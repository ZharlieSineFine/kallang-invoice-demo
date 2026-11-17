"""Orchestrate an export batch: check, render CSV, write the manifest, record to Postgres."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from invoiceflow.contracts import CodingMaster, money_sum
from invoiceflow.export.checks import BatchError, check_batch
from invoiceflow.export.csvio import to_csv
from invoiceflow.export.manifest import Manifest, sha256_bytes
from invoiceflow.export.mapping import RowContext, SapMapping, map_row
from invoiceflow.export.models import ExportDocument, ExportRowPlan
from invoiceflow.settings import load_config


@dataclass(frozen=True)
class PreparedBatch:
    """A fully checked, rendered batch, ready to be written to disk and recorded."""

    batch_id: str
    rows: tuple[tuple[str, ...], ...]
    csv_text: str
    csv_sha256: str
    total: Decimal
    manifest: Manifest
    row_plans: tuple[ExportRowPlan, ...]
    layout: str


@dataclass(frozen=True)
class ExportResult:
    batch_id: str
    csv_path: Path
    manifest_path: Path
    manifest: Manifest
    row_plans: tuple[ExportRowPlan, ...]


def export_versions() -> tuple[str, str, str]:
    """The model, prompt, and rules a batch's manifest records."""
    models = load_config("models")
    rules = load_config("rules")
    return (
        str(models.get("model", "")),
        str(models.get("prompt", "")),
        str(rules.get("version", "1")),
    )


def numbered(documents: tuple[ExportDocument, ...]) -> tuple[tuple[int, ExportDocument], ...]:
    """Number the invoices that have rows 1, 2, 3 in file order (the CSV's InvoiceID)."""
    with_rows = (doc for doc in documents if doc.coding_lines)
    return tuple(enumerate(with_rows, start=1))


def build_rows(
    mapping: SapMapping, documents: tuple[ExportDocument, ...], export_date: date
) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for invoice_id, doc in numbered(documents):
        for line in doc.coding_lines:
            rows.append(
                map_row(
                    mapping,
                    RowContext(
                        doc_id=doc.doc_id,
                        vendor=doc.vendor,
                        invoice=doc.invoice,
                        coding_line=line,
                        export_date=export_date,
                        invoice_id=invoice_id,
                    ),
                )
            )
    return tuple(rows)


def plan_rows(documents: tuple[ExportDocument, ...]) -> tuple[ExportRowPlan, ...]:
    plans: list[ExportRowPlan] = []
    first_row = 1
    for doc in documents:
        count = len(doc.coding_lines)
        if count:
            plans.append(ExportRowPlan(doc_id=doc.doc_id, first_row_no=first_row, row_count=count))
            first_row += count
    return tuple(plans)


def manifest_invoices(documents: tuple[ExportDocument, ...]) -> tuple[dict[str, Any], ...]:
    """Which InvoiceID is which document, and where its rows sit, for tracing."""
    plans = {plan.doc_id: plan for plan in plan_rows(documents)}
    return tuple(
        {
            "invoice_id": invoice_id,
            "doc_id": str(doc.doc_id),
            "vendor_no": doc.vendor.sap_vendor_no,
            "reference": doc.invoice.invoice_number,
            "first_row": plans[doc.doc_id].first_row_no,
            "row_count": plans[doc.doc_id].row_count,
        }
        for invoice_id, doc in numbered(documents)
    )


def _batch_total(documents: tuple[ExportDocument, ...]) -> Decimal:
    return money_sum(doc.invoice.total for doc in documents if doc.invoice.total is not None)


