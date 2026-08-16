"""バックグラウンド処理ワーカー。

pending の録音を1件ずつ、Vertex AI (Gemini) へ音声を直接渡して
文字起こし・話者識別・議事録生成（要約・決定事項・アクションアイテム）まで
をまとめて行う処理キュー（同時実行1）を別スレッドで動かす。denroku と異なり
NAS 同期は無いため、処理キューのみのシンプルな構成になる。

失敗時のリトライには denroku と同様バックオフを挟み、書き込み途中の
ファイルを掴む心配は無い（アップロード API がファイル書き込み完了後に
DB へ pending 登録するため、denroku の「アップロード安定確認」は不要）。

進行状況（ステータス変化・セグメント追加・要約の生成途中テキスト）は
events モジュール経由で SSE 購読中のブラウザへリアルタイム配信する。
"""

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from gijiroku_ai import events, gemini, storage, transcribe
from gijiroku_ai.db import get_conn
from gijiroku_ai.timeutil import now_iso

logger = logging.getLogger(__name__)

MAX_RETRY = 2

# リトライ間のバックオフ（秒）。retry_count=1 なら先頭、以降は末尾の値を使う。
# バックオフが無いと処理ループが約1秒後に同じ行を拾い直し、GCS アップロード
# 失敗や Gemini API のレート制限のような分単位で継続する障害でリトライ上限
# を数秒で使い切って error に固定化してしまうのを防ぐ。
_RETRY_BACKOFF_SEC = (60.0, 300.0)

# 要約ストリーミングの progress 配信を間引く最小間隔（秒）。
_SUMMARY_PROGRESS_INTERVAL = 0.15

_stop = threading.Event()
_thread: threading.Thread | None = None

# 進行中の処理に対する協調的キャンセル。ワーカーと API は同一プロセスの
# 別スレッドで動くため、メモリ上の集合で「今処理中の録音」への中断要求を
# やり取りする。
_active_lock = threading.Lock()
_active: set[int] = set()  # 処理中の recording_id
_cancelled: set[int] = set()  # 中断要求が来た recording_id


class _Cancelled(Exception):
    """進行中の処理が外部から中断要求されたことを表す内部例外。"""


# 処理ループに一時的に行を拾わせないための見送り予約（recording_id → 解除時刻）。
# リトライのバックオフに使う。メモリ上のためプロセス再起動で消えるが、
# 消えても即座に再試行されるだけで安全側に倒れる。
_defer_lock = threading.Lock()
_defer_until: dict[int, float] = {}


def _defer(recording_id: int, delay_sec: float) -> None:
    with _defer_lock:
        _defer_until[recording_id] = time.monotonic() + delay_sec


def clear_defer(recording_id: int) -> None:
    """見送り予約を取り消す。手動 retry を即時に処理させるために呼ぶ。"""
    with _defer_lock:
        _defer_until.pop(recording_id, None)


def _first_ready(rows: list[sqlite3.Row]) -> sqlite3.Row | None:
    """見送り予約中でない最初の行を返す。期限切れの予約はあわせて掃除する。"""
    now = time.monotonic()
    with _defer_lock:
        for rid in [r for r, t in _defer_until.items() if t <= now]:
            del _defer_until[rid]
        for row in rows:
            if row["id"] not in _defer_until:
                return row
    return None


def request_cancel(recording_id: int) -> bool:
    """指定録音が処理中なら中断を要求する。処理中でなければ False を返す。

    削除・リトライなど、進行中タスクの結果を捨てて状態を切り替えたい
    エンドポイントから、DB を書き換える前に呼ぶこと。
    """
    with _active_lock:
        if recording_id in _active:
            _cancelled.add(recording_id)
            return True
        return False


def _raise_if_cancelled(recording_id: int) -> None:
    with _active_lock:
        if recording_id in _cancelled:
            raise _Cancelled


@contextmanager
def _activate(recording_id: int) -> Iterator[bool]:
    """処理中の録音として登録し、終了時に登録と中断要求を確実に解除する。"""
    with _active_lock:
        if recording_id in _active:
            acquired = False
        else:
            _active.add(recording_id)
            _cancelled.discard(recording_id)
            acquired = True
    if not acquired:
        yield False
        return
    try:
        yield True
    finally:
        with _active_lock:
            _active.discard(recording_id)
            _cancelled.discard(recording_id)


