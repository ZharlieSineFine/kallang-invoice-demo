"""Coding lines follow a reviewer's corrections.

Intake codes an invoice from its line items and printed GST. When a reviewer corrects a line
amount or a header value, the backend reruns the same coding function on the corrected
values. A reviewer's own GL account, cost center, or tax code stays (matched by the invoice
lines it covers); only the amounts are recomputed.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models import CodingRow
from invoiceflow.contracts import CodingLine, CodingSource


def _key(line: CodingLine | CodingRow) -> tuple:
    return (
        line.gl_account,
        line.cost_center,
        line.tax_code,
        line.net_amount,
        line.tax_amount,
        tuple(line.source_line_nos),
    )


def coding_changed(fresh: Sequence[CodingLine], current: Sequence[CodingRow]) -> bool:
    return [_key(line) for line in fresh] != [_key(row) for row in current]


def keep_reviewer_choices(
    fresh: Sequence[CodingLine], current: Sequence[CodingRow]
) -> tuple[CodingLine, ...]:
    chosen = {
        tuple(row.source_line_nos): row
        for row in current
        if row.coding_source is CodingSource.REVIEWER
    }

    def merged(line: CodingLine) -> CodingLine:
        row = chosen.get(tuple(line.source_line_nos))
        if row is None:
            return line
        return line.model_copy(
            update={
                "gl_account": row.gl_account,
                "cost_center": row.cost_center,
                "tax_code": row.tax_code,
                "description": row.description,
                "coding_source": CodingSource.REVIEWER,
            }
        )

    return tuple(merged(line) for line in fresh)
