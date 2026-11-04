"""Upload a file to ``data/inbox/`` and start ``invoice_intake`` when Airflow answers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from app import ui
from app.airflow import AirflowSettings, TriggerResult, trigger_intake
from app.backend import Backend
from app.upload import SavedUpload, list_inbox, save_upload


def _saved_panel(saved: SavedUpload, result: TriggerResult) -> None:
    st.success(f"Saved `{saved.path.name}` ({saved.size_bytes:,} bytes) to the inbox.")
    st.caption(f"SHA-256 `{saved.sha256}`")
    if result.started:
        st.success(result.message)
        if result.run_id:
            st.caption(f"DAG run `{result.run_id}`")
    else:
        st.warning(result.message)
    st.link_button("Open invoice_intake in Airflow", result.url)


def render(
    backend: Backend | None = None,
    *,
    inbox: Path | None = None,
    settings: AirflowSettings | None = None,
    client=None,
) -> None:
    del backend  # the upload path stores bytes; the pipeline writes the database later
    st.title("Upload")
    st.caption(
        "A file is saved to `data/inbox/` first. The page then asks Airflow to start "
        "`invoice_intake`; if the REST login is not available it shows the link instead."
    )
    ui.show_flash()
    settings = settings or AirflowSettings.from_env()

    uploaded = st.file_uploader(
        "Invoice file",
        type=["pdf", "png", "jpg", "jpeg", "tif", "tiff", "xml", "xlsx"],
        key="upload_file",
    )
    if uploaded is not None:
        saved = save_upload(uploaded.name, uploaded.getvalue(), directory=inbox)
        result = trigger_intake(
            settings,
            filename=uploaded.name,
            sha256=saved.sha256,
            client=client,
        )
        _saved_panel(saved, result)
    else:
        st.info("Choose a synthetic invoice. Nothing is uploaded to a remote service.")

    st.divider()
    st.subheader("Airflow")
    st.caption(
        "The trigger reads `AIRFLOW_BASE_URL`, `AIRFLOW_DAG_ID`, and the optional basic-auth "
        "or bearer-token variables from the environment. No secret is stored in the app."
    )
    st.link_button("Open the invoice_intake grid", settings.grid_url)
    if not settings.configured:
        st.caption("Airflow is not configured; the link above is the fallback.")

    items = list_inbox(inbox)
    st.subheader("Recent inbox files")
    if not items:
        st.caption("The inbox is empty.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "file": item.name,
                    "bytes": item.size_bytes,
                    "modified": item.modified_at.isoformat(timespec="seconds"),
                }
                for item in items
            ]
        ),
        hide_index=True,
        width="stretch",
    )