def build_batch(
    mapping: SapMapping,
    documents: tuple[ExportDocument, ...],
    master: CodingMaster,
    *,
    export_date: date,
    batch_id: str,
    model: str,
    prompt_version: str,
    rule_version: str,
    previously_exported: frozenset[UUID] = frozenset(),
) -> PreparedBatch:
    """Render and check a batch. Raises :class:`BatchError` when any check fails."""
    rows = build_rows(mapping, documents, export_date)
    problems = check_batch(
        mapping, rows, documents, master, previously_exported=previously_exported
    )
    if problems:
        raise BatchError(problems)

    csv_text = to_csv(mapping, rows)
    csv_sha256 = sha256_bytes(csv_text.encode(mapping.encoding))
    total = _batch_total(documents)
    manifest = Manifest(
        batch_id=batch_id,
        row_count=len(rows),
        total=total,
        csv_sha256=csv_sha256,
        mapping_version=mapping.version,
        model=model,
        prompt_version=prompt_version,
        rule_version=rule_version,
        layout=mapping.layout,
        invoices=manifest_invoices(documents),
    )
    return PreparedBatch(
        batch_id=batch_id,
        rows=rows,
        csv_text=csv_text,
        csv_sha256=csv_sha256,
        total=total,
        manifest=manifest,
        row_plans=plan_rows(documents),
        layout=mapping.layout,
    )


def write_batch(prepared: PreparedBatch, out_dir: Path, *, encoding: str = "utf-8") -> ExportResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{prepared.batch_id}.csv"
    manifest_path = out_dir / f"{prepared.batch_id}.manifest.json"
    csv_path.write_text(prepared.csv_text, encoding=encoding, newline="")
    manifest_path.write_text(prepared.manifest.to_json() + "\n", encoding="utf-8")
    return ExportResult(
        batch_id=prepared.batch_id,
        csv_path=csv_path,
        manifest_path=manifest_path,
        manifest=prepared.manifest,
        row_plans=prepared.row_plans,
    )


def record_export(
    conn: Connection,
    batch_id: str,
    *,
    created_at: datetime,
    csv_path: str,
    csv_sha256: str,
    row_count: int,
    total: Decimal,
    layout: str,
    mapping_version: str,
    manifest: dict[str, Any],
    row_plans: tuple[ExportRowPlan, ...],
) -> None:
    """Record one batch in a single transaction. Raises if any doc was exported before.

    ``export_rows.doc_id`` is UNIQUE in the schema, so a second export of the same document
    is blocked even if two processes race past this pre-check.
    """
    doc_ids = [plan.doc_id for plan in row_plans]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT doc_id FROM export_rows WHERE doc_id = ANY(%s)", (doc_ids,))
        duplicates = [str(row[0]) for row in cur.fetchall()]
        if duplicates:
            raise BatchError((f"document(s) already exported: {', '.join(duplicates)}",))
        cur.execute(
            """
            INSERT INTO export_batches (batch_id, created_at, csv_path, csv_sha256,
                row_count, total, layout, mapping_version, manifest)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                batch_id,
                created_at,
                csv_path,
                csv_sha256,
                row_count,
                total,
                layout,
                mapping_version,
                Jsonb(manifest),
            ),
        )
        for plan in row_plans:
            cur.execute(
                """
                INSERT INTO export_rows (batch_id, doc_id, first_row_no, row_count)
                VALUES (%s, %s, %s, %s)
                """,
                (batch_id, plan.doc_id, plan.first_row_no, plan.row_count),
            )


def export_documents(
    mapping: SapMapping,
    documents: tuple[ExportDocument, ...],
    master: CodingMaster,
    *,
    export_date: date,
    batch_id: str,
    out_dir: Path,
    model: str,
    prompt_version: str,
    rule_version: str,
    previously_exported: frozenset[UUID] = frozenset(),
) -> ExportResult:
    """End-to-end: check, render, and write a batch to ``out_dir`` (no database writes)."""
    prepared = build_batch(
        mapping,
        documents,
        master,
        export_date=export_date,
        batch_id=batch_id,
        model=model,
        prompt_version=prompt_version,
        rule_version=rule_version,
        previously_exported=previously_exported,
    )
    return write_batch(prepared, out_dir, encoding=mapping.encoding)
