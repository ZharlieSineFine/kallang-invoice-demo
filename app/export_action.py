"""The "Run the SAP export" button, shared by Demo Step 7 and the Batches page.

It runs the same export as the Airflow ``sap_export`` DAG, so the review app alone can
produce the CSV without the full stack.
"""

from __future__ import annotations

import streamlit as st

from app import ui
from app.backend import Backend


def render_export_action(backend: Backend, *, key: str) -> None:
    ready = backend.export_status().get("approved_not_exported", 0)
    if not ready:
        st.caption("Nothing is waiting for export: every passed or approved invoice is in a batch.")
        return
    if st.button(f"Run the SAP export ({ready} ready)", key=key, type="primary"):
        ui.run_action(backend.run_export)
    st.caption(
        "Writes one CSV for SAP with every passed or approved invoice not yet exported. "
        "Each invoice exports once; running it again finds nothing new."
    )
