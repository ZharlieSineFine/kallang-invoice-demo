"""LocalBlobStore: a filesystem implementation of the ``BlobStore`` protocol.

Layout under the store root (``INVOICEFLOW_DATA`` or ``<repo>/data``)::

    bronze/<aa>/<sha256>            write-once, content-addressed bytes
    silver/<doc_id>/<name>          per-document artifacts (words, extraction, page images)
    gold/<batch_id>/<name>          per-export-batch artifacts (the SAP CSV)

Paths returned by the store are relative to the root, so they stay valid on disk, in the
database, and inside a container that mounts the same ``data/`` volume.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

BRONZE_DIR = "bronze"
SILVER_DIR = "silver"
GOLD_DIR = "gold"


def words_rel_path(doc_id: UUID, page_no: int) -> str:
    """The silver path a page's ``words.json`` lives at (see ``Repository.save_parsed``)."""
    return f"{SILVER_DIR}/{doc_id}/page-{page_no}.words.json"


def silver_rel_path(doc_id: UUID, name: str) -> str:
    return f"{SILVER_DIR}/{doc_id}/{name}"


def gold_rel_path(batch_id: str, name: str) -> str:
    return f"{GOLD_DIR}/{batch_id}/{name}"


class LocalBlobStore:
    """Files on disk. Bronze files are content-addressed and never overwritten."""

    def __init__(self, root: Path):
        self.root = root

    def put_bronze(self, data: bytes, original_name: str) -> tuple[str, str]:
        """Store bytes once, keyed by SHA-256. Returns ``(sha256, relative_path)``.

        ``original_name`` is carried by the caller into ``BronzeFile.original_name``; the
        blob itself is addressed only by content, so storing the same bytes twice is a no-op.
        """
        del original_name  # content address, not the display name, decides where bytes live
        sha256 = hashlib.sha256(data).hexdigest()
        rel = f"{BRONZE_DIR}/{sha256[:2]}/{sha256}"
        path = self.root / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write_atomic(path, data)
        return sha256, rel

    def read(self, path: str) -> bytes:
        return (self.root / path).read_bytes()

    def put_silver(self, doc_id: UUID, name: str, data: bytes) -> str:
        rel = silver_rel_path(doc_id, name)
        self._write(self.root / rel, data)
        return rel

    def put_gold(self, batch_id: str, name: str, data: bytes) -> str:
        rel = gold_rel_path(batch_id, name)
        self._write(self.root / rel, data)
        return rel

    def _write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(path, data)

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        """Write to a temp file and rename, so a reader never sees a half-written blob."""
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