def _set_status(
    recording_id: int, public_id: str, status: str, error: str | None = None
) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE recordings SET process_status = ?, error_message = ?, "
            "updated_at = ? WHERE id = ?",
            (status, error, now_iso(), recording_id),
        )
    events.publish(
        {"type": "recording_updated", "recording_id": public_id, "process_status": status}
    )


def _set_status_checked(
    recording_id: int, public_id: str, status: str, error: str | None = None
) -> None:
    """中断要求が無いことをロック下で確認してからステータスを書き込む。"""
    with _active_lock:
        if recording_id in _cancelled:
            raise _Cancelled
        _set_status(recording_id, public_id, status, error)


def _fail(recording_id: int, public_id: str, exc: Exception) -> None:
    """処理失敗を記録する。リトライ上限内なら pending に戻す（最初からやり直す）。"""
    logger.exception("処理失敗: %s", public_id)
    with _active_lock:
        if recording_id in _cancelled:
            logger.info("中断要求済みのため失敗ステータスの書き込みをスキップ: %s", public_id)
            return
        with get_conn() as conn:
            row = conn.execute(
                "SELECT retry_count FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if row is None:
                return  # 処理中に削除された
            retry = row["retry_count"] + 1
            status = "pending" if retry <= MAX_RETRY else "error"
            conn.execute(
                "UPDATE recordings SET retry_count = ?, process_status = ?, "
                "error_message = ?, updated_at = ? WHERE id = ?",
                (retry, status, str(exc), now_iso(), recording_id),
            )
    if status != "error":
        delay = _RETRY_BACKOFF_SEC[min(retry, len(_RETRY_BACKOFF_SEC)) - 1]
        _defer(recording_id, delay)
        logger.info(
            "リトライ %d/%d 回目を %.0f 秒後に予約: %s",
            retry, MAX_RETRY, delay, public_id,
        )
    events.publish(
        {"type": "recording_updated", "recording_id": public_id, "process_status": status}
    )


def _process_stage(recording_id: int, public_id: str, stored_filename: str) -> None:
    """2段階で処理する。

    1. ローカル（mlx-whisper + pyannote）で文字起こし・話者識別 → segments 保存
    2. 話者ラベル付きトランスクリプトを Gemini に渡して議事録生成 → 保存
    """
    local_path = storage.path_for(stored_filename)
    logger.info("処理開始: %s", public_id)

    def on_stage(text: str) -> None:
        events.publish(
            {"type": "stage_progress", "recording_id": public_id, "text": text}
        )

    # 確定順に並んだ DB 上の id。話者識別完了後、最終結果の区間と出現順で
    # 対応付けて speaker を UPDATE するために使う（浮動小数点の start_sec を
    # キーにした突き合わせは、verbose 出力のテキストをパースした値と
    # mlx-whisper の生の戻り値との丸め誤差で一致しないことがあり、
    # 区間の重複挿入を招くため使わない）。
    partial_seg_ids: list[int] = []

    def on_partial_segment(start: float, end: float, text: str) -> None:
        """文字起こしが1区間確定するたびに、話者ラベル未確定のまま即 DB へ保存する。

        リロード時にも直前までの文字起こし内容が見えるよう、話者識別の完了を
        待たずに保存する。話者が確定したら同じ id で segment_added を再配信し、
        フロント側で該当区間を更新させる。
        """
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO transcript_segments "
                "(recording_id, start_sec, end_sec, text, speaker) "
                "VALUES (?, ?, ?, ?, NULL)",
                (recording_id, start, end, text),
            )
            seg_id = cur.lastrowid
            assert seg_id is not None
        partial_seg_ids.append(seg_id)
        events.publish(
            {
                "type": "segment_added",
                "recording_id": public_id,
                "segment": {
                    "id": seg_id,
                    "start_sec": start,
                    "end_sec": end,
                    "speaker": None,
                    "text": text,
                },
            }
        )

    def is_cancelled() -> bool:
        with _active_lock:
            return recording_id in _cancelled

    # Stage 1: ローカル文字起こし＋話者識別（長時間音声だと数分〜十数分かかる。
    # 子プロセスで実行し、進捗を stage_progress / segment_added で中継しつつ、
    # 中断要求が来たら子プロセスごと終了させる）
    _raise_if_cancelled(recording_id)
    try:
        segments = transcribe.transcribe(
            local_path,
            on_stage=on_stage,
            on_segment=on_partial_segment,
            should_cancel=is_cancelled,
        )
    except transcribe.Cancelled as exc:
        raise _Cancelled from exc
    _raise_if_cancelled(recording_id)
    logger.info("文字起こし完了: %s（%d区間）", public_id, len(segments))

    duration = segments[-1].end_sec if segments else 0.0
    with get_conn() as conn:
        conn.execute(
            "UPDATE recordings SET duration_sec = ? WHERE id = ?",
            (duration, recording_id),
        )

    # 話者識別が確定した区間だけ speaker を UPDATE し、フロントへ再配信する
    # （id は on_partial_segment で保存済みの行を出現順で引き当てる。
    # 万一対応が取れない区間があれば、取りこぼし防止のため新規に挿入する）。
    for i, seg in enumerate(segments):
        _raise_if_cancelled(recording_id)
        seg_id = partial_seg_ids[i] if i < len(partial_seg_ids) else None
        with get_conn() as conn:
            if seg_id is None:
                cur = conn.execute(
                    "INSERT INTO transcript_segments "
                    "(recording_id, start_sec, end_sec, text, speaker) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (recording_id, seg.start_sec, seg.end_sec, seg.text, seg.speaker),
                )
                seg_id = cur.lastrowid
            elif seg.speaker is not None:
                conn.execute(
                    "UPDATE transcript_segments SET speaker = ? WHERE id = ?",
                    (seg.speaker, seg_id),
                )
            else:
                continue
        events.publish(
            {
                "type": "segment_added",
                "recording_id": public_id,
                "segment": {
                    "id": seg_id,
                    "start_sec": seg.start_sec,
                    "end_sec": seg.end_sec,
                    "speaker": seg.speaker,
                    "text": seg.text,
                },
            }
        )

    # Stage 2: Gemini でトランスクリプトから議事録生成
    last_publish = 0.0

    def on_partial(text: str) -> None:
        _raise_if_cancelled(recording_id)
        nonlocal last_publish
        now = time.monotonic()
        if now - last_publish < _SUMMARY_PROGRESS_INTERVAL:
            return
        last_publish = now
        events.publish(
            {"type": "summary_progress", "recording_id": public_id, "text": text}
        )

    events.publish(
        {
            "type": "stage_progress",
            "recording_id": public_id,
            "text": "議事録を生成しています（Gemini）",
        }
    )
    transcript_text = transcribe.to_transcript_text(segments)
    result = gemini.generate_minutes(transcript_text, on_partial=on_partial)

    with _active_lock:
        if recording_id in _cancelled:
            raise _Cancelled
        with get_conn() as conn:
            conn.execute(
                "UPDATE recordings SET title = ?, summary = ?, decisions = ?, "
                "action_items = ? WHERE id = ?",
                (
                    result.title,
                    result.summary,
                    json.dumps(result.decisions, ensure_ascii=False),
                    json.dumps(result.action_items, ensure_ascii=False),
                    recording_id,
                ),
            )
            # Gemini が匿名ラベル→実名を特定できた場合、文字起こしの話者ラベルを
            # 実名へ振り替える。フロントは done イベントで詳細を再取得するため、
            # ここで DB を更新しておけば追加のイベントなしに表示へ反映される。
            for anon_label, real_name in result.speaker_map.items():
                conn.execute(
                    "UPDATE transcript_segments SET speaker = ? "
                    "WHERE recording_id = ? AND speaker = ?",
                    (real_name, recording_id, anon_label),
                )


