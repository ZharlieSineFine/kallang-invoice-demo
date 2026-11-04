"""evaluate: on-demand report. WS8 replaces the counting stub with accuracy scoring."""

from __future__ import annotations

from datetime import UTC, datetime

from airflow.sdk import dag, task

from invoiceflow.pipeline.steps import evaluate as run_evaluation
from invoiceflow.store.connection import connect
from invoiceflow.store.repo import Repo


@dag(
    dag_id="evaluate",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    tags=["eval", "ws6"],
)
def evaluate():
    @task(task_id="evaluate_statuses")
    def run() -> dict[str, int]:
        with connect() as conn:
            return run_evaluation(repo=Repo(conn))

    run()


evaluate()
