"""A field's printed value, by name: a header field ("subtotal") or a line-item value
("line_items[0].amount", counted from 0 in the order the lines are stored).

Shared by the Review page's fix panel and the backend's "Correct as printed", so both read
and change the same value.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.formatting import parse_decimal
from app.models import DocumentBundle, LineItemRow
from invoiceflow.contracts import HEADER_FIELDS, NormalizedLineItem

_LINE = re.compile(r"^line_items\[(\d+)\]\.(\w+)$")
NUMERIC_LINE_VALUES = ("quantity", "days", "unit_price", "amount")
TEXT_LINE_VALUES = ("description", "unit")


@dataclass(frozen=True)
class LineField:
    index: int
    attribute: str


def line_field(name: str | None) -> LineField | None:
    match = _LINE.match(name or "")
    return LineField(int(match.group(1)), match.group(2)) if match else None


def _unknown(name: str) -> ValueError:
    return ValueError(f"{name} is not a header field or line-item value on this document")


def printed_value(bundle: DocumentBundle, name: str) -> str:
    """The value as stored now, as text. Raises ``ValueError`` for an unknown field."""
    line = line_field(name)
    if line is None:
        row = bundle.field(name)
        if row is None and name in HEADER_FIELDS:
            return ""  # the model did not read it; the reviewer can type it in
        if row is None:
            raise _unknown(name)
        return row.value_raw or ""
    if line.attribute not in (*NUMERIC_LINE_VALUES, *TEXT_LINE_VALUES):
        raise _unknown(name)
    if not 0 <= line.index < len(bundle.line_items):
        raise _unknown(name)
    value = getattr(bundle.line_items[line.index], line.attribute)
    return "" if value is None else str(value)


def _normalized(row: LineItemRow) -> NormalizedLineItem:
    return NormalizedLineItem(
        line_no=row.line_no,
        description=row.description,
        quantity=row.quantity,
        unit=row.unit,
        days=row.days,
        unit_price=row.unit_price,
        amount=row.amount,
    )


def with_line_value(
    rows: Sequence[LineItemRow], line: LineField, raw: str
) -> tuple[NormalizedLineItem, ...]:
    """Every line as it is, except one value of one line, for ``Backend.edit_line_items``."""
    if line.attribute in NUMERIC_LINE_VALUES:
        value = parse_decimal(raw)
        if value is None:
            raise ValueError(f"{line.attribute} cannot be empty: enter a number")
    elif line.attribute in TEXT_LINE_VALUES:
        value = raw.strip() or None
    else:
        raise ValueError(f"line value {line.attribute!r} cannot be edited here")
    items = [_normalized(row) for row in rows]
    items[line.index] = items[line.index].model_copy(update={line.attribute: value})
    return tuple(items)
