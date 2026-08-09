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
あなたは会議の録音を文字起こしし、議事録を作成するアシスタントです。
与えられた音声ファイルを聞き取り、以下の JSON 形式で1つのオブジェクトのみを出力してください。
コードフェンスや説明文は不要です。JSON 以外の文字を出力しないでください。

{
  "title": "会議内容を表す短い見出し（30文字程度）",
  "summary": "会議の議事録本文（Markdown形式）。下記「議事録本文について」の指示に従うこと",
  "decisions": ["会議で決定した事項の箇条書き（無ければ空配列）"],
  "action_items": ["宿題・タスクなどのアクションアイテムの箇条書き（無ければ空配列）"],
  "segments": [
    {
      "start_sec": 0.0,
      "end_sec": 3.2,
      "speaker": "話者ラベル",
      "text": "発話内容"
    }
  ]
}

議事録本文（summary）について:
- 単なる短い要約ではなく、会議で話された内容を漏らさず記録した議事録として作成してください。
  短くまとめるために話題や発言内容を省略・圧縮しないこと。
- Markdown 形式で記述してください（見出し `##`、箇条書き `-`、強調 `**太字**` などを適切に使う）。
- 話された議題・アジェンダごとに `##` 見出しで区切り、各議題の中で出た発言・議論の流れ・
  補足情報・数値やデータ・懸念点・保留事項などを箇条書きや段落で具体的に記述すること。
- 決定事項やアクションアイテムは別フィールド（decisions / action_items）に記載するため、
  summary 内で重複して詳細に書く必要はないが、文脈として触れても構わない。
- 誰がどの発言をしたかが議事録として重要な場合は、話者ラベルを添えて記述すること。

話者ラベルについて:
- 発言中の呼びかけ・自己紹介・敬称などから発話者の個人名を特定できる場合は、
  その名前をラベルにしてください（例: "田中"）
- 個人名を特定できない場合は、出現順に「話者A」「話者B」「話者C」…という
  匿名ラベルを割り当ててください
- 同一人物には常に同じラベルを使い、推測に自信が無い場合でも断定的に
  書いてよいですが、事実と異なる可能性がある推測だと分かるように
  無理に個人名を割り当てず、その場合は匿名ラベルにしてください

segments は発話順に並べ、実際に発話があった区間のみを含めてください
（無音区間は含めない）。
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
