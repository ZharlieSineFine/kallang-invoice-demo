"""`make erase-live`: remove the live-demo invoices from the database and the data folder,
keeping every other invoice, so the live demo can be run again.

A live-demo invoice is found by its file (SHA-256, the way intake knows a file) or by its
invoice number (letters and digits, as R05 compares them), so a re-saved or re-scanned copy
is found too. Everything it left behind goes: its rows (child tables cascade), its stored
file, parsed pages, and silver files, copies still waiting in the inbox, and the
model answers recorded for it. An export batch that included one is removed as a whole, and
the other invoices in it go back to the status they were exported from (APPROVED when a
reviewer approved them, otherwise AUTO_PASSED), so they can be exported again.

The audit log is append-only (a database trigger refuses changes), so the erased invoices'
history stays in it, and the erase itself is logged as ``live_demo.erased``. No screen shows
it: the screens read events per document, and an upload gets a new document ID every time.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from invoiceflow.contracts import DocStatus
from invoiceflow.normalize.text import invoice_number_key

REVERT_REASON = "its export batch was removed together with the live-demo invoices"
_INBOX_FOLDERS = ("inbox", "processed")


@dataclass(frozen=True)
class EraseTarget:
    sha256s: frozenset[str] = frozenset()
    invoice_numbers: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ErasePlan:
    doc_ids: tuple[UUID, ...] = ()
    file_ids: tuple[UUID, ...] = ()
    sha256s: tuple[str, ...] = ()
    bronze_paths: tuple[str, ...] = ()
    invoice_numbers: tuple[str, ...] = ()
    batch_ids: tuple[str, ...] = ()
    reverted: tuple[tuple[UUID, DocStatus], ...] = ()
    match_sha256s: frozenset[str] = field(default_factory=frozenset)

    def with_batches(self, batch_ids: Iterable[str]) -> ErasePlan:
        return replace(self, batch_ids=tuple(sorted({*self.batch_ids, *batch_ids})))


def target_from_folder(folder: Path) -> EraseTarget:
    """The live-demo set in ``folder``: its manifest's files and invoice numbers, or, with no
    manifest, every PDF in it by content."""
    manifest = folder / "manifest.json"
    if manifest.is_file():
        documents = json.loads(manifest.read_text(encoding="utf-8"))["documents"]
        return EraseTarget(
            sha256s=frozenset(str(doc["sha256"]) for doc in documents),
            invoice_numbers=frozenset(str(doc["invoice_number"]) for doc in documents),
        )
    return EraseTarget(sha256s=frozenset(_sha256(path) for path in sorted(folder.glob("*.pdf"))))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _rows(conn: Connection, sql: str, *args) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def _matching_numbers(conn: Connection, numbers: frozenset[str]) -> set[UUID]:
    keys = {invoice_number_key(number) for number in numbers} - {""}
    if not keys:
        return set()
    rows = _rows(
        conn, "SELECT doc_id, value_norm FROM fields WHERE name = 'invoice_number' AND is_current"
    )
    return {doc_id for doc_id, value in rows if invoice_number_key(value) in keys}


def plan_erase(conn: Connection, target: EraseTarget) -> ErasePlan:
    """What an erase would remove. Reads only."""
    by_file = _rows(
        conn,
        "SELECT d.doc_id FROM documents d JOIN bronze_files b USING (file_id) "
        "WHERE b.sha256 = ANY(%s)",
        sorted(target.sha256s),
    )
    wanted = {row[0] for row in by_file} | _matching_numbers(conn, target.invoice_numbers)
    docs = _rows(
        conn,
        """
        SELECT d.doc_id, d.file_id, b.sha256, b.path,
               (SELECT value_norm FROM fields f WHERE f.doc_id = d.doc_id
                  AND f.name = 'invoice_number' AND f.is_current LIMIT 1)
        FROM documents d JOIN bronze_files b USING (file_id)
        WHERE d.doc_id = ANY(%s) ORDER BY d.created_at, d.doc_id
        """,
        sorted(wanted),
    )
    doc_ids = tuple(row[0] for row in docs)
    batch_ids = tuple(
        row[0]
        for row in _rows(
            conn,
            "SELECT DISTINCT batch_id FROM export_rows WHERE doc_id = ANY(%s) ORDER BY 1",
            list(doc_ids),
        )
    )
    # The other invoices in those batches go back to ready, unless another batch still holds
    # them: an invoice can be sent again (2026-11-20), and then it is still in SAP.
    others = _rows(
        conn,
        """
        SELECT r.doc_id,
               EXISTS (SELECT 1 FROM reviews v WHERE v.doc_id = r.doc_id AND v.action = 'APPROVE')
        FROM export_rows r
        WHERE r.batch_id = ANY(%s) AND NOT (r.doc_id = ANY(%s))
          AND NOT EXISTS (SELECT 1 FROM export_rows o
                          WHERE o.doc_id = r.doc_id AND NOT (o.batch_id = ANY(%s)))
        GROUP BY r.doc_id
        ORDER BY min(r.batch_id), min(r.first_row_no)
        """,
        list(batch_ids),
        list(doc_ids),
        list(batch_ids),
    )
    sha256s = tuple(str(row[2]).strip() for row in docs)
    return ErasePlan(
        doc_ids=doc_ids,
        file_ids=tuple(dict.fromkeys(row[1] for row in docs)),
        sha256s=sha256s,
        bronze_paths=tuple(dict.fromkeys(str(row[3]) for row in docs)),
        invoice_numbers=tuple(row[4] for row in docs if row[4]),
        batch_ids=batch_ids,
        reverted=tuple(
            (doc_id, DocStatus.APPROVED if approved else DocStatus.AUTO_PASSED)
            for doc_id, approved in others
        ),
        match_sha256s=frozenset(target.sha256s) | frozenset(sha256s),
    )


def apply_erase(conn: Connection, plan: ErasePlan, *, actor: str) -> None:
    """Remove the planned rows. Run it inside the caller's transaction."""
    if not plan.doc_ids:
        return
    docs, batches = list(plan.doc_ids), list(plan.batch_ids)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM notifications WHERE batch_id = ANY(%s)", (batches,))
        cur.execute("DELETE FROM export_rows WHERE batch_id = ANY(%s)", (batches,))
        cur.execute("DELETE FROM export_batches WHERE batch_id = ANY(%s)", (batches,))
        for doc_id, status in plan.reverted:
            cur.execute(
                "UPDATE documents SET status = %s, status_reason = %s, updated_at = now() "
                "WHERE doc_id = %s",
                (status.value, REVERT_REASON, doc_id),
            )
            cur.execute(
                "INSERT INTO events (actor, doc_id, type, payload) VALUES (%s, %s, %s, %s)",
                (actor, doc_id, "export.reverted", Jsonb({"batches": batches, "status": status})),
            )
        cur.execute("DELETE FROM documents WHERE doc_id = ANY(%s)", (docs,))
        cur.execute(
            "DELETE FROM bronze_files b WHERE b.file_id = ANY(%s) "
            "AND NOT EXISTS (SELECT 1 FROM documents d WHERE d.file_id = b.file_id)",
            (list(plan.file_ids),),
        )
        cur.execute(
            "INSERT INTO events (actor, doc_id, type, payload) VALUES (%s, NULL, %s, %s)",
            (
                actor,
                "live_demo.erased",
                Jsonb(
                    {
                        "invoice_numbers": list(plan.invoice_numbers),
                        "documents": [str(doc_id) for doc_id in docs],
                        "batches_removed": batches,
                    }
                ),
            ),
        )


