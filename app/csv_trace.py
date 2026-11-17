"""CSV row -> invoice -> page -> the exact box the value came from, with its versions.

Column sources come from ``config/sap_mapping.yaml``. Values SAP needs but the invoice does not
print (GL account, cost center, tax code) are labeled as assigned, never given a made-up box.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd
import streamlit as st

from app import ui
from app.backend import Backend
from app.boxes import BoxSpec, draw_boxes, page_boxes
from app.formatting import source_label
from app.models import BatchSummary, CodingRow, DocumentBundle
from invoiceflow.contracts import PageText
from invoiceflow.settings import load_config

_DEFAULT_COLUMN = "GrossAmount"
LINEAGE_SQL = """SELECT b.batch_id, b.csv_sha256, r.first_row_no, f.name, f.value_raw, f.page_no,
       f.bbox, e.model, e.prompt_version
FROM export_rows r
JOIN export_batches b USING (batch_id)
JOIN fields f ON f.doc_id = r.doc_id AND f.is_current
LEFT JOIN extractions e ON e.extraction_id = f.extraction_id
WHERE r.batch_id = %(batch_id)s AND r.doc_id = %(doc_id)s;"""


@dataclass(frozen=True)
class CsvRow:
    row_no: int
    doc_id: UUID | None
    line_no: int | None
    cells: Mapping[str, str]


@dataclass(frozen=True)
class CellOrigin:
    column: str
    value: str
    kind: str  # page | coding | master | constant | batch | document | unknown
    detail: str
    field: str | None = None
    line_fields: tuple[str, ...] = ()


def _as_uuid(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:
        return None


def _as_int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def invoice_ids(manifest: Mapping[str, Any]) -> dict[str, UUID]:
    """InvoiceID (as printed in the CSV) -> document, from the batch manifest."""
    entries = manifest.get("invoices") or ()
    return {str(entry["invoice_id"]): UUID(str(entry["doc_id"])) for entry in entries}


def _row_document(cells: Mapping[str, str], ids: Mapping[str, UUID]) -> UUID | None:
    # Batches before CR-010 carried the document ID itself in a DocKey column.
    return ids.get(cells.get("InvoiceID") or "") or _as_uuid(cells.get("DocKey"))


def read_csv(path: Path, ids: Mapping[str, UUID] | None = None) -> tuple[CsvRow, ...]:
    ids = ids or {}
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(
            CsvRow(
                row_no=number,
                doc_id=_row_document(cells, ids),
                line_no=_as_int(cells.get("LineNo")),
                cells=cells,
            )
            for number, cells in enumerate(csv.DictReader(handle), start=1)
        )


def column_sources(headers: tuple[str, ...]) -> dict[str, str]:
    columns = load_config("sap_mapping")["columns"]
    known = {column["name"]: column["source"] for column in columns}
    return {header: known[header] for header in headers if header in known}


def _coding_line(bundle: DocumentBundle, line_no: int | None) -> CodingRow | None:
    return next((line for line in bundle.coding_lines if line.line_no == line_no), None)


def _line_fields(bundle: DocumentBundle, line: CodingRow | None, suffix: str) -> tuple[str, ...]:
    if line is None:
        return ()
    wanted = line.source_line_nos or (line.line_no,)
    return tuple(
        f"line_items[{index}].{suffix}"
        for index, item in enumerate(bundle.line_items)
        if item.line_no in wanted
    )


def _coding_origin(
    column: str, value: str, name: str, line: CodingRow | None, bundle: DocumentBundle
) -> CellOrigin:
    if name == "net_amount":
        fields = _line_fields(bundle, line, "amount")
        return CellOrigin(column, value, "page", "Sum of the line amounts", line_fields=fields)
    if name == "description":
        fields = _line_fields(bundle, line, "description")
        return CellOrigin(column, value, "page", "From the line description", line_fields=fields)
    if name == "tax_amount" and len(bundle.coding_lines) == 1:
        return CellOrigin(column, value, "page", "The printed GST amount", field="gst_amount")
    assigned = source_label(line.coding_source) if line is not None else "the coding step"
    return CellOrigin(
        column, value, "coding", f"Assigned by {assigned}; not printed on the invoice."
    )


def trace_cell(
    row: CsvRow, column: str, sources: Mapping[str, str], bundle: DocumentBundle
) -> CellOrigin:
    value = row.cells.get(column) or ""
    source = sources.get(column)
    if source is None:
        return CellOrigin(column, value, "unknown", "This column has no known source.")
    origin, _, name = source.partition(".")
    if source.startswith("const:"):
        return CellOrigin(column, value, "constant", "A fixed value in the SAP mapping.")
    if origin == "invoice":
        return CellOrigin(column, value, "page", f"The printed {name}", field=name)
    if origin == "coding":
        return _coding_origin(column, value, name, _coding_line(bundle, row.line_no), bundle)
    if origin == "vendor":
        return CellOrigin(
            column,
            value,
            "master",
            "From the vendor master, matched on the printed supplier.",
            field="supplier_name",
        )
    if origin == "batch":
        return CellOrigin(column, value, "batch", "Set when the batch was exported.")
    if source == "doc.invoice_id":
        return CellOrigin(
            column,
            value,
            "document",
            "Numbers the invoices 1, 2, 3 in this file; the batch manifest records which "
            "invoice each number is.",
        )
    return CellOrigin(column, value, "document", "The system's document key.")


def origin_boxes(
    origin: CellOrigin, bundle: DocumentBundle, words: PageText
) -> tuple[BoxSpec, ...]:
    targets = {*origin.line_fields, *((origin.field,) if origin.field else ())}
    if not targets:
        return ()
    every = page_boxes(words, bundle.fields, bundle.line_items, bundle.findings)
    return tuple(replace(box, selected=True) for box in every if box.field in targets)


def _boxes_by_page(origin: CellOrigin, bundle: DocumentBundle):
    """The first page that holds the value, else the first page with no box."""
    fallback = None
    for page in bundle.pages:
        _, words = ui.page_words(bundle, page.page_no)
        fallback = fallback or page
        boxes = origin_boxes(origin, bundle, words) if words is not None else ()
        if boxes:
            return page, boxes
    return fallback, ()


def _lineage_html(batch: BatchSummary, row: CsvRow, origin: CellOrigin, bundle, page) -> str:
    extraction = bundle.extraction
    model = (
        f"{extraction.model} · prompt {extraction.prompt_version}"
        if extraction is not None
        else "no model run recorded"
    )
    steps = (
        ("CSV", f"{batch.batch_id}, row {row.row_no}, {origin.column} = {origin.value}"),
        ("File", bundle.document.file_name or "unknown file"),
        ("Page", str(page.page_no) if page is not None else "no stored page"),
        ("Where it came from", origin.detail),
        ("Read by", model),
    )
    rows = "".join(
        f'<div style="margin-bottom:0.3rem;"><span style="color:#5a6068;font-size:0.8rem;">'
        f"{escape(label)}</span><br>{escape(text)}</div>"
        for label, text in steps
    )
    return (
        '<div style="background:#f4f6fb;border-left:4px solid #1565c0;padding:0.6rem 0.9rem;'
        f'border-radius:6px;color:#1f2328;">{rows}</div>'
    )


def _render_origin(batch: BatchSummary, row: CsvRow, column: str, bundle: DocumentBundle) -> None:
    origin = trace_cell(row, column, column_sources(tuple(row.cells)), bundle)
    page, boxes = _boxes_by_page(origin, bundle)
    image = ui.load_image(page.image_path) if page is not None else None
    left, right = st.columns([3, 2])
    with left:
        if image is None:
            st.warning("No page image is stored for this document.")
        else:
            st.image(draw_boxes(image, boxes), width="stretch")
    with right:
        st.markdown(_lineage_html(batch, row, origin, bundle, page), unsafe_allow_html=True)


def _render_technical(batch: BatchSummary) -> None:
    st.code(
        json.dumps(
            {
                "batch_id": batch.batch_id,
                "csv_sha256": batch.csv_sha256,
                "layout": batch.layout,
                "mapping_version": batch.mapping_version,
                "manifest": batch.manifest,
            },
            indent=2,
            sort_keys=True,
        ),
        language="json",
    )
    st.code(LINEAGE_SQL, language="sql")


def _selected_row(rows: tuple[CsvRow, ...], event, preferred: UUID | None) -> CsvRow:
    picked = event.selection.rows if event is not None else []
    if picked:
        return rows[picked[0]]
    return next((row for row in rows if row.doc_id == preferred), rows[0])


def render_csv_trace(
    backend: Backend, batch: BatchSummary, *, key: str, preferred_doc: UUID | None = None
) -> None:
    path = ui.resolve_path(batch.csv_path)
    if path is None or not path.is_file():
        st.warning(f"The CSV for batch {batch.batch_id} is not at {batch.csv_path}.")
        return
    rows = read_csv(path, invoice_ids(batch.manifest))
    if not rows:
        st.caption(f"Batch {batch.batch_id} has no rows.")
        return
    st.caption("Click a row to trace it to the invoice.")
    event = st.dataframe(
        pd.DataFrame([{"row": row.row_no, **row.cells} for row in rows]),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"{key}_rows",
    )
    row = _selected_row(rows, event, preferred_doc)
    headers = list(row.cells)
    default = _DEFAULT_COLUMN if _DEFAULT_COLUMN in headers else headers[0]
    column = st.selectbox("CSV column", headers, index=headers.index(default), key=f"{key}_column")
    bundle = backend.document(row.doc_id) if row.doc_id is not None else None
    if bundle is None:
        st.warning(f"Row {row.row_no} points at a document that is not in the database.")
        return
    _render_origin(batch, row, column, bundle)
    if ui.technical_view():
        _render_technical(batch)
