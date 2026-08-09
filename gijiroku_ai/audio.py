"""音源配信。

録音ファイルはアップロード時点でローカル（data/recordings/）に保存済みのため、
denroku のような NAS からのダウンロードキャッシュは不要で、ローカルファイルを
直接配信するだけでよい。

- ブラウザが再生できる形式: FileResponse でそのまま配信（Range 対応・シーク可）
- 非対応形式（amr 等）: ffmpeg で MP3 にオンザフライ変換して配信（シーク不可）
"""

import subprocess
from collections.abc import Iterator
from pathlib import Path

from fastapi import Response
from fastapi.responses import FileResponse, StreamingResponse

CHUNK = 1024 * 256

# ブラウザで直接再生できる形式と Content-Type
DIRECT_TYPES = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}


def _stream_transcoded(local_path: Path) -> Iterator[bytes]:
    """ファイルを ffmpeg で MP3 に変換しつつ配信する。"""
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(local_path),
         "-f", "mp3", "-b:a", "128k", "pipe:1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    try:
        while data := proc.stdout.read(CHUNK):
            yield data
    finally:
        proc.stdout.close()
        proc.terminate()
        proc.wait()


def audio_response(local_path: Path) -> Response:
    """音源のレスポンスを作る。

    Range（シーク）は FileResponse がリクエストヘッダを見て自前で処理するため、
    ここで Range を解釈する必要はない。
    """
    ext = local_path.suffix.lstrip(".").lower()
    media_type = DIRECT_TYPES.get(ext)
    if media_type is None:
        # ブラウザ非対応形式は MP3 に変換して配信（シーク不可）
        return StreamingResponse(
            _stream_transcoded(local_path), media_type="audio/mpeg"
        )
    return FileResponse(local_path, media_type=media_type)
