"""Read-only SQL for the review app. Writes live in ``app/repo.py``.

Every function takes an open psycopg connection so the Streamlit backend (and the
integration tests) decide the transaction. The SQL only ever SELECTs.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row

from app.formatting import percent
from app.models import (
    BatchSummary,
    CheckCount,
    CodingRow,
    CountRow,
    DashboardData,
    DiscardedCopy,
    DocumentBundle,
    DocumentSummary,
    EventRow,
    ExtractionInfo,
    FieldRow,
    FindingRow,
    LineItemRow,
    PageRow,
    ReviewRow,
    TraceData,
)
from invoiceflow.contracts import (
    BBox,
    CodingMaster,
    CodingSource,
    CompanyProfile,
    Confidence,
    CostCenter,
    DocStatus,
    DocType,
    GLAccount,
    LLMMode,
    MasterData,
    MatchType,
    PurchaseOrder,
    ReviewAction,
    Scope,
    Severity,
    Stage,
    TaxCode,
    ValueSource,
    Vendor,
    VenueAlias,
)
from invoiceflow.settings import load_config

_SEVERITY_BY_RANK = {
    None: None,
    0: Severity.INFO,
    1: Severity.FLAG,
    2: Severity.HOLD,
    3: Severity.MANUAL,
}

_SUMMARY_SQL = """
SELECT d.doc_id,
       d.status,
       d.status_reason,
       d.doc_type,
       d.vendor_id,
       v.name AS vendor_name,
       inv.value_norm AS invoice_number,
       sup.value_norm AS supplier_name,
       tot.value_norm AS total,
       b.received_at,
       b.original_name AS file_name,
       b.path AS file_path,
       ttl.value_raw AS printed_title,
       pg.image_path AS first_page_image,
       ext.mode AS extraction_mode,
       ext.valid AS extraction_valid,
       fc.open_rules,
       COALESCE(fc.finding_count, 0) AS finding_count,
       fc.max_rank
