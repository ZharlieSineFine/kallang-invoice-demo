"""Persistence step functions shared by the DAGs and ``make e2e``.

These wrap the pure ``pipeline.stages`` functions with the WS6 ``BlobStore`` and
``Repository``, so a document flows inbox -> bronze -> silver -> (later) gold. They import
nothing from Airflow, so they can be called from scripts, tests, or an Azure Function.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
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
    PriorInvoice,
    ValueSource,
)
from invoiceflow.export.checks import check_batch
from invoiceflow.export.exporter import build_batch, build_rows, export_versions
from invoiceflow.export.mapping import SapMapping, load_sap_mapping
from invoiceflow.export.models import ExportDocument
from invoiceflow.normalize.text import REFERENCE_CLEANUP_REASON, reference_cleanup
from invoiceflow.pipeline.deps import build_deps
from invoiceflow.pipeline.stages import PipelineDeps, ProcessResult, process_document
from invoiceflow.rules.audit import AuditSample
from invoiceflow.settings import data_dir, load_config, singapore_today
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
    """Pipeline dependencies, master data, and the rules config."""

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
    process: ProcessResult | None = None


@dataclass(frozen=True)
class ExportSummary:
    batch: ExportBatch
    doc_ids: tuple[UUID, ...]
    problems: tuple[str, ...] = ()  # documents held back, and why; they stay exportable
    resent: tuple[UUID, ...] = ()  # of doc_ids, the ones sent to SAP before


def load_demo_master() -> MasterData:
    """The full vendor master once ``make data`` has run, else the golden one-vendor master."""
    generated = data_dir() / "generated" / "master.json"
    if generated.is_file():
        return MasterData.model_validate_json(generated.read_text(encoding="utf-8"))

    from invoiceflow.pipeline.golden import load_golden

    return load_golden().master


def build_pipeline(rules_config: dict[str, Any] | None = None) -> Pipeline:
    """The real pipeline, backed by the Phase 1 implementations (WS2-WS8)."""
    rules_config = rules_config or load_config("rules")
    return Pipeline(
        deps=build_deps(rules_config), master=load_demo_master(), rules_config=rules_config
    )


golden_pipeline = build_pipeline  # backward-compatible name used by the DAGs


def guess_mime(name: str) -> str | None:
    return _MIME_BY_EXT.get(Path(name).suffix.lower())


def inbox_dir() -> Path:
    return data_dir() / INBOX_DIR


def processed_dir() -> Path:
    return data_dir() / PROCESSED_DIR


def list_inbox(inbox: Path | None = None) -> tuple[Path, ...]:
    """Files waiting for intake, oldest first, like mail in the order it arrived.

    Name order would be wrong: "SAV-2026-1001 (2).pdf" sorts before "SAV-2026-1001.pdf",
    and R05 can only catch the re-send if the original went through first.
    """
    box = inbox or inbox_dir()
    if not box.is_dir():
        return ()
    # Hidden files (macOS .DS_Store when the folder is opened in Finder) are not invoices.
    files = (p for p in box.iterdir() if p.is_file() and not p.name.startswith("."))
    return tuple(sorted(files, key=lambda p: (p.stat().st_mtime, p.name)))


def ensure_master(repo, master: MasterData) -> bool:
    """Load master data into the ap database if it is empty. Returns True when it loaded."""
    if repo.master_loaded():
        return False
    repo.save_master(master)
    return True


@dataclass(frozen=True)
class Received:
    """A file saved as a RECEIVED document, ready for the model. ``duplicate``: seen before."""

    path: Path
    doc_id: UUID
    file_id: UUID
    sha256: str
    prior_invoices: tuple[PriorInvoice, ...] = ()
    duplicate: bool = False

    def skipped(self) -> IntakeResult:
        return IntakeResult(
            doc_id=self.doc_id,
            file_id=self.file_id,
            sha256=self.sha256,
            status=DocStatus.RECEIVED,
            skipped=True,
            reason="sha256 already ingested",
        )


def receive_document(
    path: Path,
    *,
    repo,
    store: LocalBlobStore,
    pipeline: Pipeline,
    file_id: UUID | None = None,
    doc_id: UUID | None = None,
    source: str = "folder",
    sender: str | None = None,
) -> Received:
    """Save the file and a RECEIVED document. A byte-identical file is a duplicate, unless its
    document never got past RECEIVED (the process died midway): that one is resumed."""
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
    prior_invoices = repo.prior_invoices(None)
    if repo.register_file(bronze):
        repo.create_document(
            DocumentRecord(doc_id=doc_id, file_id=file_id, status=DocStatus.RECEIVED)
        )
        repo.log_event(ACTOR, "intake.received", doc_id, {"sha256": sha256, "source": source})
        return Received(path, doc_id, file_id, sha256, prior_invoices)

    unfinished = repo.unfinished_document(sha256)
    if unfinished is not None:
        doc_id, file_id = unfinished
        repo.log_event(ACTOR, "intake.resumed", doc_id, {"sha256": sha256, "name": path.name})
        return Received(path, doc_id, file_id, sha256, prior_invoices)

    repo.log_event(ACTOR, "intake.duplicate_file", None, {"sha256": sha256, "name": path.name})
    return Received(path, doc_id, file_id, sha256, duplicate=True)


def _process(received: Received, pipeline: Pipeline, today: date, run_id: str) -> ProcessResult:
    """Every pipeline stage, model included. Touches no database."""
    return process_document(
        received.path,
        file_id=received.file_id,
        doc_id=received.doc_id,
        deps=pipeline.deps,
        master=pipeline.master,
        today=today,
        run_id=run_id,
        rules_config=pipeline.rules_config,
        prior_invoices=received.prior_invoices,
    )


def _save_outcome(
    repo, store: LocalBlobStore, received: Received, result: ProcessResult, run_id: str
) -> IntakeResult:
    _persist_silver(repo, store, result, run_id)
    _log_cleanups(repo, received.doc_id, result)
    invoice = result.context.invoice
    repo.set_document_meta(
        received.doc_id,
        invoice.document_type if invoice else None,
        result.context.vendor.vendor_id if result.context.vendor else None,
    )
    status = result.decision.status
    repo.set_status(received.doc_id, status, "; ".join(result.decision.reasons) or None)
    repo.log_event(
        ACTOR, "intake.completed", received.doc_id, {"status": status.value, "run_id": run_id}
    )
    _pick_for_audit(repo, received, status, result.context.rules_config)
    return IntakeResult(
        doc_id=received.doc_id,
        file_id=received.file_id,
        sha256=received.sha256,
        status=status,
        process=result,
    )


def _pick_for_audit(repo, received: Received, status: DocStatus, rules_config) -> None:
    """CR-012: a random share of auto-passed invoices is picked for a person to check. The
    invoice keeps its status and exports as usual; the event is the audit label."""
    sample = AuditSample.from_config(rules_config)
    if status is not DocStatus.AUTO_PASSED or sample is None or not sample.picks(received.sha256):
        return
    payload = {"sample_percent": str(sample.percent), "sha256": received.sha256}
    repo.log_event(ACTOR, "audit.selected", received.doc_id, payload)


def _log_cleanups(repo, doc_id: UUID, result: ProcessResult) -> None:
    """Audit trail: say when normalization changed how a printed reference reads."""
    printed = result.extraction.extraction
    cleanup = reference_cleanup(printed.invoice_number) if printed is not None else None
    if cleanup is None:
        return
    before, after = cleanup
    payload = {
        "field": "invoice_number",
        "printed": before,
        "cleaned": after,
        "reason": REFERENCE_CLEANUP_REASON,
    }
    repo.log_event(ACTOR, "normalize.cleaned", doc_id, payload)


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
    """Run one file through every stage and persist bronze + silver, all in the caller's one
    transaction (``make e2e`` rolls it back). Returns the outcome."""
    received = receive_document(
        path,
        repo=repo,
        store=store,
        pipeline=pipeline,
        file_id=file_id,
        doc_id=doc_id,
        source=source,
        sender=sender,
    )
    if received.duplicate:
        return received.skipped()
    result = _process(received, pipeline, today, run_id)
    return _save_outcome(repo, store, received, result, run_id)


def intake_in_steps(
    path: Path,
    *,
    transaction: Callable[[], AbstractContextManager[Any]],
    store: LocalBlobStore,
    pipeline: Pipeline,
    today: date,
    run_id: str,
    file_id: UUID | None = None,
    doc_id: UUID | None = None,
    source: str = "folder",
    sender: str | None = None,
) -> IntakeResult:
    """Like ``intake_document``, but committed in steps so the review app can show the document
    while the model reads it. ``transaction()`` yields a repository and commits on exit (see
    ``store.repo.repo_transaction``).

    1. Save the file and a RECEIVED document, and commit.
    2. Run the model, with no transaction open.
    3. Save the outcome, and commit.

    If step 2 or 3 fails, the RECEIVED document is removed and the error re-raised, so a retry
    starts clean. If the process is killed instead, the retry finds the RECEIVED document and
    resumes it (see ``receive_document``).
    """
    with transaction() as repo:
        received = receive_document(
            path,
            repo=repo,
            store=store,
            pipeline=pipeline,
            file_id=file_id,
            doc_id=doc_id,
            source=source,
            sender=sender,
        )
    if received.duplicate:
        return received.skipped()
    try:
        result = _process(received, pipeline, today, run_id)
        with transaction() as repo:
            return _save_outcome(repo, store, received, result, run_id)
    except Exception as error:
        with transaction() as repo:
            repo.discard_document(received.doc_id, received.file_id)
            repo.log_event(
                ACTOR,
                "intake.failed",
                received.doc_id,
                {
                    "sha256": received.sha256,
                    "name": path.name,
                    "error": f"{type(error).__name__}: {error}",
                },
            )
        raise


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


def _export_document(repo, doc_id: UUID, master: MasterData) -> ExportDocument:
    """One document's current values. Raises ``ValueError`` if it cannot be exported."""
    record = repo.get_document(doc_id)
    vendor = master.vendor(record.vendor_id) if record and record.vendor_id else None
    if vendor is None:
        raise ValueError(f"document {doc_id} has no vendor from the vendor master")
    invoice = repo.stored_invoice(doc_id)
    if invoice is None:
        raise ValueError(f"document {doc_id} has no stored values")
    return ExportDocument(doc_id, invoice, vendor, repo.coding_lines(doc_id))


