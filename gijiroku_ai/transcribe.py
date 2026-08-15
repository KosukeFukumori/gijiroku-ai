"""ローカル文字起こし＋話者識別（Apple Silicon / Metal 前提）。

長時間の会議音声をクラウド API に丸ごと渡すと不安定なため、文字起こしと
話者識別は macOS ホスト上でローカルに行い、確定したテキスト（話者ラベル付き）
だけを Gemini に渡して議事録化する二段構成にする。

- 文字起こし: mlx-whisper（Apple MLX / Metal 最適化。large-v3 系）
- 話者識別  : pyannote.audio 3.1（PyTorch MPS で Metal を利用）

いずれも macOS ネイティブでしか GPU を使えないため、このモジュールは
Docker コンテナ内ではなくホスト上のプロセスで動かすことを前提とする。

pyannote/speaker-diarization-3.1 はゲート付きモデルのため、初回利用時に
HuggingFace 上での規約同意とアクセストークン（HF_TOKEN）が必要になる。
トークン未設定・同意なしの場合は話者識別を諦め、文字起こしのみを返す
（speaker=None）。文字起こし自体はトークン不要で常に動く。
"""

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gijiroku_ai import settings

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    """1 発話区間。DB の transcript_segments と同じスキーマに対応する。"""

    start_sec: float
    end_sec: float
    text: str
    speaker: str | None  # 「話者A」等。話者識別できない場合は None


# mlx-whisper / pyannote のモデルはプロセス内で使い回す（初期化が重いため）。
_diarize_pipeline: Any | None = None
_diarize_unavailable = False  # トークン無し等で使えないと判明したら再試行しない


def _to_wav16k_mono(src: Path) -> Path:
    """pyannote / whisper 双方が扱いやすい 16kHz mono wav へ変換する。

    mlx-whisper は内部で ffmpeg を呼ぶが、pyannote には波形を直接渡したいので
    ここで一度だけ 16kHz mono wav に正規化し、両者で共有する。
    """
    fd, out = tempfile.mkstemp(suffix=".wav")
    Path(out).unlink(missing_ok=True)  # mkstemp が作った空ファイルは ffmpeg が上書き
    import os

    os.close(fd)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-ac", "1", "-ar", "16000", out],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        Path(out).unlink(missing_ok=True)
        raise RuntimeError(
            f"音声の変換に失敗しました: {exc.stderr.decode(errors='replace')}"
        ) from exc
    return Path(out)


def _transcribe_words(wav_path: Path) -> list[dict[str, Any]]:
    """mlx-whisper で文字起こしし、Whisper のセグメント配列を返す。

    word_timestamps=True を指定して単語単位の時刻も取得する（話者の割り当て
    精度を上げるため）。返り値は Whisper 標準の segment dict のリスト。
    """
    import mlx_whisper

    result: dict[str, Any] = mlx_whisper.transcribe(
        str(wav_path),
        path_or_hf_repo=settings.effective_whisper_model(),
        language=settings.effective_whisper_language(),
        word_timestamps=True,
    )
    segments = result.get("segments") or []
    return list(segments)


def _load_diarizer() -> Any | None:
    """pyannote の話者ダイアライゼーション pipeline を取得する（無ければ None）。

    ゲートモデルのため HF_TOKEN と規約同意が必要。取得できない場合は理由を
    ログに出して None を返し、以降は再試行しない（話者識別なしで続行する）。
    MPS（Metal）が使える場合はそちらへ載せる。
    """
    global _diarize_pipeline, _diarize_unavailable
    if _diarize_pipeline is not None:
        return _diarize_pipeline
    if _diarize_unavailable:
        return None

    token = settings.effective_hf_token()
    if not token:
        logger.warning(
            "HF_TOKEN が未設定のため話者識別をスキップします"
            "（文字起こしのみ実行）。pyannote の利用には HuggingFace の"
            "規約同意とトークンが必要です。"
        )
        _diarize_unavailable = True
        return None

    try:
        import torch
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=token
        )
        if pipeline is None:
            raise RuntimeError(
                "pyannote pipeline を取得できませんでした"
                "（規約未同意またはトークン不正の可能性）"
            )
        if torch.backends.mps.is_available():
            pipeline.to(torch.device("mps"))
        _diarize_pipeline = pipeline
        return pipeline
    except Exception:  # 認証失敗・未同意・DL失敗など全て話者識別なしで続行
        logger.exception(
            "pyannote pipeline の初期化に失敗したため話者識別をスキップします"
            "（規約同意・トークンを確認してください）"
        )
        _diarize_unavailable = True
        return None


def _diarize(wav_path: Path) -> list[tuple[float, float, str]]:
    """話者区間 (start, end, speaker_label) のリストを返す。使えなければ空。"""
    pipeline = _load_diarizer()
    if pipeline is None:
        return []
    diarization = pipeline(str(wav_path))
    turns: list[tuple[float, float, str]] = []
    for turn, _, label in diarization.itertracks(yield_label=True):
        turns.append((float(turn.start), float(turn.end), str(label)))
    return turns


def _speaker_for(start: float, end: float, turns: list[tuple[float, float, str]]) -> str | None:
    """発話区間に最も重なる話者ターンのラベルを返す（重なりが無ければ None）。"""
    best_label: str | None = None
    best_overlap = 0.0
    for t_start, t_end, label in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = label
    return best_label


def _relabel_speakers(
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


def transcribe(audio_path: Path) -> list[TranscriptSegment]:
    """音声ファイルを文字起こしし、話者ラベル付きセグメントを返す。

    話者識別が使えない環境（HF_TOKEN 無し等）では speaker=None のまま返す。
    """
    wav_path = _to_wav16k_mono(audio_path)
    try:
        whisper_segments = _transcribe_words(wav_path)
        turns = _diarize(wav_path)
    finally:
        wav_path.unlink(missing_ok=True)

    segments: list[TranscriptSegment] = []
    for s in whisper_segments:
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        start = float(s.get("start") or 0.0)
        end = float(s.get("end") or 0.0)
        speaker = _speaker_for(start, end, turns) if turns else None
        segments.append(
            TranscriptSegment(start_sec=start, end_sec=end, text=text, speaker=speaker)
        )
    return _relabel_speakers(segments)


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