def _rediarize_stage(recording_id: int, public_id: str, stored_filename: str) -> None:
    """既存の文字起こし区間はそのまま、話者識別だけをやり直して speaker を更新する。"""
    local_path = storage.path_for(stored_filename)

    def on_stage(text: str) -> None:
        events.publish(
            {"type": "stage_progress", "recording_id": public_id, "text": text}
        )

    def is_cancelled() -> bool:
        with _active_lock:
            return recording_id in _cancelled

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, start_sec, end_sec, text FROM transcript_segments "
            "WHERE recording_id = ? ORDER BY start_sec",
            (recording_id,),
        ).fetchall()

    _raise_if_cancelled(recording_id)
    try:
        turns = transcribe.diarize(local_path, on_stage=on_stage, should_cancel=is_cancelled)
    except transcribe.Cancelled as exc:
        raise _Cancelled from exc
    _raise_if_cancelled(recording_id)

    if not turns:
        raise RuntimeError(
            "話者識別に失敗しました（HF_TOKEN 未設定・規約未同意・認証エラーの"
            "可能性があります。サーバのログを確認してください）"
        )

    segments = [
        transcribe.TranscriptSegment(
            start_sec=row["start_sec"], end_sec=row["end_sec"], text=row["text"], speaker=None
        )
        for row in rows
    ]
    for seg in segments:
        seg.speaker = transcribe.speaker_for(seg.start_sec, seg.end_sec, turns)
    segments = transcribe.relabel_speakers(segments)

    for row, seg in zip(rows, segments, strict=True):
        _raise_if_cancelled(recording_id)
        with get_conn() as conn:
            conn.execute(
                "UPDATE transcript_segments SET speaker = ? WHERE id = ?",
                (seg.speaker, row["id"]),
            )
        events.publish(
            {
                "type": "segment_added",
                "recording_id": public_id,
                "segment": {
                    "id": row["id"],
                    "start_sec": seg.start_sec,
                    "end_sec": seg.end_sec,
                    "speaker": seg.speaker,
                    "text": seg.text,
                },
            }
        )


