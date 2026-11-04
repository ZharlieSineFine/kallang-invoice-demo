"""Persistence step functions shared by the DAGs and ``make e2e``.

These wrap the pure ``pipeline.stages`` functions with the WS6 ``BlobStore`` and
``Repository``, so a document flows inbox -> bronze -> silver -> (later) gold. They import
nothing from Airflow, so they can be called from scripts, tests, or an Azure Function.
"""

from __future__ import annotations

import hashlib
import json
from csv import writer
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from invoiceflow.contracts import (
    HEADER_FIELDS,
    BronzeFile,
    Confidence,
    DocStatus,
    DocumentRecord,
    ExportBatch,
    FieldValue,
    MasterData,
    MatchType,
    NormalizedInvoice,
    ValueSource,
)
from invoiceflow.pipeline.golden import load_golden
from invoiceflow.pipeline.stages import PipelineDeps, process_document
from invoiceflow.pipeline.stubs import golden_deps
from invoiceflow.settings import data_dir, load_config
from invoiceflow.storage import LocalBlobStore

INBOX_DIR = "inbox"
PROCESSED_DIR = "processed"
ACTOR = "pipeline"

# Header names that differ on NormalizedInvoice.
_NORMALIZED_NAME = {"gst_rate": "gst_rate_percent"}

_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".xml": "application/xml",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class Pipeline:
    """Stub pipeline dependencies, rebuilt from the golden fixtures and the config files."""

    deps: PipelineDeps
    master: MasterData
    rules_config: dict[str, Any]


@dataclass(frozen=True)
class IntakeResult:
    doc_id: UUID
    file_id: UUID
    sha256: str
    status: DocStatus
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class ExportSummary:
    batch: ExportBatch
    doc_ids: tuple[UUID, ...]


def golden_pipeline() -> Pipeline:
    golden = load_golden()
    rules_config = load_config("rules")
    deps = golden_deps(
        golden, auto_approve_clean=bool(rules_config["routing"]["auto_approve_clean"])
    )
    return Pipeline(deps=deps, master=golden.master, rules_config=rules_config)


def guess_mime(name: str) -> str | None:
    return _MIME_BY_EXT.get(Path(name).suffix.lower())


def inbox_dir() -> Path:
    return data_dir() / INBOX_DIR


def processed_dir() -> Path:
    return data_dir() / PROCESSED_DIR


def list_inbox(inbox: Path | None = None) -> tuple[Path, ...]:
    """Files waiting for intake, in name order. Directories are ignored."""
    box = inbox or inbox_dir()
    if not box.is_dir():
        return ()
    return tuple(sorted(p for p in box.iterdir() if p.is_file()))


def ensure_master(repo, master: MasterData) -> bool:
    """Load master data into the ap database if it is empty. Returns True when it loaded."""
    if repo.master_loaded():
        return False
    repo.save_master(master)
    return True


def intake_document(
    path: Path,
    *,
    repo,
    store: LocalBlobStore,
    pipeline: Pipeline,
    today: date,
    run_id: str,
    file_id: UUID | None = None,
    doc_id: UUID | None = None,
    source: str = "folder",
    sender: str | None = None,
) -> IntakeResult:
    """Run one file through every stage and persist bronze + silver. Returns the outcome."""
    ensure_master(repo, pipeline.master)
    data = path.read_bytes()
    sha256, bronze_path = store.put_bronze(data, path.name)
    file_id = file_id or uuid4()
    doc_id = doc_id or uuid4()

    bronze = BronzeFile(
        file_id=file_id,
        sha256=sha256,
        original_name=path.name,
        source=source,
        sender=sender,
        received_at=datetime.now(UTC),
        size_bytes=len(data),
        mime_type=guess_mime(path.name),
        path=bronze_path,
    )
    if not repo.register_file(bronze):
        return IntakeResult(
            doc_id=doc_id,
            file_id=file_id,
            sha256=sha256,
            status=DocStatus.RECEIVED,
            skipped=True,
            reason="sha256 already ingested",
        )

    repo.create_document(DocumentRecord(doc_id=doc_id, file_id=file_id, status=DocStatus.RECEIVED))
    repo.log_event(ACTOR, "intake.received", doc_id, {"sha256": sha256, "source": source})

    result = process_document(
        path,
        file_id=file_id,
        doc_id=doc_id,
        deps=pipeline.deps,
        master=pipeline.master,
        today=today,
        run_id=run_id,
        rules_config=pipeline.rules_config,
    )
    _persist_silver(repo, store, result, run_id)
    status = result.decision.status
    repo.set_status(doc_id, status, "; ".join(result.decision.reasons) or None)
    repo.log_event(ACTOR, "intake.completed", doc_id, {"status": status.value, "run_id": run_id})
    return IntakeResult(doc_id=doc_id, file_id=file_id, sha256=sha256, status=status)


def intake_inbox(
    *,
    repo,
    store: LocalBlobStore,
    pipeline: Pipeline,
    today: date,
    run_id: str,
    inbox: Path | None = None,
) -> tuple[IntakeResult, ...]:
    """Process every file in the inbox, moving each one to ``data/processed/`` after intake."""
    box = inbox or inbox_dir()
    processed = box.parent / PROCESSED_DIR
    results: list[IntakeResult] = []
    for path in list_inbox(box):
        results.append(
            intake_document(
                path, repo=repo, store=store, pipeline=pipeline, today=today, run_id=run_id
            )
        )
        move_processed(path, processed)
    return tuple(results)


