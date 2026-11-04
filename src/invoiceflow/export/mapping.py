"""SAP upload mapping engine (``config/sap_mapping.yaml``).

Each column names a ``source`` that is resolved against one document's header, vendor,
and one coding line. The engine handles constants, header/coding-line fields, templates,
``max_len`` truncation, and the configured ``date_format``. It writes one row per coding
line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from invoiceflow.contracts import CodingLine, NormalizedInvoice, Vendor

_TEMPLATE_FIELD = re.compile(r"\{([^}]+)\}")


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    source: str
    required: bool = False
    max_len: int | None = None
    format: str | None = None
    free_text: bool = False


@dataclass(frozen=True)
class SapMapping:
    layout: str
    row_per: str
    delimiter: str
    encoding: str
    date_format: str
    version: str
    columns: tuple[ColumnSpec, ...]

    @property
    def header(self) -> tuple[str, ...]:
        return tuple(col.name for col in self.columns)

    @property
    def free_text_names(self) -> frozenset[str]:
        return frozenset(col.name for col in self.columns if col.free_text)


@dataclass(frozen=True)
class RowContext:
    """Everything one export row can reference."""

    doc_id: UUID
    vendor: Vendor
    invoice: NormalizedInvoice
    coding_line: CodingLine
    export_date: date


def load_sap_mapping(config: dict[str, Any]) -> SapMapping:
    """Build a :class:`SapMapping` from the parsed YAML document."""
    return SapMapping(
        layout=str(config["layout"]),
        row_per=str(config.get("row_per", "coding_line")),
        delimiter=str(config.get("delimiter", ",")),
        encoding=str(config.get("encoding", "utf-8")),
        date_format=str(config.get("date_format", "%d.%m.%Y")),
        version=str(config.get("version", "1")),
        columns=tuple(
            ColumnSpec(
                name=str(col["name"]),
                source=str(col["source"]),
                required=bool(col.get("required", False)),
                max_len=col.get("max_len"),
                format=col.get("format"),
                free_text=bool(col.get("free_text", False)),
            )
            for col in config["columns"]
        ),
    )


def _doc_field(ctx: RowContext, field: str) -> Any:
    if field == "doc_id":
        return ctx.doc_id
    raise KeyError(field)


def _batch_field(ctx: RowContext, field: str) -> Any:
    if field == "export_date":
        return ctx.export_date
    raise KeyError(field)


def _lookup(path: str, ctx: RowContext) -> Any:
    """Resolve a dotted source path such as ``coding.net_amount``."""
    prefix, separator, field = path.partition(".")
    if not separator:
        raise ValueError(f"source path needs a section: {path!r}")
    if prefix == "doc":
        return _doc_field(ctx, field)
    if prefix == "vendor":
        return getattr(ctx.vendor, field)
    if prefix == "invoice":
        return getattr(ctx.invoice, field)
    if prefix == "coding":
        return getattr(ctx.coding_line, field)
    if prefix == "batch":
        return _batch_field(ctx, field)
    raise ValueError(f"unknown source section {prefix!r} in {path!r}")


def resolve_value(source: str, ctx: RowContext) -> Any:
    """Resolve one ``source`` string (``const:``, a path, or a ``template:``)."""
    kind, separator, rest = source.partition(":")
    if not separator:
        return _lookup(source, ctx)
    if kind == "const":
        return rest
    if kind == "template":
        return _render_template(rest, ctx)
    return _lookup(source, ctx)


def _render_template(template: str, ctx: RowContext) -> str:
    def replace(match: re.Match[str]) -> str:
        value = _lookup(match.group(1), ctx)
        return format_cell_value(value, "%d.%m.%Y")

    return _TEMPLATE_FIELD.sub(replace, template)


def format_cell_value(value: Any, date_format: str) -> str:
    """Turn a resolved value into the string that lands in the CSV cell."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime(date_format)
    if isinstance(value, date):
        return value.strftime(date_format)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def map_row(mapping: SapMapping, ctx: RowContext) -> tuple[str, ...]:
    """Produce the formatted, truncated cells for one coding line."""
    cells: list[str] = []
    for column in mapping.columns:
        value = resolve_value(column.source, ctx)
        cell = format_cell_value(value, mapping.date_format)
        if column.max_len is not None and len(cell) > column.max_len:
            cell = cell[: column.max_len]
        cells.append(cell)
    return tuple(cells)


def empty_required(mapping: SapMapping, row: tuple[str, ...]) -> tuple[str, ...]:
    """Names of required columns whose cell is empty in ``row``."""
    return tuple(
        column.name
        for column, cell in zip(mapping.columns, row, strict=True)
        if column.required and not cell
    )