FROM documents d
JOIN bronze_files b ON b.file_id = d.file_id
LEFT JOIN vendors v ON v.vendor_id = d.vendor_id
LEFT JOIN LATERAL (
    SELECT f.value_norm
    FROM fields f
    WHERE f.doc_id = d.doc_id AND f.name = 'invoice_number' AND f.is_current
    ORDER BY f.row_id DESC LIMIT 1
) inv ON true
LEFT JOIN LATERAL (
    SELECT f.value_norm
    FROM fields f
    WHERE f.doc_id = d.doc_id AND f.name = 'supplier_name' AND f.is_current
    ORDER BY f.row_id DESC LIMIT 1
) sup ON true
LEFT JOIN LATERAL (
    SELECT f.value_norm
    FROM fields f
    WHERE f.doc_id = d.doc_id AND f.name = 'total' AND f.is_current
    ORDER BY f.row_id DESC LIMIT 1
) tot ON true
LEFT JOIN LATERAL (
    SELECT f.value_raw
    FROM fields f
    WHERE f.doc_id = d.doc_id AND f.name = 'title' AND f.is_current
    ORDER BY f.row_id DESC LIMIT 1
) ttl ON true
LEFT JOIN LATERAL (
    SELECT p.image_path
    FROM pages p
    WHERE p.doc_id = d.doc_id
    ORDER BY p.page_no LIMIT 1
) pg ON true
LEFT JOIN LATERAL (
    SELECT e.extraction_id, e.mode, e.valid
    FROM extractions e
    WHERE e.doc_id = d.doc_id
    ORDER BY e.created_at DESC, e.extraction_id DESC LIMIT 1
) ext ON true
LEFT JOIN LATERAL (
    SELECT count(*) AS finding_count,
           array_agg(DISTINCT f.rule_id) AS open_rules,
           max(CASE f.severity
                 WHEN 'MANUAL' THEN 3
                 WHEN 'HOLD' THEN 2
                 WHEN 'FLAG' THEN 1
                 ELSE 0 END) AS max_rank
    FROM findings f
    WHERE f.doc_id = d.doc_id
      AND f.run_id = COALESCE(
          (SELECT ev.payload->>'run_id'
           FROM events ev
           WHERE ev.doc_id = d.doc_id AND ev.type = 'recheck.completed'
           ORDER BY ev.ts DESC, ev.event_id DESC LIMIT 1),
          (SELECT f2.run_id
           FROM findings f2
           WHERE f2.doc_id = d.doc_id
           ORDER BY f2.created_at DESC, f2.finding_id DESC LIMIT 1)
      )
) fc ON true
WHERE (%(statuses)s::text[] IS NULL OR d.status = ANY(%(statuses)s))
ORDER BY b.received_at DESC NULLS LAST, d.created_at DESC
"""


def _summary(row: dict[str, Any]) -> DocumentSummary:
    return DocumentSummary(
        doc_id=row["doc_id"],
        status=DocStatus(row["status"]),
        status_reason=row["status_reason"],
        doc_type=DocType(row["doc_type"]) if row["doc_type"] else None,
        vendor_id=row["vendor_id"],
        vendor_name=row["vendor_name"],
        invoice_number=row["invoice_number"],
        supplier_name=row["supplier_name"],
        total=Decimal(row["total"]) if row["total"] is not None else None,
        received_at=row["received_at"],
        is_replay=row["extraction_mode"] == LLMMode.REPLAY.value,
        finding_count=int(row["finding_count"] or 0),
        highest_severity=_SEVERITY_BY_RANK.get(row["max_rank"]),
        open_rules=tuple(row["open_rules"] or ()),
        first_page_image=row["first_page_image"],
        extraction_valid=row["extraction_valid"],
        printed_title=row["printed_title"],
        file_name=row["file_name"],
        file_path=row["file_path"],
    )


def list_documents(
    conn: Connection, statuses: Sequence[DocStatus] = ()
) -> tuple[DocumentSummary, ...]:
    params = {"statuses": [s.value for s in statuses] if statuses else None}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SUMMARY_SQL, params)
        return tuple(_summary(row) for row in cur.fetchall())


def get_document(conn: Connection, doc_id: UUID) -> DocumentSummary | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SUMMARY_SQL, {"statuses": None})
        return next((_summary(row) for row in cur.fetchall() if row["doc_id"] == doc_id), None)


def latest_run_id(conn: Connection, doc_id: UUID) -> str | None:
    """A recheck is recorded as an event, so a run with zero findings still counts."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(
                (SELECT payload->>'run_id'
                 FROM events
                 WHERE doc_id = %s AND type = 'recheck.completed'
                 ORDER BY ts DESC, event_id DESC LIMIT 1),
                (SELECT run_id FROM findings
                 WHERE doc_id = %s ORDER BY created_at DESC, finding_id DESC LIMIT 1)
            )
            """,
            (doc_id, doc_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def fields(conn: Connection, doc_id: UUID) -> tuple[FieldRow, ...]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT name, value_raw, value_norm, page_no, x0, y0, x1, y1,
                   match_type, match_score, confidence, source
            FROM fields
            WHERE doc_id = %s AND is_current
            ORDER BY page_no NULLS LAST, y0 NULLS LAST, x0 NULLS LAST, name
            """,
            (doc_id,),
        )
        rows = []
        for row in cur.fetchall():
            bbox = None
            if None not in (row["x0"], row["y0"], row["x1"], row["y1"]):
                bbox = BBox(
                    x0=float(row["x0"]),
                    y0=float(row["y0"]),
                    x1=float(row["x1"]),
                    y1=float(row["y1"]),
                )
            rows.append(
                FieldRow(
                    name=row["name"],
                    value_raw=row["value_raw"],
                    value_norm=row["value_norm"],
                    page_no=row["page_no"],
                    bbox=bbox,
                    match_type=MatchType(row["match_type"]),
                    match_score=float(row["match_score"] or 0),
                    confidence=Confidence(row["confidence"]),
                    source=ValueSource(row["source"]),
                )
            )
        return tuple(rows)


