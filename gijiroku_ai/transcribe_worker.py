"""文字起こし・話者識別を行う子プロセス（`python -m gijiroku_ai.transcribe_worker`）。

mlx-whisper / pyannote の処理は一度呼び出すと数分〜十数分ブロックし、
Python レベルでは割り込めない（協調的キャンセルのチェック点が無い）。
そのため親プロセス（worker）から kill できるよう、重い処理はこの独立した
子プロセスで実行し、進捗と結果を標準出力の NDJSON で親へ返す。

標準出力には HuggingFace のダウンロード表示など想定外の出力が混ざりうるため、
親が確実に見分けられるよう各行を `_SENTINEL` で始める。標準エラーは親の
標準エラーをそのまま継承し、ログとしてサーバのコンソールに出す。

出力するメッセージ（type フィールド）:
- stage   : 処理段階を表す短いテキスト
- segment : 文字起こし途中の1区間（逐次表示用。話者ラベルは未確定）
- segments: 文字起こしの最終結果（全区間）
- turns   : 話者ダイアライゼーションの区間 [start, end, label]
- error   : 処理失敗（メッセージ付き。終了コードも 1 になる）
"""

import argparse
import importlib
import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from gijiroku_ai import settings

# NDJSON 行の目印。これで始まる行だけを親がメッセージとして解釈する。
SENTINEL = "@@GIJIROKU@@"

# mlx-whisper が verbose=True のとき1区間ごとに print する行の形式
# 例: `[00:12.340 --> 00:15.120] こんにちは`
_VERBOSE_LINE_RE = re.compile(r"^\[([\d:.]+) --> ([\d:.]+)\]\s*(.*)$")


def emit(message: dict[str, Any]) -> None:
    """1メッセージを NDJSON 1行として親へ送る。"""
    sys.stdout.write(SENTINEL + json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _stage(text: str) -> None:
    emit({"type": "stage", "text": text})


def _parse_timestamp(text: str) -> float:
    """`[hh:]mm:ss.mmm` 形式を秒に変換する。"""
    parts = text.split(":")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def _install_segment_hook(module: Any) -> None:
    """mlx-whisper の verbose 出力を横取りし、区間ごとに親へ送る。

    mlx-whisper には区間確定時のコールバックが無いが、verbose=True のときは
    モジュール内で `print` を呼んで確定区間を出力する。モジュールの
    グローバル名 `print` を差し替えることで、これを逐次通知の代わりに使う
    （組み込みの print はモジュールグローバルに影があると解決されない）。
    """

    def hook(*args: Any, **_kwargs: Any) -> None:
        line = " ".join(str(a) for a in args)
        matched = _VERBOSE_LINE_RE.match(line)
        if matched is None:
            return  # 言語検出メッセージなど、区間以外の verbose 出力は捨てる
        text = matched.group(3).strip()
        if not text:
            return
        emit(
            {
                "type": "segment",
                "start": _parse_timestamp(matched.group(1)),
                "end": _parse_timestamp(matched.group(2)),
                "text": text,
            }
        )

    module.print = hook


def _transcribe(wav_path: Path) -> list[dict[str, Any]]:
    """mlx-whisper で文字起こしし、Whisper のセグメント配列を返す。

    word_timestamps=True で単語単位の時刻も取らせる（話者割り当ての精度が
    上がるうえ、実測では False より速い）。
    """
    import mlx_whisper

    # mlx_whisper パッケージの属性 `transcribe` は同名の関数（__init__ が
    # 再エクスポートしている）なので、モジュール自体は import_module で取る。
    _install_segment_hook(importlib.import_module("mlx_whisper.transcribe"))

    model = settings.effective_whisper_model()
    _stage(f"文字起こしを開始します（モデル: {model}）")
    started = time.monotonic()
    result: dict[str, Any] = mlx_whisper.transcribe(
        str(wav_path),
        path_or_hf_repo=model,
        language=settings.effective_whisper_language(),
        word_timestamps=True,
        verbose=True,  # 区間ごとの逐次通知（_install_segment_hook）に必要
    )
    segments = [
        {
            "start": float(s.get("start") or 0.0),
            "end": float(s.get("end") or 0.0),
            "text": str(s.get("text") or "").strip(),
        }
        for s in (result.get("segments") or [])
        if str(s.get("text") or "").strip()
    ]
    _stage(
        f"文字起こしが完了しました（{len(segments)}区間、"
        f"{time.monotonic() - started:.0f}秒）"
    )
    return segments


def _diarize(wav_path: Path) -> list[list[Any]]:
    """pyannote で話者区間 [start, end, label] を返す。使えなければ空。

    ゲートモデルのため HF_TOKEN と規約同意が必要。取得できない場合は理由を
    親へ通知して空リストを返し、話者識別なしで続行する。
    """
    token = settings.effective_hf_token()
    if not token:
        _stage("HF_TOKEN が未設定のため話者識別をスキップします")
        return []

    _stage("話者識別を開始します")
    started = time.monotonic()
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
        diarization: Any = pipeline(str(wav_path))
    except Exception:  # noqa: BLE001 - 認証失敗・未同意・DL失敗は話者識別なしで続行
        traceback.print_exc()
        _stage("話者識別に失敗したためスキップします（文字起こしのみ実行）")
        return []

    turns = [
        [float(turn.start), float(turn.end), str(label)]
        for turn, _, label in diarization.itertracks(yield_label=True)
    ]
    _stage(f"話者識別が完了しました（{time.monotonic() - started:.0f}秒）")
    return turns


def main() -> int:
    parser = argparse.ArgumentParser(description="ローカル文字起こし＋話者識別")
    parser.add_argument("wav_path", help="16kHz mono wav のパス")
    args = parser.parse_args()

    wav_path = Path(args.wav_path)
    try:
        segments = _transcribe(wav_path)
        emit({"type": "segments", "items": segments})
        emit({"type": "turns", "items": _diarize(wav_path)})
    except Exception as exc:  # noqa: BLE001 - 失敗内容を親へ伝えてから異常終了する
        traceback.print_exc()
        emit({"type": "error", "message": str(exc) or exc.__class__.__name__})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
