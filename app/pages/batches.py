"""Batches: the SAP export batches and what is approved but not yet exported."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import ui
from app.backend import Backend


def render(backend: Backend | None = None) -> None:
    backend = backend or ui.get_backend()
    st.title("Batches")
    ui.show_flash()
    status = backend.export_status()
    batches = backend.batches()

    cols = st.columns(3)
    cols[0].metric("Batches", len(batches))
    cols[1].metric("Exported invoices", status.get("exported", 0))
    cols[2].metric("Approved, not exported", status.get("approved_not_exported", 0))

    if not batches:
        st.info("No export batches yet. Approve an invoice and run `make export` (WS6/WS8).")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "batch": batch.batch_id,
                    "created": batch.created_at.isoformat(timespec="seconds"),
                    "rows": batch.row_count,
                    "total": float(batch.total),
                    "layout": batch.layout,
                    "mapping": batch.mapping_version,
                    "csv": batch.csv_path,
                }
                for batch in batches
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    for batch in batches:
        with st.expander(f"Batch {batch.batch_id}"):
            st.write(f"**CSV:** `{batch.csv_path}`")
            st.write(f"**Rows:** {batch.row_count} · **Total:** S${batch.total:,.2f}")
            if batch.doc_ids:
                st.write("**Documents:**")
                for doc_id in batch.doc_ids:
                    st.code(str(doc_id))
            else:
                st.caption("No document rows in this batch.")