def rediarize_job(recording_id: int, public_id: str, stored_filename: str) -> None:
    """完了済み録音に対し、話者識別だけを再実行する（文字起こしはやり直さない）。

    処理キュー（pending 拾い上げ）とは別に、API から直接スレッド起動で呼ばれる。
    """
    with _activate(recording_id) as acquired:
        if not acquired:
            return  # 既に処理中
        try:
            _rediarize_stage(recording_id, public_id, stored_filename)
            _set_status_checked(recording_id, public_id, "done")
            logger.info("話者識別の再実行が完了: %s", public_id)
        except _Cancelled:
            logger.info("中断要求により話者識別の再実行を打ち切り（状態は要求元が設定）: %s", public_id)
        except Exception as exc:
            logger.exception("話者識別の再実行に失敗: %s", public_id)
            with _active_lock:
                if recording_id in _cancelled:
                    return
            _set_status(recording_id, public_id, "error", str(exc))


def process_job(recording_id: int, public_id: str, stored_filename: str) -> None:
    """録音1件を処理する（処理キュー）。

    中断要求が来たら打ち切り、失敗したら pending に戻す（リトライ上限で error）。
    """
    with _activate(recording_id) as acquired:
        if not acquired:
            return  # 既に処理中
        try:
            with get_conn() as conn:
                cur = conn.execute(
                    "SELECT process_status FROM recordings WHERE id = ?",
                    (recording_id,),
                ).fetchone()
            if cur is None or cur["process_status"] != "pending":
                return

            _set_status_checked(recording_id, public_id, "processing")
            _process_stage(recording_id, public_id, stored_filename)
            _set_status_checked(recording_id, public_id, "done")
            logger.info("処理完了: %s", public_id)
        except _Cancelled:
            logger.info("中断要求により処理を打ち切り（状態は要求元が設定）: %s", public_id)
        except Exception as exc:  # noqa: BLE001 - 想定外の例外も retry/error 記録に回す
            _fail(recording_id, public_id, exc)


def _recover_interrupted() -> None:
    """前回起動時に処理中のまま落ちた録音を pending へ戻す。

    起動直後はまだワーカーが動いていないため、processing の行はすべて
    中断されたもの。
    """
    with get_conn() as conn:
        conn.execute(
            "UPDATE recordings SET process_status = 'pending' "
            "WHERE process_status = 'processing'"
        )


def _process_loop() -> None:
    while not _stop.is_set():
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, public_id, stored_filename FROM recordings "
                "WHERE process_status = 'pending' ORDER BY id"
            ).fetchall()
        row = _first_ready(rows)
        if row is None:
            _stop.wait(1)
            continue
        try:
            process_job(row["id"], row["public_id"], row["stored_filename"])
        except Exception:
            logger.exception("処理ループで想定外の例外（次回ポーリングで再試行）")
        _stop.wait(1)  # 連続処理の合間に停止要求を確認


def start() -> None:
    """処理ワーカーを開始する。"""
    global _thread
    _stop.clear()
    _recover_interrupted()
    _thread = threading.Thread(target=_process_loop, daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
