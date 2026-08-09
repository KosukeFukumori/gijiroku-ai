"""議事録AI FastAPI アプリケーション。

API とフロントエンド（ビルド済み SPA）を単一ポートで配信する。起動時に
DB 初期化とバックグラウンドワーカー（議事録生成）を開始する。
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gijiroku_ai import worker
from gijiroku_ai.config import get_config
from gijiroku_ai.db import init_db
from gijiroku_ai.routes import events, recordings, settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="議事録AI", lifespan=lifespan)

app.include_router(recordings.router)
app.include_router(events.router)
app.include_router(settings.router)

_static = get_config().static_dir

if (_static / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

if (_static / "index.html").is_file():

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        """SPA のフォールバック配信。実在する静的ファイルはそのまま返す。"""
        candidate = (_static / full_path).resolve()
        if (
            full_path
            and candidate.is_relative_to(_static.resolve())
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(_static / "index.html")