def export_approved(
    *,
    repo,
    store: LocalBlobStore,
    mapping_version: str = "1",
    batch_id: str | None = None,
) -> ExportSummary:
    """Build a (stub) SAP CSV for every APPROVED-not-exported document and record the batch.

    The real 16-column layout is WS8's job; this stub writes one row per coding line so the
    export-once behaviour can be demonstrated today. Running it twice leaves a second batch
    with zero rows, because the first run flips every document to EXPORTED.
    """
    doc_ids = repo.approved_not_exported()
    rows = _export_rows(repo, doc_ids)
    csv_text = _render_csv(rows)
    batch_id = batch_id or _batch_id()
    csv_path = store.put_gold(batch_id, f"{batch_id}.csv", csv_text.encode("utf-8"))
    batch = ExportBatch(
        batch_id=batch_id,
        created_at=datetime.now(UTC),
        csv_path=csv_path,
        csv_sha256=hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
        row_count=len(rows),
        total=_sum_totals(rows),
        layout="hypothetical",
        mapping_version=mapping_version,
    )
    repo.record_export(batch, doc_ids)
    repo.log_event(ACTOR, "export.completed", None, {"batch_id": batch_id, "row_count": len(rows)})
    return ExportSummary(batch=batch, doc_ids=doc_ids)


def evaluate(*, repo) -> dict[str, int]:
    """Stub evaluation report: counts by status. WS8 replaces this with accuracy scoring."""
    counts: dict[str, int] = {}
    for status in DocStatus:
        counts[status.value] = len(repo.list_documents((status,)))
    return counts


# ---------------------------------------------------------------------- helpers
def _persist_silver(repo, store: LocalBlobStore, result, run_id: str) -> None:
    doc_id = result.document.doc_id
    invoice = result.context.invoice
    repo.save_parsed(result.document)
    repo.save_extraction(result.extraction)
    repo.save_fields(
        doc_id,
        _field_values(
            result.context.locations,
            result.extraction.extraction,
            invoice,
            result.decision.confidences,
        ),
        invoice.line_items if invoice else (),
    )
    repo.save_coding(doc_id, result.context.coding_lines)
    repo.save_findings(doc_id, run_id, result.findings)

    for page in result.document.pages:
        payload = json.dumps(page.model_dump(mode="json")).encode("utf-8")
        store.put_silver(doc_id, f"page-{page.page_no}.words.json", payload)
    store.put_silver(doc_id, "extraction.json", result.extraction.model_dump_json().encode("utf-8"))


def _field_values(locations, ext, invoice, confidences) -> tuple[FieldValue, ...]:
    location_by_name = {loc.field: loc for loc in locations if "[" not in loc.field}
    confidence_by_name = {c.field: c.confidence for c in confidences}
    values: list[FieldValue] = []
    for name in HEADER_FIELDS:
        raw = getattr(ext, name) if ext is not None else None
        if raw is None:
            continue
        location = location_by_name.get(name)
        values.append(
            FieldValue(
                name=name,
                value_raw=str(raw),
                value_norm=_normalized_value(invoice, name, raw),
                page_no=location.page_no if location else None,
                bbox=location.bbox if location else None,
                match_type=location.match_type if location else MatchType.NONE,
                match_score=location.score if location else 0.0,
                confidence=confidence_by_name.get(name, Confidence.LOW),
                source=ValueSource.MODEL,
            )
        )
    return tuple(values)


def _normalized_value(invoice: NormalizedInvoice | None, name: str, raw: Any) -> str:
    if invoice is None:
        return str(raw)
    value = getattr(invoice, _NORMALIZED_NAME.get(name, name), None)
    if value is None:
        return str(raw)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _export_rows(repo, doc_ids: tuple[UUID, ...]) -> tuple[tuple[Any, ...], ...]:
    rows: list[tuple[Any, ...]] = []
    for doc_id in doc_ids:
        for line in repo.coding_lines(doc_id):
            rows.append(
                (
                    doc_id,
                    line.line_no,
                    line.gl_account,
                    line.cost_center,
                    line.tax_code,
                    format(line.net_amount, "f"),
                    format(line.tax_amount, "f"),
                    line.description,
                )
            )
    return tuple(rows)


def _render_csv(rows: tuple[tuple[Any, ...], ...]) -> str:
    buffer = StringIO()
    out = writer(buffer)
    out.writerow(
        (
            "doc_id",
            "line_no",
            "gl_account",
            "cost_center",
            "tax_code",
            "net_amount",
            "tax_amount",
            "description",
        )
    )
    for row in rows:
        out.writerow(row)
    return buffer.getvalue()


def _sum_totals(rows: tuple[tuple[Any, ...], ...]) -> Decimal:
    total = Decimal("0.00")
    for row in rows:
        total += Decimal(row[5]) + Decimal(row[6])
    return total


def _batch_id() -> str:
    return "export-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def move_processed(path: Path, processed: Path | None = None) -> Path:
    """Move a processed file out of the inbox so the next run does not re-pick it."""
    destination = (processed or processed_dir()) / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    path.replace(destination)
    return destination