def _exportable(
    doc_ids: Sequence[UUID], repo, master: MasterData, mapping: SapMapping, export_date: date
) -> tuple[tuple[ExportDocument, ...], tuple[str, ...]]:
    """Keep every document that passes the batch checks; one bad invoice never blocks the rest."""
    accepted: tuple[ExportDocument, ...] = ()
    problems: list[str] = []
    for doc_id in doc_ids:
        try:
            candidate = (*accepted, _export_document(repo, doc_id, master))
        except ValueError as error:
            problems.append(str(error))
            continue
        rows = build_rows(mapping, candidate, export_date)
        found = check_batch(mapping, rows, candidate, master.coding)
        if found:
            problems.extend(found)
        else:
            accepted = candidate
    return accepted, tuple(problems)


def export_approved(
    *,
    repo,
    store: LocalBlobStore,
    batch_id: str | None = None,
    export_date: date | None = None,
    resend: Sequence[UUID] = (),
) -> ExportSummary:
    """Write the SAP CSV and manifest for everything ready, and record the batch.

    Ready means passed or approved and never exported. ``resend`` adds invoices sent before
    that a person chose to send again (user's request, 2026-11-20); any other ID in it is
    ignored. With no ``resend``, as in the scheduled run, a second run sends nothing, so no
    invoice goes twice on its own. Every send keeps its own row in the history. Documents
    that fail a batch check stay where they are, and ``ExportSummary.problems`` says why.
    """
    mapping = load_sap_mapping(load_config("sap_mapping"))
    master = repo.load_master()
    export_date = export_date or singapore_today()
    sent_before = frozenset(repo.previously_exported()) if resend else frozenset()
    again = tuple(doc_id for doc_id in dict.fromkeys(resend) if doc_id in sent_before)
    candidates = tuple(dict.fromkeys((*repo.approved_not_exported(), *again)))
    documents, problems = _exportable(candidates, repo, master, mapping, export_date)
    batch_id = batch_id or _batch_id()
    model, prompt_version, rule_version = export_versions()
    prepared = build_batch(
        mapping,
        documents,
        master.coding,
        export_date=export_date,
        batch_id=batch_id,
        model=model,
        prompt_version=prompt_version,
        rule_version=rule_version,
    )
    csv_path = store.put_gold(
        batch_id, f"{batch_id}.csv", prepared.csv_text.encode(mapping.encoding)
    )
    store.put_gold(
        batch_id, f"{batch_id}.manifest.json", prepared.manifest.to_json().encode("utf-8")
    )
    batch = ExportBatch(
        batch_id=batch_id,
        created_at=datetime.now(UTC),
        csv_path=csv_path,
        csv_sha256=prepared.csv_sha256,
        row_count=len(prepared.rows),
        total=prepared.total,
        layout=mapping.layout,
        mapping_version=mapping.version,
    )
    doc_ids = tuple(document.doc_id for document in documents)
    repo.record_export(batch, doc_ids, manifest=prepared.manifest.to_dict())
    repo.log_event(
        ACTOR,
        "export.completed",
        None,
        {
            "batch_id": batch_id,
            "row_count": batch.row_count,
            "problems": list(problems),
            "resent": [str(doc_id) for doc_id in doc_ids if doc_id in sent_before],
        },
    )
    resent = tuple(doc_id for doc_id in doc_ids if doc_id in sent_before)
    return ExportSummary(batch=batch, doc_ids=doc_ids, problems=problems, resent=resent)


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


def _batch_id() -> str:
    return "export-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def drain_inbox[T](
    process: Callable[[Path], T], inbox: Path | None = None, processed: Path | None = None
) -> tuple[T, ...]:
    """Process every file waiting in the inbox, oldest first, moving each one out after it
    is done: what ``invoice_intake`` does, without Airflow (``make intake-local``)."""
    results = []
    for path in list_inbox(inbox if inbox is not None else inbox_dir()):
        results.append(process(path))
        move_processed(path, processed)
    return tuple(results)


def move_processed(path: Path, processed: Path | None = None) -> Path:
    """Move a processed file out of the inbox so the next run does not re-pick it."""
    destination = (processed or processed_dir()) / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    path.replace(destination)
    return destination