def line_items(conn: Connection, doc_id: UUID) -> tuple[LineItemRow, ...]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT line_no, description, quantity, unit, days, unit_price, amount, source
            FROM line_items
            WHERE doc_id = %s AND is_current
            ORDER BY line_no
            """,
            (doc_id,),
        )
        return tuple(
            LineItemRow(
                line_no=row["line_no"],
                description=row["description"],
                quantity=row["quantity"],
                unit=row["unit"],
                days=row["days"],
                unit_price=row["unit_price"],
                amount=row["amount"],
                source=ValueSource(row["source"]),
            )
            for row in cur.fetchall()
        )


def coding_lines(conn: Connection, doc_id: UUID) -> tuple[CodingRow, ...]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT line_no, gl_account, cost_center, tax_code, net_amount, tax_amount,
                   description, source_line_nos, coding_source
            FROM coding_lines
            WHERE doc_id = %s AND is_current
            ORDER BY line_no
            """,
            (doc_id,),
        )
        return tuple(
            CodingRow(
                line_no=row["line_no"],
                gl_account=row["gl_account"],
                cost_center=row["cost_center"],
                tax_code=row["tax_code"],
                net_amount=row["net_amount"],
                tax_amount=row["tax_amount"],
                description=row["description"],
                source_line_nos=tuple(row["source_line_nos"] or ()),
                coding_source=CodingSource(row["coding_source"]),
            )
            for row in cur.fetchall()
        )


def _finding(row: dict[str, Any]) -> FindingRow:
    return FindingRow(
        rule_id=row["rule_id"],
        field=row["field"],
        severity=Severity(row["severity"]),
        scope=Scope(row["scope"]),
        message=row["message"],
        evidence=dict(row["evidence"] or {}),
        stage=Stage(row["stage"]),
        run_id=row["run_id"],
        rule_version=row.get("rule_version"),
    )


def findings(conn: Connection, doc_id: UUID, run_id: str | None = None) -> tuple[FindingRow, ...]:
    run = run_id or latest_run_id(conn, doc_id)
    if run is None:
        return ()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT rule_id, field, severity, scope, message, evidence, stage, run_id,
                   rule_version
            FROM findings
            WHERE doc_id = %s AND run_id = %s
            ORDER BY finding_id
            """,
            (doc_id, run),
        )
        return tuple(_finding(row) for row in cur.fetchall())


def finding_history(conn: Connection, doc_id: UUID) -> tuple[FindingRow, ...]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT rule_id, field, severity, scope, message, evidence, stage, run_id,
                   rule_version
            FROM findings
            WHERE doc_id = %s
            ORDER BY finding_id
            """,
            (doc_id,),
        )
        return tuple(_finding(row) for row in cur.fetchall())


def reviews(conn: Connection, doc_id: UUID) -> tuple[ReviewRow, ...]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT reviewer, action, field, old_value, new_value, comment, created_at
            FROM reviews
            WHERE doc_id = %s
            ORDER BY created_at, review_id
            """,
            (doc_id,),
        )
        return tuple(
            ReviewRow(
                action=ReviewAction(row["action"]),
                reviewer=row["reviewer"],
                field=row["field"],
                old_value=row["old_value"],
                new_value=row["new_value"],
                comment=row["comment"],
                created_at=row["created_at"],
            )
            for row in cur.fetchall()
        )


def events(conn: Connection, doc_id: UUID) -> tuple[EventRow, ...]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT event_id, ts, actor, type, payload
            FROM events
            WHERE doc_id = %s
            ORDER BY ts, event_id
            """,
            (doc_id,),
        )
        return tuple(
            EventRow(
                event_id=row["event_id"],
                ts=row["ts"],
                actor=row["actor"],
                type=row["type"],
                payload=dict(row["payload"] or {}),
            )
            for row in cur.fetchall()
        )


