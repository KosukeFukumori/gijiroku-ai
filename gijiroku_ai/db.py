"""SQLite 接続管理と DB 初期化。

接続は操作ごとに短命に作る（get_conn コンテキストマネージャ）。スキーマ定義と
マイグレーションは gijiroku_ai/migrations.py に集約されており、init_db が
起動時に未適用分を自動適用する。
"""

import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from gijiroku_ai.config import get_config


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """短命の SQLite 接続を返す。commit/close は自動で行う。"""
    conn = sqlite3.connect(get_config().db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def new_public_id() -> str:
    """URL 用のランダム ID を生成する（16 文字の16進文字列）。"""
    return secrets.token_hex(8)


def init_db() -> None:
    """DB を初期化する。未適用のマイグレーションがあれば自動適用する。"""
    from gijiroku_ai import migrations

    with get_conn() as conn:
        migrations.apply_all(conn)
