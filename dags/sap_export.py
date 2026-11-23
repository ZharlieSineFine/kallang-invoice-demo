"""sap_export: write the SAP CSV for every approved invoice, at 18:00 Singapore time or on demand.

The CSV uses the 16-column layout in ``config/sap_mapping.yaml`` and lands in
``data/gold/<batch_id>/`` with its manifest. It is the same ``export_approved`` that the
review app's "Run the SAP export" button calls. This run sends only invoices not exported
before, so a second run writes zero rows. A person can send an exported invoice again from the
app's "Send again" list (2026-11-20); every send is kept in the batch history.

A scheduled run that starts more than 30 minutes after its 18:00 slot is skipped
(``pipeline.schedule.missed_slot``): Airflow starts the latest missed slot as soon as the stack
comes up, and an export nobody asked for must not happen then. Runs started by hand always run.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import dag, get_current_context, task
from airflow.sdk.exceptions import AirflowSkipException

from invoiceflow.pipeline.schedule import missed_slot
from invoiceflow.settings import company_timezone


@dag(
    dag_id="sap_export",
    schedule="0 18 * * *",
    # Airflow reads "0 18 * * *" in the start date's time zone; with UTC it ran at 02:00 SGT.
    start_date=pendulum.datetime(2026, 1, 1, tz=company_timezone()),
    catchup=False,
    tags=["export", "ws6"],
)
def sap_export():
    @task(task_id="export_approved")
    def export() -> dict[str, str | int]:
        run = get_current_context()["dag_run"]
        # Pass the enum itself: its str() is "DagRunType.SCHEDULED", which never matches.
        if missed_slot(run.run_type, run.run_after, pendulum.now("UTC")):
            slot = pendulum.instance(run.run_after).in_timezone(company_timezone())
            raise AirflowSkipException(
                f"Airflow was not running at {slot:%Y-%m-%d %H:%M} ({company_timezone()}), so "
                "this late export is skipped; nothing was exported. Trigger sap_export by hand, "
                "or use the review app's export button."
            )
        # Imported here, not at the top: Airflow reads this file within 30 s at every start.
        from invoiceflow.pipeline.steps import export_approved
        from invoiceflow.settings import data_dir
        from invoiceflow.storage import LocalBlobStore
        from invoiceflow.store.connection import connect
        from invoiceflow.store.repo import Repo

        store = LocalBlobStore(data_dir())
        with connect() as conn, conn.transaction():
            summary = export_approved(repo=Repo(conn), store=store)
        return {
            "batch_id": summary.batch.batch_id,
            "row_count": summary.batch.row_count,
            "held_back": len(summary.problems),
        }

    export()


sap_export()