def pages(conn: Connection, doc_id: UUID) -> tuple[PageRow, ...]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT page_no, image_path, words_path, width_pt, height_pt, ocr_mean_conf
            FROM pages
            WHERE doc_id = %s
            ORDER BY page_no
            """,
            (doc_id,),
        )
        return tuple(
            PageRow(
                page_no=row["page_no"],
                image_path=row["image_path"],
                words_path=row["words_path"],
                width_pt=float(row["width_pt"]),
                height_pt=float(row["height_pt"]),
                ocr_mean_conf=float(row["ocr_mean_conf"])
                if row["ocr_mean_conf"] is not None
                else None,
            )
            for row in cur.fetchall()
        )


def extraction(conn: Connection, doc_id: UUID) -> ExtractionInfo | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT extraction_id, model, model_digest, prompt_version, schema_version,
                   mode, valid, error, latency_ms, created_at, raw_output, parsed,
                   prompt_tokens, completion_tokens, params
            FROM extractions
            WHERE doc_id = %s
            ORDER BY created_at DESC, extraction_id DESC
            LIMIT 1
            """,
            (doc_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return ExtractionInfo(
            extraction_id=row["extraction_id"],
            model=row["model"],
            model_digest=row["model_digest"],
            prompt_version=row["prompt_version"],
            schema_version=row["schema_version"],
            mode=LLMMode(row["mode"]),
            valid=row["valid"],
            error=row["error"],
            latency_ms=row["latency_ms"],
            created_at=row["created_at"],
            raw_output=row["raw_output"],
            parsed=row["parsed"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            images_sent=(row["params"] or {}).get("n_images"),
        )


def document_bundle(conn: Connection, doc_id: UUID) -> DocumentBundle | None:
    summary = get_document(conn, doc_id)
    if summary is None:
        return None
    return DocumentBundle(
        document=summary,
        fields=fields(conn, doc_id),
        line_items=line_items(conn, doc_id),
        coding_lines=coding_lines(conn, doc_id),
        findings=findings(conn, doc_id),
        reviews=reviews(conn, doc_id),
        pages=pages(conn, doc_id),
        extraction=extraction(conn, doc_id),
        events=events(conn, doc_id),
    )


def trace(conn: Connection, doc_id: UUID) -> TraceData | None:
    bundle = document_bundle(conn, doc_id)
    if bundle is None:
        return None
    runs = []
    for finding in finding_history(conn, doc_id):
        if finding.run_id and finding.run_id not in runs:
            runs.append(finding.run_id)
    for event in bundle.events:
        run_id = event.payload.get("run_id")
        if event.type == "recheck.completed" and run_id and run_id not in runs:
            runs.append(str(run_id))
    return TraceData(bundle=bundle, finding_history=finding_history(conn, doc_id), runs=tuple(runs))


def run_history(conn: Connection, doc_id: UUID) -> tuple[str, ...]:
    return trace(conn, doc_id).runs if trace(conn, doc_id) else ()


def master_data(conn: Connection) -> MasterData:
    company = load_config("company")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT vendor_id, sap_vendor_no, name, uen, gst_reg_no, address, bank_name,
                   bank_account, currency, locale, is_overseas, default_gl,
                   default_cost_center, default_tax_code, active
            FROM vendors ORDER BY vendor_id
            """
        )
        vendors = tuple(Vendor(**row) for row in cur.fetchall())
        cur.execute(
            """
            SELECT po_number, vendor_id, currency, amount, open_amount, gl_account, cost_center
            FROM purchase_orders ORDER BY po_number
            """
        )
        purchase_orders = tuple(PurchaseOrder(**row) for row in cur.fetchall())
        cur.execute("SELECT code, name, active FROM gl_accounts ORDER BY code")
        gl_accounts = tuple(GLAccount(**row) for row in cur.fetchall())
        cur.execute("SELECT code, name, active FROM cost_centers ORDER BY code")
        cost_centers = tuple(CostCenter(**row) for row in cur.fetchall())
        cur.execute("SELECT code, rate_percent, description FROM tax_codes ORDER BY code")
        tax_codes = tuple(TaxCode(**row) for row in cur.fetchall())
        cur.execute("SELECT alias, cost_center FROM venue_cost_centers ORDER BY alias")
        venue_aliases = tuple(VenueAlias(**row) for row in cur.fetchall())
    return MasterData(
        company=CompanyProfile(
            company_code=company["company_code"],
            currency=company.get("currency", "SGD"),
            timezone=company.get("timezone", "Asia/Singapore"),
            entity_names=tuple(company.get("entity_names", ())),
        ),
        vendors=vendors,
        purchase_orders=purchase_orders,
        coding=CodingMaster(
            gl_accounts=gl_accounts,
            cost_centers=cost_centers,
            tax_codes=tax_codes,
            venue_aliases=venue_aliases,
        ),
    )


def _counts(conn: Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE status = 'AUTO_PASSED') AS auto_passed,
                   count(*) FILTER (WHERE status = 'NEEDS_REVIEW') AS needs_review,
                   count(*) FILTER (WHERE status = 'APPROVED') AS approved,
                   count(*) FILTER (WHERE status = 'REJECTED') AS rejected,
                   count(*) FILTER (WHERE status = 'ON_HOLD') AS on_hold
            FROM documents
            """
        )
        row = cur.fetchone()
        return {
            "total": int(row[0]),
            "auto_passed": int(row[1]),
            "needs_review": int(row[2]),
            "approved": int(row[3]),
            "rejected": int(row[4]),
            "on_hold": int(row[5]),
        }


def findings_by_check(conn: Connection) -> tuple[CheckCount, ...]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH runs AS (
                SELECT d.doc_id,
                       COALESCE(
                           (SELECT ev.payload->>'run_id'
                            FROM events ev
                            WHERE ev.doc_id = d.doc_id AND ev.type = 'recheck.completed'
                            ORDER BY ev.ts DESC, ev.event_id DESC LIMIT 1),
                           (SELECT f.run_id FROM findings f
                            WHERE f.doc_id = d.doc_id
                            ORDER BY f.created_at DESC, f.finding_id DESC LIMIT 1)
                       ) AS run_id
                FROM documents d
            )
            SELECT f.rule_id, f.severity, count(*) AS n
            FROM runs r
            JOIN findings f ON f.doc_id = r.doc_id AND f.run_id = r.run_id
            GROUP BY f.rule_id, f.severity
            ORDER BY f.rule_id
            """
        )
        return tuple(
            CheckCount(rule_id=row["rule_id"], severity=Severity(row["severity"]), count=row["n"])
            for row in cur.fetchall()
        )


def corrections_by_field(conn: Connection) -> tuple[CountRow, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(field, '(document)') AS key, count(*) AS n
            FROM reviews
            WHERE action = 'CORRECT'
            GROUP BY 1 ORDER BY n DESC, key
            """
        )
        return tuple(CountRow(key=row[0], count=int(row[1])) for row in cur.fetchall())


