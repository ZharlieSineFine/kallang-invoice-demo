"""`make intake-local`: process what is waiting in data/inbox into the dev database, the way
the Airflow ``invoice_intake`` DAG does, for when only the review app and the dev Postgres
are running. Uploads from the review app's Upload page land in data/inbox.

New files go to the model (LLM_MODE from .env; replay only works for files it has seen).
"""

from __future__ import annotations

import time
from pathlib import Path

from invoiceflow.pipeline.steps import build_pipeline, drain_inbox, inbox_dir, intake_in_steps
from invoiceflow.settings import data_dir, load_config, singapore_today
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.repo import repo_transaction


def main() -> int:
    load_config("rules")  # also reads .env, so the database URL is ready
    pipeline = build_pipeline()
    store = LocalBlobStore(data_dir())
    today = singapore_today()

    def process(path: Path) -> str:
        started = time.monotonic()
        print(f"{path.name:<40} reading…", flush=True)
        result = intake_in_steps(
            path,
            transaction=repo_transaction,
            store=store,
            pipeline=pipeline,
            today=today,
            run_id="local-intake",
            source="upload",
        )
        outcome = "skipped (seen before)" if result.skipped else result.status.value
        print(f"{path.name:<40} {outcome}  {time.monotonic() - started:.0f}s", flush=True)
        return outcome

    outcomes = drain_inbox(process)
    print(
        f"{len(outcomes)} file(s) processed from {inbox_dir()}"
        if outcomes
        else "The inbox is empty."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
