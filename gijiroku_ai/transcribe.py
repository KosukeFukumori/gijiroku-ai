"""ローカル文字起こし＋話者識別（Apple Silicon / Metal 前提）の呼び出し口。

長時間の会議音声をクラウド API に丸ごと渡すと不安定なため、文字起こしと
話者識別は macOS ホスト上でローカルに行い、確定したテキスト（話者ラベル付き）
だけを Gemini に渡して議事録化する二段構成にする。

- 文字起こし: mlx-whisper（Apple MLX / Metal 最適化。large-v3 系）
- 話者識別  : pyannote.audio 3.1（PyTorch MPS で Metal を利用）

いずれも macOS ネイティブでしか GPU を使えないため、Docker コンテナ内では
なくホスト上のプロセスで動かすことを前提とする。

重い処理は子プロセス（gijiroku_ai.transcribe_worker）で実行する。mlx-whisper /
pyannote の呼び出しは一度入ると数分〜十数分ブロックし、同一プロセス内では
中断できないため、中断要求時に子プロセスごと kill できるようにするのが目的。
子プロセスは進捗（処理段階・確定した文字起こし区間）を NDJSON で流してくるので、
それをコールバック経由で SSE へ中継し、ブラウザに逐次表示する。
"""

import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gijiroku_ai.transcribe_worker import SENTINEL

logger = logging.getLogger(__name__)

# 中断要求の確認間隔（秒）。子プロセスの出力待ちをこの間隔で打ち切って確認する。
_CANCEL_POLL_SEC = 0.3


class Cancelled(RuntimeError):
    """中断要求により文字起こしを打ち切ったことを表す。"""


@dataclass
class TranscriptSegment:
    """1 発話区間。DB の transcript_segments と同じスキーマに対応する。"""

    start_sec: float
    end_sec: float
    text: str
    speaker: str | None  # 「話者A」等。話者識別できない場合は None


def _to_wav16k_mono(src: Path) -> Path:
    """pyannote / whisper 双方が扱いやすい 16kHz mono wav へ変換する。

    mlx-whisper は内部で ffmpeg を呼ぶが、pyannote には同じ波形を渡したいので
    ここで一度だけ 16kHz mono wav に正規化し、両者で共有する。
    """
    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    Path(out).unlink(missing_ok=True)  # mkstemp が作った空ファイルは ffmpeg が上書き
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(src),
                "-ac",
                "1",
                "-ar",
                "16000",
                out,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        Path(out).unlink(missing_ok=True)
        raise RuntimeError(
            f"音声の変換に失敗しました: {exc.stderr.decode(errors='replace')}"
        ) from exc
    return Path(out)


def _worker_env() -> dict[str, str]:
    """子プロセス用の環境変数を組み立てる。

    pyannote が使う torchcodec は FFmpeg の共有ライブラリ（libavutil 等）を
    @rpath 経由で読み込むが、Homebrew 版 FFmpeg の dylib には LC_RPATH が
    無いため、標準の検索パスに Homebrew の lib が含まれない環境では
    ロードに失敗する（GatedRepoError 解消後に起きる「libtorchcodec を
    ロードできない」エラー）。Homebrew の lib ディレクトリが存在すれば
    DYLD_LIBRARY_PATH へ足しておくことで、ホスト実行時に自動で解決する。
    """
    env = os.environ.copy()
    lib_dirs = [d for d in ("/opt/homebrew/lib", "/usr/local/lib") if Path(d).is_dir()]
    if lib_dirs:
        existing = env.get("DYLD_LIBRARY_PATH", "")
        merged = [*lib_dirs, *[p for p in existing.split(":") if p]]
        env["DYLD_LIBRARY_PATH"] = ":".join(dict.fromkeys(merged))
    return env


