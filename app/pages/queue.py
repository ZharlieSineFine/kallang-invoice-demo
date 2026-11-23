"""The document queue: every document, its status, value, and open findings.

The page body refreshes itself every few seconds, so a document the pipeline is reading shows
up as a "Processing…" card and turns into its outcome without a reload. Each finished
document can be deleted, alone or ticked with others (``app.queue_delete``); non-invoices
and discarded copies are listed under Discarded (``app.discarded``), not with the invoices.
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from app import ui
from app.audit import AUDIT_LABEL
from app.backend import Backend
from app.counts import intake_counts, is_invoice
from app.discarded import render_discarded
from app.flow import render_flow_strip
from app.formatting import format_time
from app.inbox import render_grid
from app.queue_delete import RESULT_AT, document_actions, render_confirm, selection_bar
from invoiceflow.contracts import DocStatus

QUEUE_REFRESH_SECONDS = 3

_STATUS_ORDER = [
    DocStatus.NEEDS_REVIEW,
    DocStatus.ON_HOLD,
    DocStatus.MANUAL_ENTRY,
    DocStatus.AUTO_PASSED,
    DocStatus.APPROVED,
    DocStatus.REJECTED,
    DocStatus.EXPORTED,
]


def _frame(docs) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "invoice": doc.invoice_number or "—",
                "vendor": doc.vendor_name or doc.supplier_name or "—",
                "status": doc.status.value,
                "findings": doc.finding_count,
                "worst": doc.highest_severity.value if doc.highest_severity else "—",
                "total": float(doc.total) if doc.total is not None else None,
                "audit": AUDIT_LABEL if doc.is_audit_sample else "",
                "replay": doc.is_replay,
                "received": format_time(doc.received_at) if doc.received_at else "—",
            }
            for doc in docs
        ]
    )


def _open_in_review(doc_id) -> None:
    """Runs before widgets are instantiated, so it may legally flip the page key."""
    st.session_state["selected_doc_id"] = doc_id
    st.session_state["page"] = "Review"


def render(backend: Backend | None = None) -> None:
    backend = backend or ui.get_backend()
    st.title("Queue")
    ui.show_flash()
    # Outside the refreshing part of the page, or a refresh would close the dialog.
    render_confirm(backend, [doc for doc in backend.list_documents() if not doc.is_processing])
    _live_queue(backend)


@st.fragment(run_every=QUEUE_REFRESH_SECONDS)
def _live_queue(backend: Backend) -> None:
    all_docs = backend.list_documents()
    if not all_docs:
        st.info("No documents yet. Upload one, or run `make db-dev && make fixtures`.")
        return

    copies = backend.discarded_copies()
    finished = [doc for doc in all_docs if not doc.is_processing]
    not_invoices = [doc for doc in finished if not is_invoice(doc)]
    render_flow_strip(all_docs, copies=len(copies))
    render_discarded(copies, not_invoices, key="queue_copy", actions=document_actions)
    processing = [doc for doc in all_docs if doc.is_processing]
    if processing:
        st.subheader("Being read now")
        render_grid(processing)
    invoices = [doc for doc in finished if is_invoice(doc)]
    if not invoices:
        ui.show_result(RESULT_AT)
        return
    _finished_queue(invoices, finished, intake_counts(all_docs, len(copies)).invoices)


def _finished_queue(docs, finished, invoice_count: int) -> None:
    options = [status for status in _STATUS_ORDER if any(d.status is status for d in docs)]
    chosen = st.multiselect(
        "Statuses",
        options,
        default=options,
        format_func=lambda status: status.value,
        key="queue_statuses",
    )
    filtered = [doc for doc in docs if doc.status in chosen]

    cols = st.columns(4)
    cols[0].metric("Invoices", invoice_count)  # the same count as the Dashboard
    cols[1].metric("Needs review", sum(d.status is DocStatus.NEEDS_REVIEW for d in docs))
    cols[2].metric("On hold", sum(d.status is DocStatus.ON_HOLD for d in docs))
    cols[3].metric("Approved", sum(d.status is DocStatus.APPROVED for d in docs))

    if not filtered:
        st.info("No documents match those statuses.")
        ui.show_result(RESULT_AT)
        return
    selection_bar(filtered, finished, place="top")
    ui.show_result(RESULT_AT)
    render_grid(filtered, actions=document_actions)
    selection_bar(filtered, finished, place="bottom")
    st.dataframe(_frame(filtered), hide_index=True, width="stretch")

    chosen_doc = ui.document_picker(filtered, key="queue_document")
    if chosen_doc is None:
        return
    doc = next(item for item in filtered if item.doc_id == chosen_doc)
    left, right = st.columns([2, 1])
    with left:
        st.subheader(doc.invoice_number or "No invoice number")
        st.write(
            f"**Vendor:** {doc.vendor_name or doc.supplier_name or '—'}  \n"
            f"**Status:** `{doc.status.value}`  \n"
            f"**Findings:** {doc.finding_count}  \n"
            f"**Total:** {ui.money_metric(doc.total)}"
        )
        if doc.status_reason:
            st.markdown(
                f'<div style="color:rgba(49,51,63,0.65);font-size:0.85rem;">'
                f"{escape(doc.status_reason)}</div>",
                unsafe_allow_html=True,
            )
    with right:
        if st.button(
            "Open in Review",
            key="queue_open",
            type="primary",
            on_click=_open_in_review,
            args=(doc.doc_id,),
        ):
            st.rerun()
