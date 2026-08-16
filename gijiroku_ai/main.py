"""議事録AI FastAPI アプリケーション。

API とフロントエンド（ビルド済み SPA）を単一ポートで配信する。起動時に
DB 初期化とバックグラウンドワーカー（議事録生成）を開始する。
"""

import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import FrameType

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gijiroku_ai import events as events_module
from gijiroku_ai import worker
from gijiroku_ai.config import get_config
from gijiroku_ai.db import init_db
from gijiroku_ai.routes import events, recordings, settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _hook_shutdown_signals() -> None:
    """SIGINT/SIGTERM を横取りし、uvicorn 本来の処理より先に SSE を止める。

    uvicorn はグレースフルシャットダウン時、既存コネクション（SSE の常時
    接続を含む）が閉じるのを待ってから lifespan の shutdown イベントを
    発行する。そのため lifespan 側で events.shutdown() を呼んでも「SSE が
    閉じるのを待っている間は絶対に呼ばれない」というデッドロックになる。
    シグナル受信時点で即座に events.shutdown() を呼び、直後に uvicorn が
    既に登録済みのハンドラへ処理を引き継ぐことで両立させる。
    """
    for sig in (signal.SIGINT, signal.SIGTERM):
        original = signal.getsignal(sig)

        def _handler(
            signum: int, frame: FrameType | None, _original=original
        ) -> None:
            events_module.shutdown()
            if callable(_original):
                _original(signum, frame)

        signal.signal(sig, _handler)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    worker.start()
    _hook_shutdown_signals()
    yield
    worker.stop()
    events_module.shutdown()


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
