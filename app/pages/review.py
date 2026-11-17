"""Review screen: boxes and zoom, findings that lead to their field, the fix panel, the
invoice decision, and editable lines and coding (the panel lives in ``app.fix_panel``)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pandas as pd
import streamlit as st

from app import ui
from app.backend import Backend, CodingUpdate
from app.boxes import crop_region, draw_boxes, page_boxes
from app.cleanup import highlight_cleaned, show_cleanups
from app.fix_panel import (
    FIELD_KEY,
    default_field,
    render_decision,
    render_findings,
    render_fix_panel,
)
from app.formatting import (
    confidence_label,
    format_time,
    parse_decimal,
    source_label,
    status_tone,
)
from app.hidden_text import hidden_markers
from app.models import DocumentBundle
from invoiceflow.contracts import (
    HEADER_FIELDS,
    NormalizedLineItem,
)

_EDITABLE_LINE_COLUMNS = [
    "line_no",
    "description",
    "quantity",
    "unit",
    "days",
    "unit_price",
    "amount",
]


def _field_options(bundle: DocumentBundle) -> list[str]:
    options = [field.name for field in bundle.fields]
    # A finding can point at a value the model did not read (e.g. a missing GST number).
    for finding in bundle.findings:
        if finding.field in HEADER_FIELDS and finding.field not in options:
            options.append(finding.field)
    for index, item in enumerate(bundle.line_items):
        if item.description:
            options.append(f"line_items[{index}].description")
        if item.amount is not None:
            options.append(f"line_items[{index}].amount")
    return options


def _selected_box(boxes, selected: str | None):
    return next((box for box in boxes if box.field == selected), None)


def _draw(bundle: DocumentBundle, selected: str | None) -> None:
    if not bundle.pages:
        st.warning("No page image is stored for this document.")
        return
    page_numbers = [page.page_no for page in bundle.pages]
    page_no = st.selectbox("Page", page_numbers, key="review_page")
    page, words = ui.page_words(bundle, page_no)
    if words is not None:
        boxes = page_boxes(
            words,
            bundle.fields,
            bundle.line_items,
            bundle.findings,
            selected=selected,
        )
    else:
        boxes = ()
    boxes = (*boxes, *hidden_markers(bundle, page_no))
    image = ui.load_image(page.image_path)
    if image is None:
        st.warning(f"No page image at {page.image_path or '—'}")
        return
    st.image(
        draw_boxes(image, boxes, selected=selected),
        caption=f"Page {page_no} — green passed, amber fuzzy, red flagged, blue selected",
        width="stretch",
    )
    box = _selected_box(boxes, selected)
    if box is not None:
        crop = image.crop(crop_region(box.bbox, image.width, image.height))
        st.image(crop, caption=f"Zoom: {box.label}", width=min(560, crop.width))
    elif selected:
        st.caption(f"No box is stored for `{selected}` on page {page_no}.")


def _render_fields(bundle: DocumentBundle) -> None:
    st.subheader("Extracted values")
    if not bundle.fields:
        st.caption("No current fields.")
        return
    # Changes the system made on its own come first, so the reviewer sees them.
    changed = show_cleanups(bundle.fields)
    table = pd.DataFrame(
        [
            {
                "field": field.name,
                "printed": field.value_raw or "—",
                "normalized": field.value_norm or "—",
                "confidence": confidence_label(field.confidence),
                "match": field.match_type.value,
                "source": field.source.value,
            }
            for field in bundle.fields
        ]
    )
    st.dataframe(highlight_cleaned(table, changed), hide_index=True, width="stretch")


def _decimal(value: Any) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return None
    try:
        return parse_decimal(str(value))
    except ValueError:
        return None


def _items_from_frame(frame: pd.DataFrame) -> tuple[NormalizedLineItem, ...]:
    items: list[NormalizedLineItem] = []
    for position, row in frame.iterrows():
        description = row.get("description")
        if pd.isna(description):
            description = None
        if not description and _decimal(row.get("amount")) is None:
            continue
        line_no = int(row.get("line_no") or position + 1)
        items.append(
            NormalizedLineItem(
                line_no=line_no,
                description=str(description) if description else None,
                quantity=_decimal(row.get("quantity")),
                unit=str(row["unit"]) if not pd.isna(row.get("unit")) else None,
                days=_decimal(row.get("days")),
                unit_price=_decimal(row.get("unit_price")),
                amount=_decimal(row.get("amount")),
            )
        )
    return tuple(items)


def _render_line_items(
    backend: Backend, bundle: DocumentBundle, doc_id: UUID, reviewer: str
) -> None:
    st.subheader("Line items")
    frame = pd.DataFrame(
        [
            {
                "line_no": item.line_no,
                "description": item.description,
                "quantity": float(item.quantity) if item.quantity is not None else None,
                "unit": item.unit,
                "days": float(item.days) if item.days is not None else None,
                "unit_price": float(item.unit_price) if item.unit_price is not None else None,
                "amount": float(item.amount) if item.amount is not None else None,
            }
            for item in bundle.line_items
        ],
        columns=_EDITABLE_LINE_COLUMNS,
    )
    edited = st.data_editor(
        frame,
        key="line_items_editor",
        hide_index=True,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "line_no": st.column_config.NumberColumn("Line", min_value=1, step=1, required=True),
            "description": st.column_config.TextColumn("Description", width="large"),
            "quantity": st.column_config.NumberColumn("Qty", format="%.2f"),
            "days": st.column_config.NumberColumn("Days", format="%.2f"),
            "unit_price": st.column_config.NumberColumn("Unit price", format="%.2f"),
            "amount": st.column_config.NumberColumn("Amount", format="%.2f"),
        },
    )
    if st.button("Save line items", key="btn_save_lines"):
        items = _items_from_frame(edited)
        ui.run_action(backend.edit_line_items, doc_id, items, reviewer)


def _coding_frame(bundle: DocumentBundle) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "line_no": line.line_no,
                "gl_account": line.gl_account,
                "cost_center": line.cost_center,
                "tax_code": line.tax_code,
                "rule": source_label(line.coding_source),
                "net": float(line.net_amount),
                "tax": float(line.tax_amount),
            }
            for line in bundle.coding_lines
        ]
    )


def _render_coding(backend: Backend, bundle: DocumentBundle, doc_id: UUID, reviewer: str) -> None:
    st.subheader("Coding")
    if not bundle.coding_lines:
        st.caption("No coding lines.")
        return
    master = backend.master()
    gl_options = [g.code for g in master.coding.gl_accounts if g.active]
    center_options = [c.code for c in master.coding.cost_centers if c.active]
    tax_options = [t.code for t in master.coding.tax_codes]
    frame = _coding_frame(bundle)
    edited = st.data_editor(
        frame,
        key="coding_editor",
        hide_index=True,
        width="stretch",
        disabled=["line_no", "rule", "net", "tax"],
        column_config={
            "gl_account": st.column_config.SelectboxColumn("GL account", options=gl_options),
            "cost_center": st.column_config.SelectboxColumn("Cost center", options=center_options),
            "tax_code": st.column_config.SelectboxColumn("Tax code", options=tax_options),
        },
    )
    if st.button("Save coding", key="btn_save_coding"):
        updates: list[CodingUpdate] = []
        original = {line.line_no: line for line in bundle.coding_lines}
        for _, row in edited.iterrows():
            line_no = int(row["line_no"])
            line = original.get(line_no)
            if line is None:
                continue
            candidate = CodingUpdate(
                line_no=line_no,
                gl_account=row["gl_account"] or None,
                cost_center=row["cost_center"] or None,
                tax_code=row["tax_code"] or None,
            )
            if (
                candidate.gl_account != line.gl_account
                or candidate.cost_center != line.cost_center
                or candidate.tax_code != line.tax_code
            ):
                updates.append(candidate)
        if not updates:
            ui.flash("No coding changes to save.", "info")
            st.rerun()
        ui.run_action(backend.recode, doc_id, updates, reviewer)


def _render_reviews(bundle: DocumentBundle) -> None:
    st.subheader("Review history")
    if not bundle.reviews:
        st.caption("No reviewer actions yet.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "when": format_time(review.created_at),
                    "reviewer": review.reviewer,
                    "action": review.action.value,
                    "field": review.field or "—",
                    "old": review.old_value or "—",
                    "new": review.new_value or "—",
                    "comment": review.comment or "—",
                }
                for review in bundle.reviews
            ]
        ),
        hide_index=True,
        width="stretch",
    )


def render(backend: Backend | None = None) -> None:
    backend = backend or ui.get_backend()
    st.title("Review")
    ui.show_flash()
    # A document the model is still reading has nothing to review yet.
    docs = [doc for doc in backend.list_documents() if not doc.is_processing]
    if not docs:
        st.info("No documents to review. Run `make db-dev && make fixtures`.")
        return
    doc_id = ui.document_picker(docs, key="review_document")
    if doc_id is None:
        return
    bundle = backend.document(doc_id)
    if bundle is None:
        st.error("That document disappeared.")
        return
    doc = bundle.document
    st.markdown(
        f":{status_tone(doc.status)}-badge[{doc.status.value}] "
        f"**{doc.invoice_number or 'no invoice number'}** · "
        f"{doc.vendor_name or doc.supplier_name or 'unknown vendor'}"
    )
    if bundle.extraction and bundle.extraction.replay:
        st.markdown(":violet-badge[Replayed response]")
        st.caption(
            f"mode `{bundle.extraction.mode.value}` · model `{bundle.extraction.model}` · "
            f"extraction `{bundle.extraction.extraction_id}`"
        )
    reviewer = ui.reviewer_name()
    options = _field_options(bundle)
    # Open each invoice on the first field a finding asks a person to look at.
    if st.session_state.get("review_field_doc") != doc_id or (
        st.session_state.get(FIELD_KEY) not in options
    ):
        st.session_state[FIELD_KEY] = default_field(bundle, options)
        st.session_state["review_field_doc"] = doc_id
    selected = st.selectbox(
        "Field to inspect",
        options,
        key=FIELD_KEY,
        help="Choosing a field highlights its box and zooms in on it. "
        "The Fix this field buttons choose a flagged field for you.",
    )

    top = st.columns(4)
    top[0].metric("Total", ui.money_metric(doc.total))
    top[1].metric("Findings", len(bundle.findings))
    top[2].metric("Line items", len(bundle.line_items))
    top[3].metric("Status", doc.status.value)

    left, right = st.columns([1.1, 1])
    with left:
        _draw(bundle, selected)
    with right:
        render_findings(bundle, options, selected)
        render_fix_panel(backend, bundle, selected, reviewer)
        st.divider()
        render_decision(backend, bundle, reviewer)

    st.divider()
    _render_fields(bundle)
    st.divider()
    _render_line_items(backend, bundle, doc_id, reviewer)
    st.divider()
    _render_coding(backend, bundle, doc_id, reviewer)
    st.divider()
    _render_reviews(bundle)
