"""Upload invoices to ``data/inbox/`` and get them read.

On the full stack the page asks Airflow to start one ``invoice_intake`` run for the files of
each upload (the DAG also checks the inbox every 5 minutes). Without Airflow (the light
setup: review app plus dev Postgres) the app reads the inbox itself, in the background, as
soon as files are saved.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from app import ui
from app.airflow import AirflowSettings, TriggerResult, trigger_intake
from app.backend import Backend
from app.local_intake import InboxProgress, InboxReader, inbox_reader, summary
from app.upload import SavedUpload, list_inbox, save_upload

_SAVED_KEY = "upload_saved_ids"  # uploads already saved this session; a rerun must not resave
PROGRESS_REFRESH_SECONDS = 2
_TYPES = ["pdf", "png", "jpg", "jpeg", "tif", "tiff", "xml", "xlsx"]


def _upload_id(uploaded, data: bytes) -> str:
    return getattr(uploaded, "file_id", None) or f"{uploaded.name}:{len(data)}"


def _save_new(files, inbox: Path | None) -> tuple[SavedUpload, ...]:
    """Save each upload once. Streamlit keeps files in the box across reruns; saving again
    would put a file back after it was read and moved out, and it would be read twice."""
    seen = tuple(st.session_state.get(_SAVED_KEY, ()))
    saved, ids = [], []
    for uploaded in files:
        data = uploaded.getvalue()
        key = _upload_id(uploaded, data)
        if key in seen or key in ids:
            continue
        saved.append(save_upload(uploaded.name, data, directory=inbox))
        ids.append(key)
    st.session_state[_SAVED_KEY] = (*seen, *ids)
    return tuple(saved)


def _airflow_panel(result: TriggerResult) -> None:
    if result.started:
        st.success(result.message)
        if result.run_id:
            st.caption(f"DAG run `{result.run_id}`")
            st.link_button("Watch this run in Airflow", result.url, key="upload_run_link")
    else:
        st.warning(result.message)


def _open_queue() -> None:
    st.session_state["page"] = "Queue"


def _progress_panel(progress: InboxProgress) -> None:
    if progress.running:
        now = f" · now {progress.current}" if progress.current else ""
        st.info(f"Reading the inbox: {len(progress.done)} done{now}")
        st.caption("The Queue page shows each invoice under “Being read now”.")
    elif progress.error:
        st.error(
            f"Reading stopped: {progress.error}. The file is still in the inbox; "
            "upload again or run `make intake-local` once the cause is fixed."
        )
    elif progress.done:
        st.success(f"Done: {summary(progress)}")
        if st.button("Open the Queue", key="upload_open_queue", on_click=_open_queue):
            st.rerun()


def _waiting_panel(reader: InboxReader, inbox: Path | None) -> None:
    @st.fragment(run_every=PROGRESS_REFRESH_SECONDS)
    def live() -> None:
        progress = reader.progress()
        _progress_panel(progress)
        waiting = len(list_inbox(inbox, limit=1000))
        # Files left from before (e.g. the app was restarted mid-run) get a button.
        idle_with_files = not progress.running and waiting
        if idle_with_files and st.button(
            f"Read the {waiting} waiting file(s)", key="upload_read_waiting"
        ):
            reader.start()
            st.rerun()

    live()


def _inbox_table(inbox: Path | None) -> None:
    items = list_inbox(inbox)
    st.subheader("Waiting in the inbox")
    if not items:
        st.caption("The inbox is empty: every uploaded file has been read.")
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


def render(
    backend: Backend | None = None,
    *,
    inbox: Path | None = None,
    settings: AirflowSettings | None = None,
    client=None,
    reader: InboxReader | None = None,
) -> None:
    del backend  # the upload path stores bytes; the pipeline writes the database
    st.title("Upload")
    st.caption(
        "Files are saved to `data/inbox/` first, then read by the pipeline: by Airflow on the "
        "full stack, or by this app when Airflow is not running."
    )
    ui.show_flash()
    settings = settings or AirflowSettings.from_env()
    reader = reader or inbox_reader()

    files = st.file_uploader(
        "Invoice files", type=_TYPES, accept_multiple_files=True, key="upload_file"
    )
    saved = _save_new(files or (), inbox)
    if saved:
        st.success(
            f"Saved {len(saved)} file{'s' if len(saved) != 1 else ''} to the inbox: "
            + ", ".join(f"`{item.path.name}`" for item in saved)
        )
        if settings.configured:
            files = tuple((item.path.name, item.sha256) for item in saved)
            _airflow_panel(trigger_intake(settings, files=files, client=client))
        else:
            reader.start()  # False when a run is going; that run reads these files too
    elif not files:
        st.info("Choose synthetic invoices. Nothing is uploaded to a remote service.")

    if settings.configured:
        st.divider()
        st.subheader("Airflow")
        st.caption(
            "Airflow reads the inbox: at once when you upload here, and by itself every "
            "5 minutes. Its grid shows every run, one square per invoice."
        )
        st.link_button("Open invoice_intake in Airflow", settings.grid_url)
    else:
        _waiting_panel(reader, inbox)
        st.caption("Airflow is not running in this setup; the app reads the inbox itself.")

    st.divider()
    _inbox_table(inbox)
