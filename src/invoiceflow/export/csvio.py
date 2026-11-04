"""CSV writing for the SAP upload: UTF-8, quoted, formula-injection guarded."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from invoiceflow.export.mapping import SapMapping

# Spreadsheet cells that start with these characters are interpreted as formulas by
# Excel/LibreOffice/Google Sheets. Prepending a single quote makes them inert.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize_formula(value: str) -> str:
    """Prefix ``'`` when ``value`` starts with a spreadsheet formula trigger."""
    if value.startswith(_FORMULA_TRIGGERS):
        return "'" + value
    return value


def guard_free_text(mapping: SapMapping, row: tuple[str, ...]) -> tuple[str, ...]:
    """Apply the formula-injection guard to the free-text columns of one row."""
    free = mapping.free_text_names
    return tuple(
        neutralize_formula(cell) if column.name in free else cell
        for column, cell in zip(mapping.columns, row, strict=True)
    )


def to_csv(
    mapping: SapMapping,
    rows: tuple[tuple[str, ...], ...],
) -> str:
    """Render the header plus data rows as a quoted, UTF-8 CSV string."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(
        buffer,
        delimiter=mapping.delimiter,
        quoting=csv.QUOTE_ALL,
        lineterminator="\r\n",
    )
    writer.writerow(mapping.header)
    for row in rows:
        writer.writerow(guard_free_text(mapping, row))
    return buffer.getvalue()


def write_csv(path: Path, mapping: SapMapping, rows: tuple[tuple[str, ...], ...]) -> None:
    """Write the CSV to ``path`` in UTF-8 (no BOM)."""
    path.write_text(to_csv(mapping, rows), encoding=mapping.encoding, newline="")
