"""Delete chosen documents from the Queue (user's request, 2026-11-20).

Each one goes from the database (its child rows cascade), along with its stored file, parsed
pages, silver files, and recorded model answer, so the same file uploaded again is read as
new. The append-only event log keeps a ``document.deleted`` event per document, with its
invoice number, file name, fingerprint, status, and SAP batch.

Unlike `make erase-live` (``store.erase``), an exported invoice's SAP batch stays as it is:
its CSV file, its other invoices (still EXPORTED), and its notification. SAP already has
those invoices, so putting them back to ready would export them twice. Only the deleted
invoice's own export row goes, because it points at the document. The Queue warns before an
exported invoice is deleted that SAP and this system no longer match afterward.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from invoiceflow.contracts import DocStatus
from invoiceflow.store.erase import ErasePlan, remove_files

EVENT_TYPE = "document.deleted"

_PLAN_SQL = """
SELECT d.doc_id, d.file_id, b.sha256, b.path, b.original_name, d.status,
       (SELECT value_norm FROM fields f WHERE f.doc_id = d.doc_id
          AND f.name = 'invoice_number' AND f.is_current LIMIT 1),
       (SELECT string_agg(r.batch_id, ', ' ORDER BY x.created_at, r.batch_id)
          FROM export_rows r JOIN export_batches x USING (batch_id)
          WHERE r.doc_id = d.doc_id),
       EXISTS (SELECT 1 FROM documents o
               WHERE o.file_id = d.file_id AND NOT (o.doc_id = ANY(%(ids)s)))
FROM documents d JOIN bronze_files b USING (file_id)
WHERE d.doc_id = ANY(%(ids)s)
ORDER BY d.created_at, d.doc_id
"""


@dataclass(frozen=True)
class DeletedDocument:
    doc_id: UUID
    file_id: UUID
    sha256: str
    path: str  # the stored file, relative to the data folder
    file_name: str | None
    status: DocStatus
    invoice_number: str | None
    export_batch: str | None  # every SAP batch it went out in, e.g. "B-1, B-4"; all are kept
    file_is_shared: bool = False  # another document still uses the stored file

    @property
    def was_exported(self) -> bool:
        return self.status is DocStatus.EXPORTED or self.export_batch is not None

    @property
    def label(self) -> str:
        return self.invoice_number or self.file_name or "a document with no invoice number"


def plan_delete(conn: Connection, doc_ids: Sequence[UUID]) -> tuple[DeletedDocument, ...]:
    """The documents that exist among ``doc_ids``, oldest first. Reads only."""
    if not doc_ids:
        return ()
    with conn.cursor() as cur:
        cur.execute(_PLAN_SQL, {"ids": list(doc_ids)})
        rows = cur.fetchall()
    return tuple(
        DeletedDocument(
            doc_id=row[0],
            file_id=row[1],
            sha256=str(row[2]).strip(),
            path=str(row[3]),
            file_name=row[4],
            status=DocStatus(row[5]),
            invoice_number=row[6],
            export_batch=row[7],
            file_is_shared=bool(row[8]),
        )
        for row in rows
    )


def apply_delete(conn: Connection, plan: Sequence[DeletedDocument], *, actor: str) -> None:
    """Remove the planned documents. Run it inside the caller's transaction."""
    if not plan:
        return
    doc_ids = [item.doc_id for item in plan]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM export_rows WHERE doc_id = ANY(%s)", (doc_ids,))
        cur.execute("DELETE FROM documents WHERE doc_id = ANY(%s)", (doc_ids,))
        cur.execute(
            "DELETE FROM bronze_files b WHERE b.file_id = ANY(%s) "
            "AND NOT EXISTS (SELECT 1 FROM documents d WHERE d.file_id = b.file_id)",
            ([item.file_id for item in plan],),
        )
        for item in plan:
            cur.execute(
                "INSERT INTO events (actor, doc_id, type, payload) VALUES (%s, %s, %s, %s)",
                (actor, item.doc_id, EVENT_TYPE, Jsonb(_payload(item))),
            )


def remove_deleted_files(
    plan: Sequence[DeletedDocument], *, data_root: Path, cache_dir: Path | None
) -> tuple[Path, ...]:
    """Delete their files; an SAP batch's CSV stays. Run it after the delete is committed."""
    own_files = [item for item in plan if not item.file_is_shared]
    files = ErasePlan(
        doc_ids=tuple(item.doc_id for item in plan),
        bronze_paths=tuple(dict.fromkeys(item.path for item in own_files)),
        match_sha256s=frozenset(item.sha256 for item in own_files),
    )
    return remove_files(files, data_root=data_root, cache_dir=cache_dir)


def _payload(item: DeletedDocument) -> dict[str, str | None]:
    return {
        "invoice_number": item.invoice_number,
        "file_name": item.file_name,
        "sha256": item.sha256,
        "status": item.status.value,
        "export_batch": item.export_batch,
    }
