"""Local-disk storage for task attachments (MVP, no object storage yet).

Files are written under ``settings.attachments_dir`` keyed by a path we fully
control (``<workspace>/<task>/<attachment_id><ext>``), never by the user-supplied
filename — that is kept only as display metadata. Downloads are streamed through
the API so every read is authorization-checked.
"""

from pathlib import Path
from uuid import UUID

from app.core.config import settings


def _root() -> Path:
    return Path(settings.attachments_dir)


def build_storage_key(workspace_id: UUID, task_id: UUID, attachment_id: UUID, filename: str) -> str:
    ext = Path(filename).suffix[:20]  # keep a sane extension, drop anything weird
    return f"{workspace_id}/{task_id}/{attachment_id}{ext}"


def absolute_path(storage_key: str) -> Path:
    return _root() / storage_key


def write_file(storage_key: str, data: bytes) -> None:
    path = absolute_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def delete_file(storage_key: str) -> None:
    try:
        absolute_path(storage_key).unlink(missing_ok=True)
    except OSError:
        # Best-effort: the DB row is the source of truth; a stray file is harmless.
        pass
