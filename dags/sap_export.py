"""sap_export: build the (stub) SAP CSV at 18:00 Singapore time, or on demand.

The CSV is one row per coding line for now; WS8 replaces the renderer with the real
16-column ``config/sap_mapping.yaml`` layout. The export-once behaviour is already real:
``record_export`` flips every document to EXPORTED, so the next run writes zero rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

from airflow.sdk import dag, task

from invoiceflow.pipeline.steps import export_approved
from invoiceflow.settings import data_dir
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.connection import connect
from invoiceflow.store.repo import Repo


@dag(
    dag_id="sap_export",
    schedule="0 18 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    tags=["export", "ws6"],
)
def sap_export():
    @task(task_id="export_approved")
    def export() -> dict[str, str | int]:
        store = LocalBlobStore(data_dir())
        with connect() as conn, conn.transaction():
            summary = export_approved(repo=Repo(conn), store=store)
        return {
            "batch_id": summary.batch.batch_id,
            "row_count": summary.batch.row_count,
        }

    export()


sap_export()
