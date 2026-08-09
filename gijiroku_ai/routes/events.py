"""状態変化のリアルタイム通知 API（SSE）。"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from gijiroku_ai.events import sse_stream

router = APIRouter(prefix="/api")


@router.get("/events")
def events() -> StreamingResponse:
    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
