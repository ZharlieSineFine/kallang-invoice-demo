"""The "Run the SAP export" button, shared by Demo Step 7 and the Batches page.

It runs the same export as the Airflow ``sap_export`` DAG, so the review app alone can
produce the CSV without the full stack. It sends every passed or approved invoice not yet
exported. Under "Send again", a person can tick invoices sent before to send them to SAP
again (user's request, 2026-11-20); every send stays in the batch history. The scheduled run
never re-sends, so an invoice only goes twice when a person chooses it.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import streamlit as st

from app import ui
from app.backend import Backend
from app.formatting import format_money
from app.models import ExportedInvoice
from app.notice import Act, export_notice


def _picker_key(key: str) -> str:
    return f"{key}_resend"


def _clear_key(key: str) -> str:
    return f"{key}_resend_clear"


def resend_label(item: ExportedInvoice) -> str:
    parts = [item.label, item.vendor, format_money(item.total) if item.total is not None else None]
    sent = f"sent in {', '.join(item.batches)}"
    return " · ".join([*(part for part in parts if part), sent])


def _resend_picker(history: Sequence[ExportedInvoice], key: str) -> list[UUID]:
    if not history:
        return []
    by_id = {item.doc_id: item for item in history}
    with st.expander(f"Send again ({len(history)} sent before)"):
        st.caption(
            "Tick invoices already sent to SAP to send them again in the next export. "
            "SAP receives them again, so check it will not pay them twice."
        )
        # The list has its own "Select all" option and clear-all x, so no buttons of ours.
        chosen = st.multiselect(
            "Invoices to send again",
            list(by_id),
            format_func=lambda doc_id: resend_label(by_id[doc_id]),
            key=_picker_key(key),
            placeholder="Choose invoices sent before",
        )
    return list(chosen)


def _button_label(ready: int, again: int) -> str:
    parts = [f"{ready} ready"] * bool(ready) + [f"{again} sent again"] * bool(again)
    return f"Run the SAP export ({' + '.join(parts)})"


def render_export_action(backend: Backend, *, key: str) -> None:
    if st.session_state.pop(_clear_key(key), False):
        st.session_state.pop(_picker_key(key), None)  # the last export sent the ticked ones
    ready = backend.export_status().get("approved_not_exported", 0)
    history = backend.export_history()
    top = st.container()  # the button sits above the picker, but needs its count
    again = _resend_picker(history, key)
    with top:
        if not ready and not again:
            note = " Tick any under Send again to send it to SAP again." if history else ""
            st.caption(
                "Nothing is waiting for export: every passed or approved invoice is in a batch."
                + note
            )
            ui.show_result(f"export:{key}")  # right after an export, nothing is left to export
            return
        if st.button(_button_label(ready, len(again)), key=key, type="primary"):
            st.session_state[_clear_key(key)] = True
            act = Act("Exported", "run the SAP export", describe=export_notice)
            ui.run_action(backend.run_export, tuple(again), act=act, at=f"export:{key}")
        st.caption(
            "Writes one CSV for SAP with every passed or approved invoice not yet exported, "
            "plus any ticked under Send again. Every send is kept in the batch history."
        )
        ui.show_result(f"export:{key}")
