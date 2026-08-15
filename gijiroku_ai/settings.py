"""ユーザー設定（Gemini モデル名・プロンプト）の永続化。

環境変数（gijiroku_ai/config.py）は未設定時のデフォルト値として扱い、
設定ファイル（data/settings.json）に値が保存されていればそちらを優先する。
DB ではなく単一の JSON ファイルで管理する（設定項目が少なくスキーマ変更の
必要が薄いため）。
"""

import json
import logging
import threading

from gijiroku_ai.config import get_config

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = """\
あなたは会議のトランスクリプト（文字起こし）から議事録を作成するアシスタントです。
与えられたトランスクリプトを読み、以下の JSON 形式で1つのオブジェクトのみを出力してください。
コードフェンスや説明文は不要です。JSON 以外の文字を出力しないでください。

{
  "title": "会議内容を表す短い見出し（30文字程度）",
  "summary": "会議の議事録本文（Markdown形式）。下記「議事録本文について」の指示に従うこと",
  "decisions": ["会議で決定した事項の箇条書き（無ければ空配列）"],
  "action_items": ["宿題・タスクなどのアクションアイテムの箇条書き（無ければ空配列）"],
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
- ここで対応付けた名前は、文字起こし表示の話者ラベルとして使われます。
- ローカルの音声認識による自動文字起こしのため、固有名詞・数値・専門用語などに
  誤認識が含まれることがあります。文脈から明らかな誤りは適宜補正して解釈して
  構いませんが、事実を創作しないでください。

議事録本文（summary）について:
- 単なる短い要約ではなく、会議で話された内容を漏らさず記録した議事録として作成してください。
  短くまとめるために話題や発言内容を省略・圧縮しないこと。
- Markdown 形式で記述してください（見出し `##`、箇条書き `-`、強調 `**太字**` などを適切に使う）。
- 話された議題・アジェンダごとに `##` 見出しで区切り、各議題の中で出た発言・議論の流れ・
  補足情報・数値やデータ・懸念点・保留事項などを箇条書きや段落で具体的に記述すること。
- 決定事項やアクションアイテムは別フィールド（decisions / action_items）に記載するため、
  summary 内で重複して詳細に書く必要はないが、文脈として触れても構わない。
- 誰がどの発言をしたかが議事録として重要な場合は、話者ラベルを添えて記述すること。
- トランスクリプト中の発言から発話者の個人名が判明する場合（呼びかけ・自己紹介・
  敬称など）は、議事録本文中では匿名ラベルの代わりにその名前を用いても構いません。
"""


_KEYS = ("gemini_model", "prompt")

Settings = dict[str, str]

_lock = threading.Lock()


def _settings_path():
    return get_config().data_dir / "settings.json"


def _load_locked() -> Settings:
    """`_lock` を保持した状態で呼び出すこと。"""
    path = _settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("settings.json の読み込みに失敗したため無視する: %s", path)
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in _KEYS and isinstance(v, str) and v}


def load_settings() -> Settings:
    with _lock:
        return _load_locked()


def save_settings(patch: dict[str, str | None]) -> Settings:
    """既存設定に patch をマージして保存する。値が空文字/None のキーは削除する。"""
    with _lock:
        current = _load_locked()
        for key in _KEYS:
            if key not in patch:
                continue
            value = patch[key]
            if value:
                current[key] = value
            else:
                current.pop(key, None)
        path = _settings_path()
        path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return current


def effective_gemini_model() -> str:
    return load_settings().get("gemini_model") or get_config().gemini_model


def effective_prompt() -> str:
    return load_settings().get("prompt") or DEFAULT_PROMPT


def effective_whisper_model() -> str:
    """ローカル文字起こしの mlx-whisper モデル（環境変数由来）。"""
    return get_config().whisper_model


def effective_whisper_language() -> str | None:
    """文字起こしの言語。空なら自動判定（None）。"""
    return get_config().whisper_language or None


def effective_hf_token() -> str:
    """pyannote 用 HuggingFace トークン（未設定なら空文字で話者識別スキップ）。"""
    return get_config().hf_token
