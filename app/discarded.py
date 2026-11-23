"""The Queue's Discarded list: what came in but goes no further (user's request, 2026-11-20).

Two kinds: byte-identical copies of a file already in (intake keeps only the original), and
documents the model read as something other than an invoice, such as a statement of account.
A non-invoice is listed here instead of with the invoices, with Open in Review to see its
page. On the Queue it also has the same Select box and Delete button as an invoice card.
Demo Step 1 shows the same list, without those, so both pages show the same documents.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import streamlit as st

from app.duplicates import open_review, render_copies
from app.formatting import format_time, md_escape
from app.inbox import inbox_card, load_type_labels
from app.models import DiscardedCopy, DocumentSummary


def render_discarded(
    copies: Sequence[DiscardedCopy],
    not_invoices: Sequence[DocumentSummary],
    *,
    key: str,
    actions: Callable[[DocumentSummary], None] | None = None,
) -> None:
    total = len(copies) + len(not_invoices)
    if not total:
        return
    with st.expander(f"Discarded ({total})"):
        if copies:
            st.markdown(f"**Copies of a file already in ({len(copies)})**")
            render_copies(copies, key=key)
        if copies and not_invoices:
            st.divider()
        if not_invoices:
            st.markdown(f"**Not invoices ({len(not_invoices)})**")
            st.caption(
                "The model read these as something other than an invoice, such as a statement "
                "of account. They are kept for the record and never sent for payment."
            )
            labels = load_type_labels()
            for doc in not_invoices:
                _not_invoice_row(doc, inbox_card(doc, labels).type_label, key, actions)


def _not_invoice_row(
    doc: DocumentSummary,
    read_as: str,
    key: str,
    actions: Callable[[DocumentSummary], None] | None,
) -> None:
    name = doc.file_name or doc.invoice_number or "Unnamed file"
    arrived = format_time(doc.received_at) if doc.received_at else "—"
    about, review, rest = st.columns([3, 1.2, 2])
    about.markdown(
        f"**{md_escape(name)}**  \nRead as: {md_escape(read_as)} · arrived {md_escape(arrived)}"
    )
    if review.button(
        "Open in Review",
        key=f"{key}_review_{doc.doc_id}",
        on_click=open_review,
        args=(doc.doc_id,),
        width="stretch",
    ):
        st.rerun()
    if actions is not None:
        with rest:
            actions(doc)
