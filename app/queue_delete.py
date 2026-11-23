"""Deleting documents from the Queue (user's request, 2026-11-20).

Every finished document has a Select box and a Delete button, on its card or on its row in
the Discarded list. A bar above and below the cards deletes the ticked ones together. Either
way a dialog asks first, names each document, and warns when one is already in SAP: SAP
keeps it, so the two no longer match. A document still being read has neither control.

The Queue refreshes itself every few seconds, so the dialog is opened outside that part of
the page (``render_confirm``); a refresh would otherwise close it.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import streamlit as st

from app import ui
from app.backend import Backend
from app.formatting import md_escape
from app.models import DocumentSummary
from app.notice import Act, delete_notice, failed_notice
from invoiceflow.contracts import DocStatus

PENDING = "queue_delete_pending"  # the doc IDs the dialog is asking about
RESULT_AT = "queue_delete"  # the result shows under the bar above the cards
DEFAULT_REVIEWER = "demo.reviewer"


def pick_key(doc_id: UUID) -> str:
    return f"queue_pick_{doc_id}"


def label(doc: DocumentSummary) -> str:
    return doc.invoice_number or doc.file_name or "a document with no invoice number"


def picked_ids(docs: Sequence[DocumentSummary]) -> tuple[UUID, ...]:
    return tuple(doc.doc_id for doc in docs if st.session_state.get(pick_key(doc.doc_id)))


def sap_warning(exported: Sequence[DocumentSummary], total: int) -> str:
    names = ", ".join(label(doc) for doc in exported)
    if len(exported) == 1 and total == 1:
        lead, pronoun = f"{names} was already exported to SAP.", "it"
    else:
        lead, pronoun = f"{len(exported)} of these were already exported to SAP: {names}.", "them"
    return (
        f"{lead} Deleting {pronoun} here does not take {pronoun} out of SAP, so SAP and this "
        f"system will be out of step: SAP still has {pronoun} and may pay {pronoun}, but this "
        "system will no longer know about it. The same invoice uploaded again would be read "
        "as new, so it could be exported and paid twice. The SAP batch file and the other "
        "invoices in that batch are kept."
    )


def document_actions(doc: DocumentSummary) -> None:
    """One document's Select box and Delete button, side by side."""
    if doc.is_processing:
        return
    pick, delete = st.columns(2)
    pick.checkbox("Select", key=pick_key(doc.doc_id))
    if delete.button(
        "Delete",
        key=f"queue_delete_{doc.doc_id}",
        on_click=_ask,
        args=((doc.doc_id,),),
        width="stretch",
    ):
        st.rerun()  # the whole page, so the dialog opens


def selection_bar(
    shown: Sequence[DocumentSummary], finished: Sequence[DocumentSummary], *, place: str
) -> None:
    """Select every shown document, clear the ticks, or delete the ticked ones together."""
    chosen = picked_ids(finished)
    select_all, clear, delete = st.columns([1, 1, 1.2])
    select_all.button(
        "Select all shown",
        key=f"queue_select_all_{place}",
        on_click=_set_picks,
        args=(tuple(doc.doc_id for doc in shown), True),
        width="stretch",
    )
    clear.button(
        "Clear selection",
        key=f"queue_select_none_{place}",
        on_click=_set_picks,
        args=(tuple(doc.doc_id for doc in finished), False),
        disabled=not chosen,
        width="stretch",
    )
    if delete.button(
        f"Delete selected ({len(chosen)})",
        key=f"queue_delete_selected_{place}",
        on_click=_ask,
        args=(chosen,),
        disabled=not chosen,
        width="stretch",
    ):
        st.rerun()


def render_confirm(backend: Backend, docs: Sequence[DocumentSummary]) -> None:
    """Open the dialog while a delete waits for an answer. Call it outside the fragment."""
    pending = st.session_state.get(PENDING)
    if not pending:
        return
    by_id = {doc.doc_id: doc for doc in docs}
    chosen = tuple(by_id[doc_id] for doc_id in pending if doc_id in by_id)
    if not chosen:  # deleted or being read again since the button was pressed
        st.session_state.pop(PENDING, None)
        return
    _confirm(backend, chosen)


def _ask(doc_ids: Sequence[UUID]) -> None:
    st.session_state[PENDING] = tuple(doc_ids)


def _dismiss() -> None:
    st.session_state.pop(PENDING, None)


def _set_picks(doc_ids: Sequence[UUID], value: bool) -> None:
    for doc_id in doc_ids:
        st.session_state[pick_key(doc_id)] = value


def _delete(backend: Backend, docs: Sequence[DocumentSummary], reviewer: str) -> None:
    _dismiss()
    doc_ids = tuple(doc.doc_id for doc in docs)
    try:
        outcome = backend.delete_documents(doc_ids, reviewer)
    except (ValueError, LookupError) as exc:
        one = docs[0] if len(docs) == 1 else None
        tried = "delete" if one else f"delete {len(docs)} documents"
        ui.flash(failed_notice(Act("Deleted", tried, doc=one), exc), at=RESULT_AT)
        return
    for doc_id in doc_ids:
        st.session_state.pop(pick_key(doc_id), None)
    ui.flash(delete_notice(outcome, docs, by=reviewer), at=RESULT_AT)


@st.dialog("Delete documents", on_dismiss=_dismiss)
def _confirm(backend: Backend, docs: Sequence[DocumentSummary]) -> None:
    title = label(docs[0]) if len(docs) == 1 else f"these {len(docs)} documents"
    st.markdown(f"**Delete {md_escape(title)} for good?**")
    for doc in docs:
        vendor = doc.vendor_name or doc.supplier_name or doc.file_name or "unknown vendor"
        st.markdown(f"- {md_escape(label(doc))} · {md_escape(vendor)} · {doc.status.value}")
    st.caption(
        "Each goes from the database, with its stored file and its recorded model answer. "
        "If the same file is uploaded again, it is read as new. The history keeps a record "
        "of the delete under your name."
    )
    exported = [doc for doc in docs if doc.status is DocStatus.EXPORTED]
    if exported:
        st.warning(sap_warning(exported, len(docs)))
    reviewer = st.session_state.get("reviewer_name") or DEFAULT_REVIEWER
    st.caption(f"Recorded as {reviewer}.")
    confirm, cancel = st.columns(2)
    if confirm.button(
        "Delete" if len(docs) == 1 else f"Delete {len(docs)}",
        key="queue_delete_confirm",
        type="primary",
        on_click=_delete,
        args=(backend, tuple(docs), reviewer),
        width="stretch",
    ):
        st.rerun()
    if cancel.button("Cancel", key="queue_delete_cancel", on_click=_dismiss, width="stretch"):
        st.rerun()