def _terminate(proc: subprocess.Popen) -> None:
    """子プロセスを確実に終了させる（SIGTERM で落ちなければ SIGKILL）。"""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _run_worker(
    wav_path: Path,
    on_stage: Callable[[str, str], None] | None,
    on_segment: Callable[[float, float, str], None] | None,
    should_cancel: Callable[[], bool] | None,
    diarize_only: bool = False,
) -> tuple[list[dict[str, Any]], list[tuple[float, float, str]]]:
    """子プロセスを起動し、文字起こし区間と話者区間を受け取る。

    子プロセスの標準エラーは親のものをそのまま継承させ、モデルのダウンロード
    表示やスタックトレースがサーバのログに出るようにする。
    diarize_only=True の場合、文字起こしは行わず話者識別だけを実行する
    （戻り値の segments は空リストになる）。
    """
    cmd = [sys.executable, "-m", "gijiroku_ai.transcribe_worker", str(wav_path)]
    if diarize_only:
        cmd.append("--diarize-only")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,  # 行バッファ（逐次表示のため）
        env=_worker_env(),
    )

    # readline はブロックするため、読み取りは別スレッドに任せ、本体は
    # キューをタイムアウト付きで待ちながら中断要求を確認する。
    lines: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    segments: list[dict[str, Any]] = []
    turns: list[tuple[float, float, str]] = []
    error: str | None = None
    try:
        while True:
            if should_cancel is not None and should_cancel():
                raise Cancelled
            try:
                line = lines.get(timeout=_CANCEL_POLL_SEC)
            except queue.Empty:
                continue
            if line is None:
                break
            if not line.startswith(SENTINEL):
                continue  # 想定外の標準出力（ダウンロード表示など）は無視
            message = json.loads(line[len(SENTINEL) :])
            kind = message.get("type")
            if kind == "stage":
                text = str(message["text"])
                logger.info(text)
                if on_stage is not None:
                    on_stage(text, str(message["step"]))
            elif kind == "segment" and on_segment is not None:
                on_segment(
                    float(message["start"]), float(message["end"]), str(message["text"])
                )
            elif kind == "segments":
                segments = list(message["items"])
            elif kind == "turns":
                turns = [
                    (float(s), float(e), str(label)) for s, e, label in message["items"]
                ]
            elif kind == "error":
                error = str(message["message"])
    finally:
        _terminate(proc)

    if error is not None:
        raise RuntimeError(f"文字起こしに失敗しました: {error}")
    if proc.returncode != 0:
        raise RuntimeError(
            f"文字起こしプロセスが異常終了しました（終了コード {proc.returncode}）"
        )
    return segments, turns


def speaker_for(
    start: float, end: float, turns: list[tuple[float, float, str]]
) -> str | None:
    """発話区間に最も重なる話者ターンのラベルを返す（重なりが無ければ None）。"""
    best_label: str | None = None
    best_overlap = 0.0
    for t_start, t_end, label in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = label
    return best_label


def relabel_speakers(
    segments: list[TranscriptSegment],
) -> list[TranscriptSegment]:
    """pyannote の内部ラベル（SPEAKER_00 等）を出現順の「話者A/B/C…」へ振り直す。"""
    mapping: dict[str, str] = {}
    for seg in segments:
        if seg.speaker is None or seg.speaker in mapping:
            continue
        mapping[seg.speaker] = f"話者{chr(ord('A') + len(mapping))}"
    for seg in segments:
        if seg.speaker is not None:
            seg.speaker = mapping[seg.speaker]
    return segments


def transcribe(
    audio_path: Path,
    on_stage: Callable[[str, str], None] | None = None,
    on_segment: Callable[[float, float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[TranscriptSegment]:
    """音声ファイルを文字起こしし、話者ラベル付きセグメントを返す。

    話者識別が使えない環境（HF_TOKEN 無し等）では speaker=None のまま返す。

    - on_stage:      処理段階が変わるたびに (テキスト, 段階の識別子) で
                     呼ばれる（SSE で表示する用途）
    - on_segment:    文字起こしが1区間確定するたびに (start, end, text) で
                     呼ばれる。話者ラベルは全区間の確定後に付くため、ここでは
                     まだ分からない
    - should_cancel: 定期的に呼ばれ、True を返すと子プロセスを終了して
                     Cancelled を送出する
    """
    wav_path = _to_wav16k_mono(audio_path)
    try:
        whisper_segments, turns = _run_worker(
            wav_path, on_stage, on_segment, should_cancel
        )
    finally:
        wav_path.unlink(missing_ok=True)

    segments = [
        TranscriptSegment(
            start_sec=float(s["start"]),
            end_sec=float(s["end"]),
            text=str(s["text"]),
            speaker=speaker_for(float(s["start"]), float(s["end"]), turns)
            if turns
            else None,
        )
        for s in whisper_segments
    ]
    return relabel_speakers(segments)


def diarize(
    audio_path: Path,
    on_stage: Callable[[str, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[tuple[float, float, str]]:
    """既存の文字起こし結果はそのままに、話者識別だけをやり直して話者区間を返す。

    HF_TOKEN 未設定・認証失敗など話者識別が使えない場合は空リストを返す。
    """
    wav_path = _to_wav16k_mono(audio_path)
    try:
        _, turns = _run_worker(
            wav_path, on_stage, None, should_cancel, diarize_only=True
        )
    finally:
        wav_path.unlink(missing_ok=True)
    return turns


def to_transcript_text(segments: list[TranscriptSegment]) -> str:
    """Gemini へ渡す話者ラベル付きプレーンテキストを組み立てる。

    形式: `[mm:ss] 話者A: 発話内容` を1行ずつ。話者未識別の行はラベルを省く。
    """
    lines: list[str] = []
    for seg in segments:
        mm, ss = divmod(int(seg.start_sec), 60)
        ts = f"[{mm:02d}:{ss:02d}]"
        prefix = f"{ts} {seg.speaker}: " if seg.speaker else f"{ts} "
        lines.append(f"{prefix}{seg.text}")
    return "\n".join(lines)
