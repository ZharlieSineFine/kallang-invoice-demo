"""TEMPORARY write adapter for WS6's ``store.repo`` (not present at ``contracts-v1``).

The interface names mirror the frozen ``Repository`` protocol, but this module also exposes
the review-specific writes WS7 needs. When WS6's repository lands, ``app/backend.py`` swaps
these calls for ``store.repo``; the pages do not change. Everything here runs inside the
caller's transaction and keeps field/line/coding history by clearing ``is_current`` and
inserting a new version instead of updating in place.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from invoiceflow.contracts import (
    BBox,
    CodingLine,
    Confidence,
    DocStatus,
    Finding,
    MatchType,
    NormalizedLineItem,
    Review,
    ValueSource,
)


def _numeric(value: float) -> Decimal:
    return Decimal(str(value))


def latest_extraction_id(conn: Connection, doc_id: UUID) -> UUID | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT extraction_id FROM extractions
            WHERE doc_id = %s ORDER BY created_at DESC, extraction_id DESC LIMIT 1
            """,
            (doc_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def save_field_value(
    conn: Connection,
    doc_id: UUID,
    *,
    name: str,
    value_raw: str | None,
    value_norm: str | None,
    page_no: int | None = None,
    bbox: BBox | None = None,
    match_type: MatchType = MatchType.EXACT,
    match_score: float = 100.0,
    confidence: Confidence = Confidence.HIGH,
    source: ValueSource = ValueSource.REVIEWER,
    extraction_id: UUID | None = None,
) -> None:
    """Version one field: the old current row stops being current, a new row is added."""
    extraction_id = extraction_id or latest_extraction_id(conn, doc_id)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE fields SET is_current = false WHERE doc_id = %s AND name = %s AND is_current",
            (doc_id, name),
        )
        cur.execute(
            """
            INSERT INTO fields (doc_id, extraction_id, name, value_raw, value_norm, page_no,
                x0, y0, x1, y1, match_type, match_score, confidence, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                doc_id,
                extraction_id,
                name,
                value_raw,
                value_norm,
                page_no,
                _numeric(bbox.x0) if bbox else None,
                _numeric(bbox.y0) if bbox else None,
                _numeric(bbox.x1) if bbox else None,
                _numeric(bbox.y1) if bbox else None,
                match_type.value,
                match_score,
                confidence.value,
                source.value,
            ),
        )


def save_line_items(
    conn: Connection,
    doc_id: UUID,
    items: Sequence[NormalizedLineItem],
    *,
    source: ValueSource = ValueSource.REVIEWER,
) -> None:
    """Replace the current line-item set with a new reviewed version."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE line_items SET is_current = false WHERE doc_id = %s AND is_current",
            (doc_id,),
        )
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
                    source.value,
                ),
            )


def save_coding_lines(conn: Connection, doc_id: UUID, lines: Sequence[CodingLine]) -> None:
    """Replace the current coding with a new version; the caller chooses the coding_source."""
    with conn.cursor() as cur:
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


def save_findings(conn: Connection, doc_id: UUID, run_id: str, findings: Sequence[Finding]) -> None:
    with conn.cursor() as cur:
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


def add_review(conn: Connection, review: Review) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reviews (doc_id, reviewer, action, field, old_value, new_value,
                comment, created_at)
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


def set_status(
    conn: Connection, doc_id: UUID, status: DocStatus, reason: str | None = None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET status = %s, status_reason = %s, updated_at = now()
            WHERE doc_id = %s
            """,
            (status.value, reason, doc_id),
        )


def log_event(
    conn: Connection,
    actor: str,
    event_type: str,
    doc_id: UUID | None,
    payload: Mapping[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (actor, doc_id, type, payload) VALUES (%s, %s, %s, %s)",
            (actor, doc_id, event_type, Jsonb(dict(payload))),
        )


def now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "add_review",
    "latest_extraction_id",
    "log_event",
    "now",
    "save_coding_lines",
    "save_field_value",
    "save_findings",
    "save_line_items",
    "set_status",
]