def corrections_by_vendor(conn: Connection) -> tuple[CountRow, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(v.name, d.vendor_id, 'unknown') AS key, count(*) AS n
            FROM reviews r
            JOIN documents d USING (doc_id)
            LEFT JOIN vendors v ON v.vendor_id = d.vendor_id
            WHERE r.action = 'CORRECT'
            GROUP BY 1 ORDER BY n DESC, key
            """
        )
        return tuple(CountRow(key=row[0], count=int(row[1])) for row in cur.fetchall())


def average_seconds_per_invoice(conn: Connection) -> float | None:
    """Prefer recorded model latency; fall back to the span between a document's events."""
    with conn.cursor() as cur:
        cur.execute("SELECT avg(latency_ms) FROM extractions WHERE latency_ms IS NOT NULL")
        row = cur.fetchone()
        if row and row[0] is not None:
            return float(row[0]) / 1000.0
        cur.execute(
            """
            SELECT avg(span) FROM (
                SELECT extract(epoch FROM max(ts) - min(ts)) AS span
                FROM events GROUP BY doc_id HAVING count(*) > 1
            ) spans
            """
        )
        row = cur.fetchone()
        if row and row[0] is not None and float(row[0]) > 0:
            return float(row[0])
        return None


def total_value(conn: Connection) -> Decimal:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(sum(value_norm::numeric), 0)
            FROM fields WHERE name = 'total' AND is_current
            """
        )
        return Decimal(cur.fetchone()[0])


def dashboard(conn: Connection, latest_evaluation=None) -> DashboardData:
    counts = _counts(conn)
    return DashboardData(
        total_documents=counts["total"],
        auto_passed=counts["auto_passed"],
        needs_review=counts["needs_review"],
        approved=counts["approved"],
        rejected=counts["rejected"],
        on_hold=counts["on_hold"],
        auto_pass_rate=percent(counts["auto_passed"], counts["total"]),
        findings_by_check=findings_by_check(conn),
        avg_seconds_per_invoice=average_seconds_per_invoice(conn),
        corrections_by_field=corrections_by_field(conn),
        corrections_by_vendor=corrections_by_vendor(conn),
        hold_count=counts["on_hold"],
        total_value=total_value(conn),
        latest_evaluation=latest_evaluation,
    )


def batches(conn: Connection) -> tuple[BatchSummary, ...]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT b.batch_id, b.created_at, b.csv_path, b.csv_sha256, b.row_count, b.total,
                   b.layout, b.mapping_version, b.manifest,
                   COALESCE(array_agg(r.doc_id) FILTER (WHERE r.doc_id IS NOT NULL), '{}')
                       AS doc_ids
            FROM export_batches b
            LEFT JOIN export_rows r USING (batch_id)
            GROUP BY b.batch_id
            ORDER BY b.created_at DESC
            """
        )
        return tuple(
            BatchSummary(
                batch_id=row["batch_id"],
                created_at=row["created_at"],
                csv_path=row["csv_path"],
                row_count=row["row_count"],
                total=row["total"],
                layout=row["layout"],
                mapping_version=row["mapping_version"],
                doc_ids=tuple(row["doc_ids"] or ()),
                csv_sha256=row["csv_sha256"],
                manifest=dict(row["manifest"] or {}),
            )
            for row in cur.fetchall()
        )


