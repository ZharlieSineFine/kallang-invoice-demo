"""Upload helpers: write bytes to ``data/inbox/`` under a content-addressed name.

No database work and no Airflow here; the Upload page composes this with ``app.airflow``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from invoiceflow.settings import data_dir

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class SavedUpload:
    path: Path
    sha256: str
    size_bytes: int
    existed: bool


@dataclass(frozen=True)
class InboxItem:
    name: str
    size_bytes: int
    modified_at: datetime


def inbox_dir() -> Path:
    return data_dir() / "inbox"


def safe_filename(name: str) -> str:
    """Keep the basename and a small character set; never allow a path traversal."""
    base = Path(name.replace("\\", "/")).name.strip()
    cleaned = _SAFE.sub("_", base).strip("._")
    return cleaned or "upload.bin"


def upload_target(directory: Path, name: str, digest: str) -> Path:
    """Same bytes land on the same path; the first 12 hex chars identify the file."""
    return directory / f"{digest[:12]}-{safe_filename(name)}"


def save_upload(name: str, data: bytes, *, directory: Path | None = None) -> SavedUpload:
    if not data:
        raise ValueError("refusing to save an empty upload")
    target_dir = Path(directory) if directory is not None else inbox_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    target = upload_target(target_dir, name, digest)
    existed = target.is_file() and target.read_bytes() == data
    if not existed:
        target.write_bytes(data)
    return SavedUpload(path=target, sha256=digest, size_bytes=len(data), existed=existed)


def list_inbox(directory: Path | None = None, *, limit: int = 10) -> tuple[InboxItem, ...]:
    target_dir = Path(directory) if directory is not None else inbox_dir()
    if not target_dir.is_dir():
        return ()
    files = sorted(
        (p for p in target_dir.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return tuple(
        InboxItem(
            name=path.name,
            size_bytes=path.stat().st_size,
            modified_at=datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
        )
        for path in files[:limit]
    )


__all__ = [
    "InboxItem",
    "SavedUpload",
    "inbox_dir",
    "list_inbox",
    "safe_filename",
    "save_upload",
    "upload_target",
]
