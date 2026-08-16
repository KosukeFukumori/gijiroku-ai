"""アプリ内イベントのパブサブと SSE 配信。

ワーカースレッドで起きた状態変化（文字起こし進行・要約生成）をブラウザへ
リアルタイムに通知するための仕組み。購読者ごとに Queue を持ち、publish は
全購読者へブロードキャストする。

イベントの種類（type フィールド）:
- recordings_changed: 一覧に増減・状態変化があった（一覧の再読込を促す）
- recording_updated:  特定録音の process_status が変わった
- stage_progress:     処理中の大まかな段階を表す短いテキスト（都度上書き。
                       ローカル文字起こし・話者識別のように segment_added /
                       summary_progress が出るまで無反応に見える区間の
                       つなぎとして使う）
- segment_added:      文字起こしセグメントが1件追加、または既存区間の話者が
                       確定して更新された（区間確定時は speaker=None で即
                       DB 保存・配信され、リロード後も直前までの内容が残る。
                       話者識別完了後、同じ id で speaker 入りが再配信される）
- summary_progress:   要約の生成途中テキスト（累積）
"""

import json
import logging
import queue
import threading
import time
from collections.abc import Iterator

logger = logging.getLogger(__name__)

# 購読者キューの上限。溢れた購読者へのイベントは黙って捨てる
# （ローカル利用前提のため、遅い購読者でワーカーを止めない方を優先）
_QUEUE_SIZE = 256

# イベントが無い間も接続維持のためコメント行を流す間隔（秒）
KEEPALIVE_SEC = 15

# 破棄警告のレート制限間隔（秒）。イベントがバーストして購読者キューが
# 溢れても、破棄自体は無害（フロントは recording_updated/recordings_changed
# を受けて一覧を再取得するため自己回復する）ため、警告は間引いて件数だけ
# まとめて報告する。
_DROP_WARN_INTERVAL = 5.0

_lock = threading.Lock()
_subscribers: list[queue.Queue] = []

_drop_lock = threading.Lock()
_dropped_since_warn = 0
_last_drop_warn = 0.0


def _note_drop(event_type: str | None) -> None:
    """イベント破棄を記録し、間隔を空けて件数入りの警告を出す。"""
    global _dropped_since_warn, _last_drop_warn
    with _drop_lock:
        _dropped_since_warn += 1
        now = time.monotonic()
        if now - _last_drop_warn < _DROP_WARN_INTERVAL:
            return
        count = _dropped_since_warn
        _dropped_since_warn = 0
        _last_drop_warn = now
    logger.warning(
        "イベントキューが満杯のため直近 %d 件を破棄しました（最新の種別: %s）",
        count,
        event_type,
    )


def publish(event: dict) -> None:
    """イベントを全購読者へ配信する（どのスレッドからでも呼べる）。

    put_nowait のため購読者が遅くてもブロックしない。溢れた分は破棄する。
    """
    with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(event)
        except queue.Full:
            _note_drop(event.get("type"))


def sse_stream() -> Iterator[str]:
    """購読を開始し、SSE 形式でイベントを流し続けるジェネレータ。

    クライアント切断時は GeneratorExit で finally が走り、購読解除される。
    """
    q: queue.Queue = queue.Queue(maxsize=_QUEUE_SIZE)
    with _lock:
        _subscribers.append(q)
    try:
        yield ": connected\n\n"
        while True:
            try:
                event = q.get(timeout=KEEPALIVE_SEC)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        with _lock:
            _subscribers.remove(q)
