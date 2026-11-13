"""invoice_intake: scan ``data/inbox`` every 5 minutes and process one task per document.

Each document is processed inside the one-slot ``llm`` pool (the extraction step is the only
thing that talks to the model), with 2 retries. The pipeline stages are still stubs in Phase
1 — they replay the golden fixtures — but the DAG/storage wiring is the real one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from airflow.sdk import dag, task

from invoiceflow.pipeline.steps import (
    golden_pipeline,
    inbox_dir,
    intake_document,
    list_inbox,
    move_processed,
)
from invoiceflow.settings import data_dir, singapore_today
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.connection import connect
from invoiceflow.store.repo import Repo


@dag(
    dag_id="invoice_intake",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    tags=["intake", "ws6"],
)
def invoice_intake():
    @task(task_id="scan_inbox")
    def scan() -> list[str]:
        return [str(path) for path in list_inbox(inbox_dir())]

    @task(task_id="process_document", pool="llm", retries=2)
    def process(path: str) -> dict[str, str | bool]:
        pipeline = golden_pipeline()
        store = LocalBlobStore(data_dir())
        with connect() as conn, conn.transaction():
            result = intake_document(
                Path(path),
                repo=Repo(conn),
                store=store,
                pipeline=pipeline,
                today=singapore_today(),
                run_id="airflow-intake",
            )
        move_processed(Path(path))
        return {
            "doc_id": str(result.doc_id),
            "status": result.status.value,
            "skipped": result.skipped,
        }

    process.expand(path=scan())


invoice_intake()
