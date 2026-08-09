"""アップロードされた録音ファイルのローカル保存。

NAS 同期は行わず、ユーザーがアップロードしたファイルをそのまま
`data/recordings/{public_id}{拡張子}` に永続保存する。
"""

import shutil
from pathlib import Path
from typing import IO

from gijiroku_ai.config import get_config

# アップロードを受け付ける拡張子
ALLOWED_EXTENSIONS = {"m4a", "mp3", "wav", "aac", "amr", "ogg", "flac"}


def save_upload(public_id: str, original_filename: str, file_obj: IO[bytes]) -> tuple[str, int]:
    """アップロードされたファイルを保存し、(保存ファイル名, サイズ) を返す。"""
    suffix = Path(original_filename).suffix.lower()
    stored_filename = f"{public_id}{suffix}"
    dest = get_config().recordings_dir / stored_filename
    with dest.open("wb") as out:
        shutil.copyfileobj(file_obj, out)
    return stored_filename, dest.stat().st_size


def path_for(stored_filename: str) -> Path:
    return get_config().recordings_dir / stored_filename


def delete(stored_filename: str) -> None:
    path_for(stored_filename).unlink(missing_ok=True)
