"""Vertex AI (Gemini) クライアント。

会議録音ファイルを GCS 経由で Gemini に直接渡し、文字起こし・話者識別・
議事録生成（要約・決定事項・アクションアイテム）を1回の呼び出しでまとめて
行う（denroku/gemini.py と同じアプローチ）。

話者識別: 発話内容（呼びかけ・自己紹介等）から個人名を特定できる場合は
その名前をラベルにし、特定できない場合は「話者A」「話者B」「話者C」…の
匿名ラベルにする（会議は3人以上の参加者を想定するため、denroku のような
「自分/相手」の2者推定はしない）。
"""

import json
import logging
import re
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google import genai
from google.cloud import storage
from google.genai import types

from gijiroku_ai import settings
from gijiroku_ai.config import get_config

logger = logging.getLogger(__name__)

# 出力上限。長時間の会議でも segments + summary が途中で切れないよう大きめに確保する
MAX_OUTPUT_TOKENS = 65536


_client: genai.Client | None = None


def genai_client() -> genai.Client:
    """Vertex AI 向け genai クライアント（プロセス内シングルトン）。"""
    global _client
    if _client is None:
        config = get_config()
        _client = genai.Client(
            vertexai=True, project=config.gcp_project, location=config.gcp_location
        )
    return _client


def _convert_to_mp3(src: Path) -> Path:
    """アップロード前に mono/64k mp3 へ変換する（サイズ・トークン量の削減）。"""
    fd, out_path = tempfile.mkstemp(suffix=".mp3")
    import os

    os.close(fd)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-ac", "1", "-b:a", "64k", out_path],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        Path(out_path).unlink(missing_ok=True)
        raise RuntimeError(
            f"音声の変換に失敗しました: {exc.stderr.decode(errors='replace')}"
        ) from exc
    return Path(out_path)


def _upload_to_gcs(local_path: Path) -> tuple[str, Any]:
    """一時アップロードし、(gs:// URI, blob) を返す。呼び出し側が削除の責務を持つ。"""
    config = get_config()
    client = storage.Client(project=config.gcp_project)
    bucket = client.bucket(config.gcs_bucket)
    blob_name = f"{uuid.uuid4()}.mp3"
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(local_path))
    return f"gs://{config.gcs_bucket}/{blob_name}", blob


def _extract_json(text: str) -> dict[str, Any]:
    """LLM 応答から JSON オブジェクトを取り出す（コードフェンス等を許容）。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"応答から JSON を抽出できませんでした: {text[:200]}")
    return json.loads(match.group(0))


class ProcessResult:
    """process_recording の結果。"""

    def __init__(
        self,
        segments: list[dict[str, Any]],
        title: str,
        summary: str,
        decisions: list[str],
        action_items: list[str],
        duration_sec: float,
    ) -> None:
        self.segments = segments
        self.title = title
        self.summary = summary
        self.decisions = decisions
        self.action_items = action_items
        self.duration_sec = duration_sec


def process_recording(
    audio_path: Path,
    on_partial: Callable[[str], None] | None = None,
) -> ProcessResult:
    """音声ファイルを Gemini に渡し、文字起こし・話者識別・議事録生成を一括で行う。

    GCS への一時アップロード → generate_content → GCS 上のファイル削除、
    という流れを1回の呼び出しで完結させる。on_partial を渡すと生成途中の
    累積テキストから summary フィールドを抜き出して逐次通知する
    （要約ストリーミング表示用）。
    """
    mp3_path = _convert_to_mp3(audio_path)
    try:
        gcs_uri, blob = _upload_to_gcs(mp3_path)
    finally:
        mp3_path.unlink(missing_ok=True)

    try:
        stream = genai_client().models.generate_content_stream(
            model=settings.effective_gemini_model(),
            contents=[
                types.Part.from_uri(file_uri=gcs_uri, mime_type="audio/mp3"),
                settings.effective_prompt(),
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        content = ""
        last_partial = ""
        for chunk in stream:
            if not chunk.text:
                continue
            content += chunk.text
            if on_partial is not None:
                partial = _partial_summary(content)
                if partial and partial != last_partial:
                    last_partial = partial
                    on_partial(partial)
    finally:
        blob.delete()

    data = _extract_json(content)
    raw_segments = data.get("segments") or []
    segments = [
        {
            "start_sec": float(s.get("start_sec") or 0.0),
            "end_sec": float(s.get("end_sec") or 0.0),
            "speaker": (str(s["speaker"]) if s.get("speaker") else None),
            "text": str(s.get("text") or "").strip(),
        }
        for s in raw_segments
        if str(s.get("text") or "").strip()
    ]
    duration = segments[-1]["end_sec"] if segments else 0.0
    decisions = data.get("decisions") or []
    items = data.get("action_items") or []
    return ProcessResult(
        segments=segments,
        title=str(data.get("title") or "")[:100],
        summary=str(data.get("summary") or ""),
        decisions=[str(d) for d in decisions if str(d).strip()],
        action_items=[str(i) for i in items if str(i).strip()],
        duration_sec=duration,
    )


def _partial_summary(text: str) -> str | None:
    """生成途中の JSON 応答から summary フィールドの値を取り出す。

    閉じ引用符がまだ来ていない途中状態も許容する（ストリーミング表示用）。
    """
    match = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)', text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        return None
