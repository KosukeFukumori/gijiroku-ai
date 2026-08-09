"""API の入出力スキーマ（Pydantic）。"""

from typing import Literal

from pydantic import BaseModel

ProcessStatus = Literal["pending", "processing", "done", "error"]


class RecordingListItem(BaseModel):
    id: str  # 公開用ランダム ID（public_id）
    title: str | None
    meeting_datetime: str
    duration_sec: float | None
    process_status: ProcessStatus
    summary_head: str | None  # 一覧表示用の要約冒頭


class RecordingList(BaseModel):
    items: list[RecordingListItem]
    total: int


class Segment(BaseModel):
    id: int
    start_sec: float
    end_sec: float
    speaker: str | None  # 個人名 または「話者A」等。未識別は None
    text: str


class RecordingDetail(BaseModel):
    id: str  # 公開用ランダム ID（public_id）
    original_filename: str
    title: str | None
    meeting_datetime: str
    duration_sec: float | None
    process_status: ProcessStatus
    summary: str | None
    decisions: list[str]
    action_items: list[str]
    error_message: str | None
    created_at: str
    updated_at: str
    segments: list[Segment]