def export_status(conn: Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM export_rows")
        exported = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT count(*) FROM documents d
            LEFT JOIN export_rows e ON e.doc_id = d.doc_id
            WHERE d.status IN ('APPROVED', 'AUTO_PASSED') AND e.doc_id IS NULL
            """
        )
        ready = int(cur.fetchone()[0])
    return {"exported": exported, "approved_not_exported": ready}


# Discard events whose matching file is still stored, so erasing the live-demo set leaves
# no stale count. bronze_files.sha256 is char(64), so it comes back padded; trim it.
_DISCARDED_FROM = """
    FROM events e
    JOIN bronze_files b ON b.sha256 = e.payload->>'sha256'
    JOIN documents d ON d.file_id = b.file_id
    WHERE e.type = 'intake.duplicate_file'
"""


def discarded_duplicates(conn: Connection) -> int:
    """Files intake discarded as byte-identical copies of a stored file."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*)" + _DISCARDED_FROM)
        return int(cur.fetchone()[0])


def discarded_copies(conn: Connection) -> tuple[DiscardedCopy, ...]:
    """Each discarded copy beside the stored original it matched, for the user to check."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT e.payload->>'name' AS name, e.ts AS arrived_at,"
            " e.payload->>'sha256' AS sha256, trim(b.sha256) AS kept_sha256, d.doc_id"
            + _DISCARDED_FROM
            + " ORDER BY e.ts, e.event_id"
        )
        rows = cur.fetchall()
    if not rows:
        return ()
    originals = {doc.doc_id: doc for doc in list_documents(conn)}
    return tuple(
        DiscardedCopy(
            name=row["name"],
            arrived_at=row["arrived_at"],
            sha256=row["sha256"],
            kept_sha256=row["kept_sha256"],
            original=originals[row["doc_id"]],
        )
        for row in rows
        if row["doc_id"] in originals
    )


def latest_document_time(conn: Connection) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT max(updated_at) FROM documents")
        row = cur.fetchone()
        return row[0] if row else None


__all__ = [
    "average_seconds_per_invoice",
    "batches",
    "coding_lines",
    "corrections_by_field",
    "corrections_by_vendor",
    "dashboard",
    "discarded_copies",
    "discarded_duplicates",
    "document_bundle",
    "events",
    "export_status",
    "extraction",
    "fields",
    "finding_history",
    "findings",
    "findings_by_check",
    "get_document",
    "latest_run_id",
    "line_items",
    "list_documents",
    "master_data",
    "pages",
    "reviews",
    "run_history",
    "total_value",
    "trace",
]
