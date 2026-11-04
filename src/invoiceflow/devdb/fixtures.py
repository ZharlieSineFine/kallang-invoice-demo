"""Load the golden fixtures into the dev Postgres, through the Phase 0 stubs.

Run ``make db-dev && make fixtures``. The loader truncates the invoice tables first, so it
is safe to run twice. Master data and documents come from ``tests/fixtures/golden/`` and
the stub pipeline (``invoiceflow.pipeline.stubs``); nothing here is production storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection, Cursor
from psycopg.types.json import Jsonb

from invoiceflow.contracts import (
    HEADER_FIELDS,
    CodingLine,
    InvoiceExtraction,
    MasterData,
    NormalizedInvoice,
    NormalizedLineItem,
)
from invoiceflow.pipeline.golden import GoldenFixture, GoldenSet, load_golden
from invoiceflow.pipeline.skeleton import GOLDEN_TODAY
from invoiceflow.pipeline.stages import ProcessResult, process_document
from invoiceflow.pipeline.stubs import golden_deps
from invoiceflow.settings import load_config, repo_root

RUN_ID = "fixtures"
ACTOR = "scripts/load_fixtures"

# Children first. RESTART IDENTITY keeps review-app URLs and ids stable between loads.
DATA_TABLES = (
    "events",
    "notifications",
    "export_rows",
    "export_batches",
    "reviews",
    "findings",
    "coding_lines",
    "line_items",
    "fields",
    "extractions",
    "pages",
    "documents",
    "bronze_files",
)
MASTER_TABLES = (
    "venue_cost_centers",
    "purchase_orders",
    "vendors",
    "tax_codes",
    "cost_centers",
    "gl_accounts",
)

# Header names that differ on NormalizedInvoice.
_NORMALIZED_NAME = {"gst_rate": "gst_rate_percent"}


@dataclass(frozen=True)
class LoadedDocument:
    fixture_id: str
    doc_id: UUID
    invoice_number: str | None
    status: str
    findings: tuple[str, ...]


@dataclass(frozen=True)
class LoadReport:
    documents: tuple[LoadedDocument, ...]
    fields: int
    line_items: int
    coding_lines: int
    findings: int

    def render(self) -> str:
        lines = [
            f"{len(self.documents)} document(s): {self.fields} fields, "
            f"{self.line_items} line items, {self.coding_lines} coding lines, "
            f"{self.findings} finding(s)"
        ]
        width = max((len(d.fixture_id) for d in self.documents), default=0)
        for doc in self.documents:
            found = ", ".join(doc.findings) or "none"
            lines.append(
                f"  {doc.fixture_id:<{width}}  {doc.status:<13}  "
                f"{doc.invoice_number or '-':<14}  findings: {found}"
            )
        return "\n".join(lines)


def load_fixtures(
    conn: Connection,
    *,
    golden: GoldenSet | None = None,
    rules_config: dict[str, Any] | None = None,
) -> LoadReport:
    """Replace the invoice tables with the two golden documents. Does not commit."""
    golden = golden or load_golden()
    rules_config = rules_config or load_config("rules")
    auto_approve = bool(rules_config.get("routing", {}).get("auto_approve_clean", True))
    deps = golden_deps(golden, auto_approve_clean=auto_approve)

    truncate(conn)
    load_master(conn, golden.master)

    loaded: list[LoadedDocument] = []
    counts = {"fields": 0, "line_items": 0, "coding_lines": 0, "findings": 0}
    for fixture in golden.fixtures:
        result = process_document(
            fixture.pdf_path,
            file_id=fixture.file_id,
            doc_id=fixture.doc_id,
            deps=deps,
            master=golden.master,
            today=GOLDEN_TODAY,
            run_id=RUN_ID,
            rules_config=rules_config,
        )
        counts_for_doc = _save_fixture(conn, fixture, result)
        for key, value in counts_for_doc.items():
            counts[key] += value
        loaded.append(
            LoadedDocument(
                fixture_id=fixture.fixture_id,
                doc_id=fixture.doc_id,
                invoice_number=fixture.truth.invoice.invoice_number,
                status=result.decision.status.value,
                findings=tuple(f.rule_id for f in result.findings),
            )
        )
    return LoadReport(documents=tuple(loaded), **counts)


def truncate(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE")
        cur.execute(f"TRUNCATE TABLE {', '.join(MASTER_TABLES)} RESTART IDENTITY CASCADE")


def load_master(conn: Connection, master: MasterData) -> None:
    coding = master.coding
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO gl_accounts (code, name, active) VALUES (%s, %s, %s)",
            [(g.code, g.name, g.active) for g in coding.gl_accounts],
        )
        cur.executemany(
            "INSERT INTO cost_centers (code, name, active) VALUES (%s, %s, %s)",
            [(c.code, c.name, c.active) for c in coding.cost_centers],
        )
        cur.executemany(
            "INSERT INTO tax_codes (code, rate_percent, description) VALUES (%s, %s, %s)",
            [(t.code, t.rate_percent, t.description) for t in coding.tax_codes],
        )
        cur.executemany(
            """
            INSERT INTO vendors (vendor_id, sap_vendor_no, name, uen, gst_reg_no, address,
                bank_name, bank_account, currency, locale, is_overseas, default_gl,
                default_cost_center, default_tax_code, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    v.vendor_id,
                    v.sap_vendor_no,
                    v.name,
                    v.uen,
                    v.gst_reg_no,
                    v.address,
                    v.bank_name,
                    v.bank_account,
                    v.currency,
                    v.locale,
                    v.is_overseas,
                    v.default_gl,
                    v.default_cost_center,
                    v.default_tax_code,
                    v.active,
                )
                for v in master.vendors
            ],
        )
        cur.executemany(
            """
            INSERT INTO purchase_orders (po_number, vendor_id, currency, amount, open_amount,
                gl_account, cost_center)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    p.po_number,
                    p.vendor_id,
                    p.currency,
                    p.amount,
                    p.open_amount,
                    p.gl_account,
                    p.cost_center,
                )
                for p in master.purchase_orders
            ],
        )
        cur.executemany(
            "INSERT INTO venue_cost_centers (alias, cost_center) VALUES (%s, %s)",
            [(v.alias, v.cost_center) for v in coding.venue_aliases],
        )


def _save_fixture(
    conn: Connection, fixture: GoldenFixture, result: ProcessResult
) -> dict[str, int]:
    invoice = result.context.invoice
    extraction = result.extraction
    ext = extraction.extraction
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bronze_files (file_id, sha256, original_name, source, sender,
                received_at, size_bytes, mime_type, path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                fixture.file_id,
                fixture.sha256,
                fixture.pdf_path.name,
                "golden",
                None,
                extraction.created_at,
                fixture.pdf_path.stat().st_size,
                "application/pdf",
                _relative(fixture.pdf_path),
            ),
        )
        cur.execute(
            """
            INSERT INTO documents (doc_id, file_id, doc_type, status, status_reason, vendor_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                fixture.doc_id,
                fixture.file_id,
                invoice.document_type.value if invoice and invoice.document_type else None,
                result.decision.status.value,
                "; ".join(result.decision.reasons) or None,
                result.context.vendor.vendor_id if result.context.vendor else None,
            ),
        )
        for page in result.document.pages:
            cur.execute(
                """
                INSERT INTO pages (doc_id, page_no, text_source, width_pt, height_pt,
                    image_path, words_path, ocr_mean_conf)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    fixture.doc_id,
                    page.page_no,
                    page.source.value,
                    page.width_pt,
                    page.height_pt,
                    page.image_path,
                    _relative(fixture.directory / f"page-{page.page_no}.words.json"),
                    page.ocr_mean_conf,
                ),
            )
        cur.execute(
            """
            INSERT INTO extractions (extraction_id, doc_id, model, model_digest, prompt_version,
                schema_version, params, mode, raw_output, parsed, valid, error, prompt_tokens,
                completion_tokens, latency_ms, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                extraction.extraction_id,
                fixture.doc_id,
                extraction.model,
                extraction.model_digest,
                extraction.prompt_version,
                extraction.schema_version,
                Jsonb(extraction.params),
                extraction.mode.value,
                extraction.raw_output,
                Jsonb(ext.model_dump(mode="json")) if ext else None,
                extraction.valid,
                extraction.error,
                extraction.prompt_tokens,
                extraction.completion_tokens,
                extraction.latency_ms,
                extraction.created_at,
            ),
        )
        field_count = _save_fields(cur, fixture, result, invoice, ext)
        line_count = _save_line_items(cur, fixture.doc_id, invoice.line_items if invoice else ())
        coding_count = _save_coding(cur, fixture.doc_id, result.context.coding_lines)
        for finding in result.findings:
            cur.execute(
                """
                INSERT INTO findings (doc_id, run_id, stage, rule_id, rule_version, severity,
                    scope, field, message, evidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    fixture.doc_id,
                    RUN_ID,
                    finding.stage.value,
                    finding.rule_id,
                    finding.rule_version,
                    finding.severity.value,
                    finding.scope.value,
                    finding.field,
                    finding.message,
                    Jsonb(dict(finding.evidence)),
                ),
            )
        cur.execute(
            "INSERT INTO events (actor, doc_id, type, payload) VALUES (%s, %s, %s, %s)",
            (
                ACTOR,
                fixture.doc_id,
                "fixture.loaded",
                Jsonb({"fixture_id": fixture.fixture_id, "run_id": RUN_ID}),
            ),
        )
    return {
        "fields": field_count,
        "line_items": line_count,
        "coding_lines": coding_count,
        "findings": len(result.findings),
    }


def _save_fields(
    cur: Cursor,
    fixture: GoldenFixture,
    result: ProcessResult,
    invoice: NormalizedInvoice | None,
    ext: InvoiceExtraction | None,
) -> int:
    locations = {loc.field: loc for loc in result.context.locations if "[" not in loc.field}
    confidences = {c.field: c.confidence.value for c in result.decision.confidences}
    count = 0
    for name in HEADER_FIELDS:
        raw = getattr(ext, name) if ext is not None else None
        if raw is None:
            continue
        location = locations.get(name)
        bbox = location.bbox if location else None
        cur.execute(
            """
            INSERT INTO fields (doc_id, extraction_id, name, value_raw, value_norm, page_no,
                x0, y0, x1, y1, match_type, match_score, confidence, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                fixture.doc_id,
                result.extraction.extraction_id,
                name,
                str(raw),
                _normalized_value(invoice, name, raw),
                location.page_no if location else None,
                bbox.x0 if bbox else None,
                bbox.y0 if bbox else None,
                bbox.x1 if bbox else None,
                bbox.y1 if bbox else None,
                location.match_type.value if location else "NONE",
                location.score if location else 0,
                confidences.get(name, "LOW"),
                "MODEL",
            ),
        )
        count += 1
    return count


def _save_line_items(cur: Cursor, doc_id: UUID, items: tuple[NormalizedLineItem, ...]) -> int:
    for item in items:
        cur.execute(
            """
            INSERT INTO line_items (doc_id, line_no, description, quantity, unit, days,
                unit_price, amount, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                doc_id,
                item.line_no,
                item.description,
                item.quantity,
                item.unit,
                item.days,
                item.unit_price,
                item.amount,
                "MODEL",
            ),
        )
    return len(items)


def _save_coding(cur: Cursor, doc_id: UUID, lines: tuple[CodingLine, ...]) -> int:
    for line in lines:
        cur.execute(
            """
            INSERT INTO coding_lines (doc_id, line_no, gl_account, cost_center, tax_code,
                net_amount, tax_amount, description, source_line_nos, coding_source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                doc_id,
                line.line_no,
                line.gl_account,
                line.cost_center,
                line.tax_code,
                line.net_amount,
                line.tax_amount,
                line.description,
                list(line.source_line_nos),
                line.coding_source.value,
            ),
        )
    return len(lines)


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


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(repo_root()))
    except ValueError:
        return str(path)


__all__ = [
    "LoadReport",
    "LoadedDocument",
    "load_fixtures",
    "load_master",
    "truncate",
]
