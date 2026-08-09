"""日時フォーマットの共通ヘルパー。

DB保存・API応答はすべて UTC の ISO8601（ミリ秒・`Z` 終端）文字列に統一する。
SQLite の `datetime('now')` はオフセット情報の無い UTC 文字列を返し、
フロントエンドの `new Date()` がそれをローカル時刻と誤解釈してしまうため、
時刻生成は SQL 関数に任せず本モジュールで行う。
"""

from datetime import UTC, datetime


def now_iso() -> str:
    """現在時刻を UTC の ISO8601（ミリ秒・`Z` 終端）文字列で返す。"""
    return to_iso(datetime.now(UTC))


def to_iso(dt: datetime) -> str:
    """`datetime` を UTC の ISO8601（ミリ秒・`Z` 終端）文字列に変換する。

    tz-naive な場合は UTC とみなす。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
