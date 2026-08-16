"""Vertex AI (Gemini) クライアント（議事録生成のみ）。

文字起こし・話者識別はローカル（gijiroku_ai/transcribe.py）で確定させ、
その結果の話者ラベル付きトランスクリプト（テキスト）を Gemini に渡して
議事録（要約・決定事項・アクションアイテム）を生成する。

以前は音声を GCS 経由で Gemini に直接渡し、文字起こし〜議事録を1回で行って
いたが、長時間会議で API が不安定になるため、音声を扱う責務をローカルへ
移し、Gemini はテキスト入力のみを扱うようにした。GCS への一時アップロードも
不要になった。
"""

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import types

from gijiroku_ai import settings
from gijiroku_ai.config import get_config

logger = logging.getLogger(__name__)

# 出力上限。長時間の会議でも summary が途中で切れないよう大きめに確保する
MAX_OUTPUT_TOKENS = 65536

# 話者名解決は speaker_map のみを返す小さな出力なので、議事録より小さくてよい
_SPEAKER_NAME_MAX_OUTPUT_TOKENS = 8192

SPEAKER_NAME_PROMPT = """\
あなたは会議のトランスクリプト（文字起こし）から、匿名の話者ラベルが実際には
誰なのかを特定するアシスタントです。
与えられたトランスクリプトを読み、以下の JSON 形式で1つのオブジェクトのみを
出力してください。コードフェンスや説明文は不要です。JSON 以外の文字を
出力しないでください。

{
  "speaker_map": {"話者A": "実名または役割", "話者B": "実名または役割"}
}

トランスクリプトの形式について:
- 各行は `[mm:ss] 話者A: 発話内容` の形式です（先頭は発話開始時刻）。
- 話者は「話者A」「話者B」…の匿名ラベル、または話者識別ができなかった場合は
  ラベルが省略されています。

話者マップ（speaker_map）について:
- トランスクリプト中の匿名ラベル（話者A/話者B…）が実際には誰なのかを、
  会話の内容から特定できた場合にのみ、そのラベルをキー、特定した名前
  （個人名。分からなければ「司会」「営業担当」等の役割でも可）を値とする
  対応表を返してください。
- 特定の根拠（自己紹介・名指しの呼びかけ・敬称・所属など）が明確なラベルだけを
  含めること。推測に自信が無いラベルは speaker_map に含めないでください
  （その話者は匿名ラベルのまま残します）。
- 特定できるラベルが1つも無い場合は空オブジェクト {} を返してください。
- ローカルの音声認識による自動文字起こしのため、固有名詞・数値・専門用語などに
  誤認識が含まれることがあります。文脈から明らかな誤りは適宜補正して解釈して
  構いませんが、事実を創作しないでください。
"""


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


def _extract_json(text: str) -> dict[str, Any]:
    """LLM 応答から JSON オブジェクトを取り出す（コードフェンス等を許容）。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"応答から JSON を抽出できませんでした: {text[:200]}")
    return json.loads(match.group(0))


class MinutesResult:
    """generate_minutes の結果（議事録本文とメタ情報）。"""

    def __init__(
        self,
        title: str,
        summary: str,
        decisions: list[str],
        action_items: list[str],
    ) -> None:
        self.title = title
        self.summary = summary
        self.decisions = decisions
        self.action_items = action_items


def generate_minutes(
    transcript_text: str,
    on_partial: Callable[[str], None] | None = None,
) -> MinutesResult:
    """話者ラベル付きトランスクリプトから議事録を生成する。

    on_partial を渡すと生成途中の累積テキストから summary フィールドを抜き出して
    逐次通知する（要約ストリーミング表示用）。
    """
    stream = genai_client().models.generate_content_stream(
        model=settings.effective_gemini_model(),
        contents=[
            settings.effective_prompt(),
            "\n\n---\n以下が会議のトランスクリプトです。\n---\n",
            transcript_text,
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

    data = _extract_json(content)
    decisions = data.get("decisions") or []
    items = data.get("action_items") or []
    return MinutesResult(
        title=str(data.get("title") or "")[:100],
        summary=str(data.get("summary") or ""),
        decisions=[str(d) for d in decisions if str(d).strip()],
        action_items=[str(i) for i in items if str(i).strip()],
    )


def resolve_speaker_names(transcript_text: str) -> dict[str, str]:
    """匿名の話者ラベル（話者A等）を、会話内容から実名/役割へ解決する。

    議事録生成（generate_minutes）とは独立した別セッションで実行する。
    話者識別だけをやり直した場合（rediarize）にも、この関数だけを再実行
    すれば実名を復元できる。特定できたラベルのみを含む対応表を返す
    （それ以外は匿名ラベルのまま残す）。
    """
    response = genai_client().models.generate_content(
        model=settings.effective_gemini_model(),
        contents=[
            SPEAKER_NAME_PROMPT,
            "\n\n---\n以下が会議のトランスクリプトです。\n---\n",
            transcript_text,
        ],
        config=types.GenerateContentConfig(
            max_output_tokens=_SPEAKER_NAME_MAX_OUTPUT_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    data = _extract_json(response.text or "")
    raw_map = data.get("speaker_map") or {}
    return {
        str(k): str(v).strip()
        for k, v in raw_map.items()
        if isinstance(raw_map, dict) and str(k).strip() and str(v).strip()
    }


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
