"""The ``Repository`` protocol over Postgres, using psycopg 3 with parameterized SQL only.

Rules that hold here:

- Every SQL statement is parameterized (``%s`` placeholders); values are never interpolated.
- ``fields``, ``line_items``, and ``coding_lines`` are append-with-history: saving marks the
  previous current rows ``is_current = false`` and inserts fresh rows. Nothing is updated in
  place.
- ``export_rows.doc_id`` is unique, so ``record_export`` raises if an invoice is exported twice.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from invoiceflow.contracts import (
    BronzeFile,
    CodingLine,
    CodingMaster,
    CodingSource,
    CompanyProfile,
    CostCenter,
    DocStatus,
    DocType,
    DocumentRecord,
    ExportBatch,
    ExtractionResult,
    FieldValue,
    Finding,
    GLAccount,
    MasterData,
    NormalizedInvoice,
    NormalizedLineItem,
    ParsedDocument,
    PriorInvoice,
    PurchaseOrder,
    Review,
    TaxCode,
    ValueSource,
    Vendor,
    VenueAlias,
)
from invoiceflow.normalize.normalizer import gst_inclusive_from_note
from invoiceflow.settings import data_relative, load_config
from invoiceflow.storage import words_rel_path
from invoiceflow.store.connection import connect

_EXPORTED = DocStatus.EXPORTED.value
# Header field names that differ on NormalizedInvoice.
_INVOICE_FIELD = {"gst_rate": "gst_rate_percent"}


def _line_item_from_row(row) -> NormalizedLineItem:
    line_no, description, quantity, unit, days, unit_price, amount = row
    return NormalizedLineItem(
        line_no=line_no,
        description=description,
        quantity=quantity,
        unit=unit,
        days=days,
        unit_price=unit_price,
        amount=amount,
    )


def _row_count(value: int) -> int:
    return max(1, value)


class Repo:
    """Postgres repository. Pass an open ``psycopg.Connection``; the caller owns commits."""

    def __init__(self, conn: Connection):
        self._conn = conn

    # ------------------------------------------------------------------ bronze
    def register_file(self, file: BronzeFile) -> bool:
        """True if new; False if a file with the same sha256 already exists."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bronze_files (file_id, sha256, original_name, source, sender,
                    received_at, size_bytes, mime_type, path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sha256) DO NOTHING
                RETURNING file_id
                """,
                (
                    file.file_id,
                    file.sha256,
                    file.original_name,
                    file.source,
                    file.sender,
                    file.received_at,
                    file.size_bytes,
                    file.mime_type,
                    file.path,
                ),
            )
            return cur.fetchone() is not None

    # ---------------------------------------------------------------- documents
    def unfinished_document(self, sha256: str) -> tuple[UUID, UUID] | None:
        """``(doc_id, file_id)`` of the file's RECEIVED document, left if intake stopped midway."""
        row = self._one(
            """
            SELECT d.doc_id, d.file_id
            FROM documents d JOIN bronze_files b USING (file_id)
            WHERE b.sha256 = %s AND d.status = %s
            """,
            (sha256, DocStatus.RECEIVED.value),
        )
        return (row[0], row[1]) if row else None

    def discard_document(self, doc_id: UUID, file_id: UUID) -> None:
        """Remove a document that never got past RECEIVED, and its file row, so a retry is not
        mistaken for a duplicate. A document with an outcome is never removed."""
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM documents WHERE doc_id = %s AND status = %s",
                (doc_id, DocStatus.RECEIVED.value),
            )
            cur.execute(
                """
                DELETE FROM bronze_files b
                WHERE b.file_id = %s
                  AND NOT EXISTS (SELECT 1 FROM documents d WHERE d.file_id = b.file_id)
                """,
                (file_id,),
            )

    def create_document(self, record: DocumentRecord) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (doc_id, file_id, doc_type, status, status_reason, vendor_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    record.doc_id,
                    record.file_id,
                    record.doc_type.value if record.doc_type else None,
                    record.status.value,
                    record.status_reason,
                    record.vendor_id,
                ),
            )

    def get_document(self, doc_id: UUID) -> DocumentRecord | None:
        row = self._one(
            """
            SELECT doc_id, file_id, doc_type, status, status_reason, vendor_id
            FROM documents WHERE doc_id = %s
            """,
            (doc_id,),
        )
        return None if row is None else self._document_from_row(row)

    def set_status(self, doc_id: UUID, status: DocStatus, reason: str | None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents SET status = %s, status_reason = %s, updated_at = now()
                WHERE doc_id = %s
                """,
                (status.value, reason, doc_id),
            )

    def set_document_meta(
        self, doc_id: UUID, doc_type: DocType | None, vendor_id: str | None
    ) -> None:
        """What intake learned about the document: its type and its matched vendor."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents SET doc_type = %s, vendor_id = %s, updated_at = now()
                WHERE doc_id = %s
                """,
                (doc_type.value if doc_type else None, vendor_id, doc_id),
            )

    def stored_invoice(self, doc_id: UUID) -> NormalizedInvoice | None:
        """The current values, including reviewer corrections, as a NormalizedInvoice.

        Raises ``ValueError`` if a stored value cannot be read as its type.
        """
        record = self.get_document(doc_id)
        if record is None:
            return None
        rows = self._all(
            "SELECT name, value_norm FROM fields WHERE doc_id = %s AND is_current", (doc_id,)
        )
        items = self._all(
            """
            SELECT line_no, description, quantity, unit, days, unit_price, amount
            FROM line_items WHERE doc_id = %s AND is_current ORDER BY line_no
            """,
            (doc_id,),
        )
        known = NormalizedInvoice.model_fields
        values = {_INVOICE_FIELD.get(name, name): value for name, value in rows}
        printed = {name: value for name, value in values.items() if name in known}
        return NormalizedInvoice(
            **{
                **printed,
                "document_type": record.doc_type,
                "gst_inclusive": gst_inclusive_from_note(values.get("gst_inclusive_note")),
                "line_items": tuple(_line_item_from_row(row) for row in items),
            }
        )

    def list_documents(self, statuses: tuple[DocStatus, ...]) -> tuple[DocumentRecord, ...]:
        values = [s.value for s in statuses]
        rows = self._all(
            """
            SELECT doc_id, file_id, doc_type, status, status_reason, vendor_id
            FROM documents WHERE status = ANY(%s) ORDER BY created_at
            """,
            (values,),
        )
        return tuple(self._document_from_row(r) for r in rows)

    # ------------------------------------------------------------------ silver
    def save_parsed(self, document: ParsedDocument) -> None:
        with self._conn.cursor() as cur:
            for page in document.pages:
                cur.execute(
                    """
                    INSERT INTO pages (doc_id, page_no, text_source, width_pt, height_pt,
                        image_path, words_path, ocr_mean_conf)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        document.doc_id,
                        page.page_no,
                        page.source.value,
                        page.width_pt,
                        page.height_pt,
                        data_relative(page.image_path),
                        words_rel_path(document.doc_id, page.page_no),
                        page.ocr_mean_conf,
                    ),
                )

    def save_extraction(self, result: ExtractionResult) -> None:
        parsed = result.extraction.model_dump(mode="json") if result.extraction else None
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO extractions (extraction_id, doc_id, model, model_digest,
                    prompt_version, schema_version, params, mode, raw_output, parsed, valid,
                    error, prompt_tokens, completion_tokens, latency_ms, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    result.extraction_id,
                    result.doc_id,
                    result.model,
                    result.model_digest,
                    result.prompt_version,
                    result.schema_version,
                    Jsonb(result.params),
                    result.mode.value,
                    result.raw_output,
                    Jsonb(parsed) if parsed is not None else None,
                    result.valid,
                    result.error,
                    result.prompt_tokens,
                    result.completion_tokens,
                    result.latency_ms,
                    result.created_at,
                ),
            )

    def save_fields(
        self,
        doc_id: UUID,
        fields: tuple[FieldValue, ...],
        line_items: tuple[NormalizedLineItem, ...],
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE fields SET is_current = false WHERE doc_id = %s AND is_current", (doc_id,)
            )
            for field in fields:
                bbox = field.bbox
                cur.execute(
                    """
                    INSERT INTO fields (doc_id, name, value_raw, value_norm, page_no, x0, y0, x1,
                        y1, match_type, match_score, confidence, source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        doc_id,
                        field.name,
                        field.value_raw,
                        field.value_norm,
                        field.page_no,
                        bbox.x0 if bbox else None,
                        bbox.y0 if bbox else None,
                        bbox.x1 if bbox else None,
                        bbox.y1 if bbox else None,
                        field.match_type.value,
                        field.match_score,
                        field.confidence.value,
                        field.source.value,
                    ),
                )
            cur.execute(
                "UPDATE line_items SET is_current = false WHERE doc_id = %s AND is_current",
                (doc_id,),
            )
            for item in line_items:
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
                        ValueSource.MODEL.value,
                    ),
                )

    def save_coding(self, doc_id: UUID, lines: tuple[CodingLine, ...]) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE coding_lines SET is_current = false WHERE doc_id = %s AND is_current",
                (doc_id,),
            )
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

    def save_findings(self, doc_id: UUID, run_id: str, findings: tuple[Finding, ...]) -> None:
        with self._conn.cursor() as cur:
            for finding in findings:
                cur.execute(
                    """
                    INSERT INTO findings (doc_id, run_id, stage, rule_id, rule_version, severity,
                        scope, field, message, evidence)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        doc_id,
                        run_id,
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

    def coding_lines(self, doc_id: UUID) -> tuple[CodingLine, ...]:
        """Current coding lines for a document, in line order. Used by the export stub."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT line_no, gl_account, cost_center, tax_code, net_amount, tax_amount,
                       description, source_line_nos, coding_source
                FROM coding_lines WHERE doc_id = %s AND is_current ORDER BY line_no
                """,
                (doc_id,),
            )
            return tuple(self._coding_from_row(row) for row in cur.fetchall())

    def add_review(self, review: Review) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reviews (doc_id, reviewer, action, field, old_value, new_value, comment,
                    created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    review.doc_id,
                    review.reviewer,
                    review.action.value,
                    review.field,
                    review.old_value,
                    review.new_value,
                    review.comment,
                    review.created_at,
                ),
            )

    # ------------------------------------------------------------------ master
    def save_master(self, master: MasterData) -> None:
        """Insert the master data rows (gl/cost/tax/venues/vendors/POs). Caller truncates first."""
        coding = master.coding
        with self._conn.cursor() as cur:
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
                "INSERT INTO venue_cost_centers (alias, cost_center) VALUES (%s, %s)",
                [(v.alias, v.cost_center) for v in coding.venue_aliases],
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

    def master_loaded(self) -> bool:
        """True when the master tables already have rows (so ``save_master`` would collide)."""
        row = self._one("SELECT count(*) FROM vendors")
        return bool(row and row[0] > 0)

    def load_master(self) -> MasterData:
        company = self._company()
        with self._conn.cursor() as cur:
            vendors = tuple(
                self._vendor_from_row(r) for r in self._all_rows(cur, self._VENDORS_SQL)
            )
            pos = tuple(self._po_from_row(r) for r in self._all_rows(cur, self._POS_SQL))
            gls = tuple(self._gl_from_row(r) for r in self._all_rows(cur, self._GL_SQL))
            centers = tuple(
                self._center_from_row(r) for r in self._all_rows(cur, self._CENTERS_SQL)
            )
            taxes = tuple(self._tax_from_row(r) for r in self._all_rows(cur, self._TAX_SQL))
            aliases = tuple(self._alias_from_row(r) for r in self._all_rows(cur, self._ALIASES_SQL))
        coding = CodingMaster(
            gl_accounts=gls, cost_centers=centers, tax_codes=taxes, venue_aliases=aliases
        )
        return MasterData(company=company, vendors=vendors, purchase_orders=pos, coding=coding)

    _VENDORS_SQL = (
        "SELECT vendor_id, sap_vendor_no, name, uen, gst_reg_no, address, bank_name, bank_account,"
        " currency, locale, is_overseas, default_gl, default_cost_center, default_tax_code, active"
        " FROM vendors ORDER BY vendor_id"
    )
    _POS_SQL = (
        "SELECT po_number, vendor_id, currency, amount, open_amount, gl_account, cost_center"
        " FROM purchase_orders ORDER BY po_number"
    )
    _GL_SQL = "SELECT code, name, active FROM gl_accounts ORDER BY code"
    _CENTERS_SQL = "SELECT code, name, active FROM cost_centers ORDER BY code"
    _TAX_SQL = "SELECT code, rate_percent, description FROM tax_codes ORDER BY code"
    _ALIASES_SQL = "SELECT alias, cost_center FROM venue_cost_centers ORDER BY alias"

    def prior_invoices(self, vendor_id: str | None) -> tuple[PriorInvoice, ...]:
        """Earlier invoices for one vendor, or for every known vendor when ``vendor_id`` is None.

        Intake needs them before the vendor is matched, and R05 compares vendors itself.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.doc_id, d.vendor_id,
                       (SELECT value_norm FROM fields WHERE doc_id = d.doc_id
                          AND name = 'invoice_number' AND is_current LIMIT 1) AS invoice_number,
                       (SELECT value_norm FROM fields WHERE doc_id = d.doc_id
                          AND name = 'total' AND is_current LIMIT 1) AS total,
                       (SELECT value_norm FROM fields WHERE doc_id = d.doc_id
                          AND name = 'invoice_date' AND is_current LIMIT 1) AS invoice_date,
                       b.sha256
                FROM documents d JOIN bronze_files b USING (file_id)
                WHERE d.vendor_id IS NOT NULL
                  AND (%s::text IS NULL OR d.vendor_id = %s)
                  AND d.status <> 'NOT_INVOICE'
                ORDER BY d.created_at
                """,
                (vendor_id, vendor_id),
            )
            rows = cur.fetchall()
        return tuple(self._prior_from_row(r) for r in rows)

    # --------------------------------------------------------------------- gold
    def approved_not_exported(self) -> tuple[UUID, ...]:
        rows = self._all(
            """
            SELECT d.doc_id FROM documents d
            LEFT JOIN export_rows e ON e.doc_id = d.doc_id
            WHERE d.status IN ('APPROVED', 'AUTO_PASSED') AND e.doc_id IS NULL
            ORDER BY d.created_at
            """
        )
        return tuple(row[0] for row in rows)

    def record_export(
        self,
        batch: ExportBatch,
        doc_ids: tuple[UUID, ...],
        manifest: Mapping[str, Any] | None = None,
    ) -> None:
        """One transaction. Raises if any doc_id was exported before (unique doc_id)."""
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO export_batches (batch_id, created_at, csv_path, csv_sha256, row_count,
                    total, layout, mapping_version, manifest)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    batch.batch_id,
                    batch.created_at,
                    batch.csv_path,
                    batch.csv_sha256,
                    batch.row_count,
                    batch.total,
                    batch.layout,
                    batch.mapping_version,
                    Jsonb(dict(manifest or {})),
                ),
            )
            first_row = 1
            for doc_id in doc_ids:
                cur.execute(
                    "SELECT count(*) FROM coding_lines WHERE doc_id = %s AND is_current", (doc_id,)
                )
                rows = _row_count(cur.fetchone()[0])
                cur.execute(
                    """
                    INSERT INTO export_rows (batch_id, doc_id, first_row_no, row_count)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (batch.batch_id, doc_id, first_row, rows),
                )
                cur.execute(
                    "UPDATE documents SET status = %s, updated_at = now() WHERE doc_id = %s",
                    (_EXPORTED, doc_id),
                )
                first_row += rows

    # ------------------------------------------------------------------- audit
    def log_event(
        self, actor: str, event_type: str, doc_id: UUID | None, payload: dict[str, Any]
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO events (actor, doc_id, type, payload) VALUES (%s, %s, %s, %s)",
                (actor, doc_id, event_type, Jsonb(payload)),
            )

    # ----------------------------------------------------------------- helpers
    def _one(self, sql: str, params: tuple[Any, ...] = ()):
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _all(self, sql: str, params: tuple[Any, ...] = ()):
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    @staticmethod
    def _all_rows(cur, sql: str):
        cur.execute(sql)
        return cur.fetchall()

    @staticmethod
    def _company() -> CompanyProfile:
        cfg = load_config("company")
        return CompanyProfile(
            company_code=cfg["company_code"],
            currency=cfg.get("currency", "SGD"),
            timezone=cfg.get("timezone", "Asia/Singapore"),
            entity_names=tuple(cfg["entity_names"]),
        )

    @staticmethod
    def _document_from_row(row) -> DocumentRecord:
        doc_id, file_id, doc_type, status, status_reason, vendor_id = row
        return DocumentRecord(
            doc_id=doc_id,
            file_id=file_id,
            doc_type=DocType(doc_type) if doc_type else None,
            status=DocStatus(status),
            status_reason=status_reason,
            vendor_id=vendor_id,
        )

    @staticmethod
    def _vendor_from_row(row) -> Vendor:
        (
            vendor_id,
            sap_vendor_no,
            name,
            uen,
            gst_reg_no,
            address,
            bank_name,
            bank_account,
            currency,
            locale,
            is_overseas,
            default_gl,
            default_cost_center,
            default_tax_code,
            active,
        ) = row
        return Vendor(
            vendor_id=vendor_id,
            sap_vendor_no=sap_vendor_no,
            name=name,
            uen=uen,
            gst_reg_no=gst_reg_no,
            address=address,
            bank_name=bank_name,
            bank_account=bank_account,
            currency=currency.strip() if currency else "SGD",
            locale=locale,
            is_overseas=is_overseas,
            default_gl=default_gl,
            default_cost_center=default_cost_center,
            default_tax_code=default_tax_code,
            active=active,
        )

    @staticmethod
    def _po_from_row(row) -> PurchaseOrder:
        po_number, vendor_id, currency, amount, open_amount, gl_account, cost_center = row
        return PurchaseOrder(
            po_number=po_number,
            vendor_id=vendor_id,
            currency=currency.strip() if currency else "SGD",
            amount=amount,
            open_amount=open_amount,
            gl_account=gl_account,
            cost_center=cost_center,
        )

    @staticmethod
    def _gl_from_row(row) -> GLAccount:
        code, name, active = row
        return GLAccount(code=code, name=name, active=active)

    @staticmethod
    def _center_from_row(row) -> CostCenter:
        code, name, active = row
        return CostCenter(code=code, name=name, active=active)

    @staticmethod
    def _tax_from_row(row) -> TaxCode:
        code, rate_percent, description = row
        return TaxCode(code=code, rate_percent=Decimal(rate_percent), description=description)

    @staticmethod
    def _alias_from_row(row) -> VenueAlias:
        alias, cost_center = row
        return VenueAlias(alias=alias, cost_center=cost_center)

    @staticmethod
    def _coding_from_row(row) -> CodingLine:
        (
            line_no,
            gl_account,
            cost_center,
            tax_code,
            net_amount,
            tax_amount,
            description,
            source_line_nos,
            coding_source,
        ) = row
        return CodingLine(
            line_no=line_no,
            gl_account=gl_account,
            cost_center=cost_center,
            tax_code=tax_code,
            net_amount=net_amount,
            tax_amount=tax_amount,
            description=description,
            source_line_nos=tuple(source_line_nos or ()),
            coding_source=CodingSource(coding_source),
        )

    @staticmethod
    def _prior_from_row(row) -> PriorInvoice:
        doc_id, vendor_id, invoice_number, total, invoice_date, sha256 = row
        return PriorInvoice(
            doc_id=doc_id,
            vendor_id=vendor_id,
            invoice_number=invoice_number,
            total=Decimal(total) if total is not None else None,
            invoice_date=date.fromisoformat(invoice_date) if invoice_date else None,
            file_sha256=sha256,
        )


@contextmanager
def repo_transaction() -> Iterator[Repo]:
    """One transaction on a new connection: committed when the block ends, rolled back if it
    raises. ``intake_in_steps`` opens one per step."""
    with connect() as conn, conn.transaction():
        yield Repo(conn)