def _remove(path: Path, removed: list[Path]) -> None:
    if path.is_dir():
        shutil.rmtree(path)
        removed.append(path)
    elif path.is_file():
        path.unlink()
        removed.append(path)


def _cached_for(path: Path, doc_ids: set[str]) -> bool:
    try:
        result = json.loads(path.read_text(encoding="utf-8")).get("result") or {}
    except (OSError, ValueError, AttributeError):
        return False
    return str(result.get("doc_id")) in doc_ids


def remove_files(plan: ErasePlan, *, data_root: Path, cache_dir: Path | None) -> tuple[Path, ...]:
    """Delete what the erased invoices left in ``data_root`` and the model-answer cache.

    ``cache_dir=None`` keeps their recorded answers, for a replay rehearsal of the same set."""
    removed: list[Path] = []
    for relative in plan.bronze_paths:
        _remove(data_root / relative, removed)
    for doc_id in plan.doc_ids:
        for folder in ("silver", "parsed"):
            _remove(data_root / folder / str(doc_id), removed)
    for batch_id in plan.batch_ids:
        _remove(data_root / "gold" / batch_id, removed)
    for folder in _INBOX_FOLDERS:
        for path in sorted((data_root / folder).glob("*")) if (data_root / folder).is_dir() else ():
            if path.is_file() and _sha256(path) in plan.match_sha256s:
                _remove(path, removed)
    wanted = {str(doc_id) for doc_id in plan.doc_ids}
    if wanted and cache_dir is not None and cache_dir.is_dir():
        for path in sorted(cache_dir.glob("*.json")):
            if _cached_for(path, wanted):
                _remove(path, removed)
    return tuple(removed)
