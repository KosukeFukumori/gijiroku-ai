"""録音アップロード・一覧・詳細・音源・削除・中断・再試行 API。"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from gijiroku_ai import audio, events, storage, worker
from gijiroku_ai.db import get_conn, new_public_id
from gijiroku_ai.models import (
    RecordingDetail,
    RecordingList,
    RecordingListItem,
    Segment,
)
from gijiroku_ai.timeutil import now_iso, to_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

SUMMARY_HEAD_LEN = 80


def _row_to_item(row) -> RecordingListItem:
    summary = row["summary"] or ""
    return RecordingListItem(
        id=row["public_id"],
        title=row["title"],
        meeting_datetime=row["meeting_datetime"],
        duration_sec=row["duration_sec"],
        process_status=row["process_status"],
        summary_head=summary[:SUMMARY_HEAD_LEN] or None,
    )


@router.post("/recordings")
async def upload_recording(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    file_modified_at: str | None = Form(None),
) -> RecordingDetail:
    ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if ext not in storage.ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(storage.ALLOWED_EXTENSIONS))
        raise HTTPException(400, f"対応していない拡張子です（対応: {allowed}）")

    public_id = new_public_id()
    stored_filename, size = storage.save_upload(public_id, file.filename or "recording", file.file)

    meeting_datetime = now_iso()
    if file_modified_at:
        try:
            meeting_datetime = to_iso(datetime.fromisoformat(file_modified_at))
        except ValueError:
            pass

    now = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO recordings "
            "(public_id, original_filename, stored_filename, size, title, "
            "meeting_datetime, created_at, updated_at, process_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                public_id,
                file.filename or stored_filename,
                stored_filename,
                size,
                title,
                meeting_datetime,
                now,
                now,
            ),
        )
    events.publish({"type": "recordings_changed"})
    return get_recording(public_id)


@router.get("/recordings")
def list_recordings(
    q: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 50,
) -> RecordingList:
    where = ["1=1"]
    params: list = []
    selectable = {"pending", "processing", "done", "error"}
    statuses = [s for s in status.split(",") if s in selectable]
    if statuses:
        placeholders = ",".join("?" * len(statuses))
        where.append(f"process_status IN ({placeholders})")
        params.extend(statuses)
    if q.strip():
        query = q.strip()
        escaped = (
            query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        like = f"%{escaped}%"
        where.append(
            "(title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' "
            "OR original_filename LIKE ? ESCAPE '\\')"
        )
        params += [like, like, like]

    cond = " AND ".join(where)
    offset = max(0, (page - 1) * page_size)
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM recordings WHERE {cond}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM recordings WHERE {cond} "
            "ORDER BY meeting_datetime DESC, id DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
    return RecordingList(items=[_row_to_item(r) for r in rows], total=total)


def _get_row(public_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM recordings WHERE public_id = ?", (public_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "録音が見つかりません")
    return row


@router.get("/recordings/{public_id}")
def get_recording(public_id: str) -> RecordingDetail:
    row = _get_row(public_id)
    with get_conn() as conn:
        segs = conn.execute(
            "SELECT id, start_sec, end_sec, speaker, text FROM transcript_segments "
            "WHERE recording_id = ? ORDER BY start_sec",
            (row["id"],),
        ).fetchall()
    try:
        decisions = json.loads(row["decisions"] or "[]")
    except json.JSONDecodeError:
        decisions = []
    try:
        action_items = json.loads(row["action_items"] or "[]")
    except json.JSONDecodeError:
        action_items = []
    return RecordingDetail(
        id=row["public_id"],
        original_filename=row["original_filename"],
        title=row["title"],
        meeting_datetime=row["meeting_datetime"],
        duration_sec=row["duration_sec"],
        process_status=row["process_status"],
        summary=row["summary"],
        decisions=decisions,
        action_items=action_items,
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        segments=[Segment(**dict(s)) for s in segs],
    )


@router.get("/recordings/{public_id}/audio")
def get_audio(public_id: str) -> Response:
    row = _get_row(public_id)
    local_path = storage.path_for(row["stored_filename"])
    if not local_path.is_file():
        raise HTTPException(404, "音源ファイルが見つかりません")
    return audio.audio_response(local_path)


@router.delete("/recordings/{public_id}")
def delete_recording(public_id: str) -> dict:
    """録音を完全削除する（DBレコード・音源ファイル・文字起こしをすべて削除）。

    処理中の録音を削除する場合も、進行中のワーカー処理を中断してから削除する。
    """
    row = _get_row(public_id)
    worker.request_cancel(row["id"])
    storage.delete(row["stored_filename"])
    with get_conn() as conn:
        conn.execute("DELETE FROM recordings WHERE id = ?", (row["id"],))
    events.publish({"type": "recordings_changed"})
    return {"ok": True}


@router.post("/recordings/{public_id}/cancel")
def cancel_recording(public_id: str) -> dict:
    """処理待ち・処理中の録音を中断する（エラー状態にして再試行可能にする）。

    進行中のローカル文字起こしは子プロセスで動いているため、中断要求を出せば
    ワーカーがその子プロセスを終了させる。まだ処理が始まっていない場合も、
    ここでステータスを変えておけばワーカーは pending 以外の行を拾わない。
    """
    row = _get_row(public_id)
    if row["process_status"] not in ("pending", "processing"):
        raise HTTPException(409, "処理待ち・処理中のアイテムのみ中断できます")
    worker.request_cancel(row["id"])
    with get_conn() as conn:
        conn.execute(
            "UPDATE recordings SET process_status = 'error', retry_count = 0, "
            "error_message = ?, updated_at = ? WHERE id = ?",
            ("ユーザー操作により中断しました", now_iso(), row["id"]),
        )
    worker.clear_defer(row["id"])
    events.publish(
        {"type": "recording_updated", "recording_id": public_id, "process_status": "error"}
    )
    return {"ok": True}


@router.post("/recordings/{public_id}/rediarize")
def rediarize_recording(public_id: str) -> dict:
    """完了済み録音の話者識別だけを再実行する（文字起こしはやり直さない）。

    HF_TOKEN 未設定時など、初回処理時は話者識別が付かなかった録音に対して
    後からトークンを設定した場合の再実行に使う。
    """
    row = _get_row(public_id)
    if row["process_status"] != "done":
        raise HTTPException(409, "完了済みのアイテムのみ話者識別を再実行できます")
    with get_conn() as conn:
        has_segments = conn.execute(
            "SELECT 1 FROM transcript_segments WHERE recording_id = ? LIMIT 1",
            (row["id"],),
        ).fetchone()
    if has_segments is None:
        raise HTTPException(409, "文字起こしが無いため話者識別を再実行できません")

    with get_conn() as conn:
        conn.execute(
            "UPDATE recordings SET process_status = 'processing', updated_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
    events.publish(
        {"type": "recording_updated", "recording_id": public_id, "process_status": "processing"}
    )
    threading.Thread(
        target=worker.rediarize_job,
        args=(row["id"], public_id, row["stored_filename"]),
        daemon=True,
    ).start()
    return {"ok": True}


@router.post("/recordings/{public_id}/retry")
def retry_recording(public_id: str) -> dict:
    """エラーになった処理の再試行（pending に戻して最初からやり直す）。"""
    row = _get_row(public_id)
    if row["process_status"] != "error":
        raise HTTPException(409, "エラー状態のアイテムのみ再試行できます")
    with get_conn() as conn:
        conn.execute(
            "UPDATE recordings SET process_status = 'pending', retry_count = 0, "
            "error_message = NULL, updated_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
    worker.clear_defer(row["id"])
    events.publish(
        {"type": "recording_updated", "recording_id": public_id, "process_status": "pending"}
    )
    return {"ok": True}
