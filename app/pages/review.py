"""Review screen: boxes, zoom, corrections, actions, editable lines and coding."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pandas as pd
import streamlit as st
from PIL import Image

from app import ui
from app.backend import Backend, CodingUpdate, subtotal_hint
from app.boxes import crop_region, draw_boxes, load_page_text, page_boxes
from app.formatting import (
    confidence_label,
    format_money,
    parse_decimal,
    source_label,
    status_tone,
)
from app.models import DocumentBundle
from invoiceflow.contracts import (
    DocStatus,
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
    for index, item in enumerate(bundle.line_items):
        if item.description:
            options.append(f"line_items[{index}].description")
        if item.amount is not None:
            options.append(f"line_items[{index}].amount")
    return options


def _load_image(path: str | None) -> Image.Image | None:
    resolved = ui.resolve_path(path)
    if resolved is None or not resolved.is_file():
        return None
    return Image.open(resolved)


def _page_words(bundle: DocumentBundle, page_no: int):
    page = next((p for p in bundle.pages if p.page_no == page_no), None)
    if page is None or not page.words_path:
        return page, None
    try:
        return page, load_page_text(ui.resolve_path(page.words_path) or page.words_path)
    except (OSError, ValueError):
        return page, None


def _selected_box(boxes, selected: str | None):
    return next((box for box in boxes if box.field == selected), None)


def _draw(bundle: DocumentBundle, selected: str | None) -> None:
    if not bundle.pages:
        st.warning("No page image is stored for this document.")
        return
    page_numbers = [page.page_no for page in bundle.pages]
    page_no = st.selectbox("Page", page_numbers, key="review_page")
    page, words = _page_words(bundle, page_no)
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
    image = _load_image(page.image_path)
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


def _render_findings(bundle: DocumentBundle) -> None:
    st.subheader("Open findings")
    if not bundle.findings:
        st.success("No open findings.")
        return
    for finding in bundle.findings:
        field_name = finding.field or "document"
        line = (
            f"**{finding.rule_id}** · {finding.severity.value} · `{field_name}` — {finding.message}"
        )
        if finding.severity.value == "INFO":
            st.info(line)
        else:
            st.error(line)
        if finding.evidence:
            st.caption(" · ".join(f"{k}={v}" for k, v in finding.evidence.items()))


def _render_actions(
    backend: Backend, bundle: DocumentBundle, doc_id: UUID, selected: str | None, reviewer: str
) -> None:
    st.subheader("Actions")
    header_names = {field.name for field in bundle.fields}
    correctable = selected if selected in header_names else None
    current = bundle.field(correctable) if correctable else None

    left, middle, right = st.columns(3)
    if left.button("Confirm field", key="btn_confirm", disabled=correctable is None):
        ui.run_action(backend.confirm, doc_id, correctable, reviewer)
    if middle.button("Approve", key="btn_approve", type="primary"):
        ui.run_action(backend.approve, doc_id, reviewer, st.session_state.get("approve_comment"))
    if right.button("Reject", key="btn_reject"):
        ui.run_action(backend.reject, doc_id, reviewer, st.session_state.get("reject_comment"))

    st.markdown("**Correct a field**")
    if current is None:
        st.caption("Choose a header field above to correct it. Edit line items in the table.")
    else:
        raw = st.text_input(
            "Corrected value",
            value=current.value_raw or "",
            key="correction_value",
            help=f"Stored normalized as {current.value_norm or '—'}",
        )
        if correctable == "subtotal":
            hint = subtotal_hint(bundle)
            if hint is not None:
                st.caption(
                    f"Line items add up to {format_money(hint)}. A subtotal of that amount "
                    "clears R02."
                )
        if st.button("Correct & rerun checks", key="btn_correct"):
            if correctable is None:
                ui.flash("Choose a header field first.", "error")
                st.rerun()
            ui.run_action(backend.correct, doc_id, correctable, raw, reviewer)

    st.markdown("**Release a hold**")
    comment = st.text_area(
        "Release comment (required)",
        key="hold_comment",
        placeholder="Why can this hold be released?",
    )
    if st.button(
        "Release hold",
        key="btn_release",
        disabled=bundle.document.status is not DocStatus.ON_HOLD,
    ):
        ui.run_action(backend.release_hold, doc_id, reviewer, comment)

    with st.expander("Approval comment"):
        st.text_area("Comment", key="approve_comment", placeholder="Optional for approve/reject")


def _render_fields(bundle: DocumentBundle) -> None:
    st.subheader("Extracted values")
    if not bundle.fields:
        st.caption("No current fields.")
        return
    st.dataframe(
        pd.DataFrame(
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
        ),
        hide_index=True,
        width="stretch",
    )


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
                    "when": review.created_at.isoformat(timespec="seconds"),
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
    docs = backend.list_documents()
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
    selected = st.selectbox(
        "Field to inspect",
        _field_options(bundle),
        key="review_field",
        help="Choosing a field highlights its box and zooms in on it.",
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
        _render_findings(bundle)
        _render_actions(backend, bundle, doc_id, selected, reviewer)

    st.divider()
    _render_fields(bundle)
    st.divider()
    _render_line_items(backend, bundle, doc_id, reviewer)
    st.divider()
    _render_coding(backend, bundle, doc_id, reviewer)
    st.divider()
    _render_reviews(bundle)
