"""起動時に実行する DB スキーマの自動マイグレーション。

- スキーマバージョンは SQLite 標準の PRAGMA user_version で管理する
- MIGRATIONS にバージョン昇順で登録し、現在の user_version より
  大きいものだけを順に適用する。全適用後に user_version を更新する
- 各マイグレーションは冪等（IF NOT EXISTS、_has_column による存在確認など）
  に書くこと

マイグレーションの追加手順:
    1. 適用関数 `_m<N>_<内容>(conn)` を定義する（冪等に書く）
    2. MIGRATIONS の末尾に (N, "説明", 関数) を追加する（N は最終+1）
    3. 新規 DB もマイグレーションの積み上げだけで構築されるため、
       ベースラインスキーマ（_m1）は書き換えないこと
"""

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

_BASELINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- URL・API で使う推測困難なランダム ID（連番の露出を避ける）
    public_id TEXT UNIQUE NOT NULL,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    duration_sec REAL,
    title TEXT,
    meeting_datetime TEXT NOT NULL,
    -- pending | processing | done | error
    process_status TEXT NOT NULL DEFAULT 'pending',
    summary TEXT,
    decisions TEXT,     -- JSON 配列文字列
    action_items TEXT,  -- JSON 配列文字列
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    -- 個人名（推定できた場合）または「話者A」等の匿名ラベル。NULL は未識別
    speaker TEXT,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_recording
    ON transcript_segments(recording_id);
"""


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """テーブルに列が存在するか。ALTER TABLE ADD COLUMN の冪等化に使う。"""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _m1_baseline(conn: sqlite3.Connection) -> None:
    conn.executescript(_BASELINE_SCHEMA)


# (バージョン, 説明, 適用関数) をバージョン昇順で並べる
MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "ベースラインスキーマ", _m1_baseline),
]


def apply_all(conn: sqlite3.Connection) -> None:
    """未適用のマイグレーションを順に適用し、user_version を進める。"""
    versions = [v for v, _, _ in MIGRATIONS]
    if versions != sorted(set(versions)):
        raise RuntimeError("MIGRATIONS のバージョンが昇順・一意になっていない")

    current = conn.execute("PRAGMA user_version").fetchone()[0]
    latest = versions[-1]
    if current > latest:
        # 旧バージョンのコードで新しい DB を開いている。互換性がないため停止
        raise RuntimeError(
            f"DB スキーマ (v{current}) がコード (v{latest}) より新しい。"
            "アプリを更新するか、DB のバックアップを確認すること"
        )

    for version, description, migrate in MIGRATIONS:
        if version <= current:
            continue
        logger.info("マイグレーション適用: v%d %s", version, description)
        migrate(conn)
        # PRAGMA はプレースホルダを使えないため int を検証済みの値として埋め込む
        conn.execute(f"PRAGMA user_version = {int(version)}")

    if current < latest:
        logger.info("DB スキーマを v%d → v%d に更新した", current, latest)
