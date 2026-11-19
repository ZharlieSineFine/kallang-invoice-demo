"""Read data/inbox without Airflow: ``make intake-local`` and the review app's Upload page.

The same steps the ``invoice_intake`` DAG runs, committed one stage at a time, so the Queue
shows each invoice while the model reads it. New files go to the model (``LLM_MODE`` from
``.env``; replay only works for files it has seen).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from invoiceflow.pipeline.steps import IntakeResult, build_pipeline, drain_inbox, intake_in_steps
from invoiceflow.settings import data_dir, load_config, singapore_today
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.repo import repo_transaction

RUN_ID = "local-intake"
SOURCE = "upload"


def local_processor() -> Callable[[Path], IntakeResult]:
    """Build the pipeline once; the returned function reads one inbox file into the database."""
    load_config("rules")  # also reads .env, so the database URL and model mode are ready
    pipeline = build_pipeline()
    store = LocalBlobStore(data_dir())
    today = singapore_today()

    def process(path: Path) -> IntakeResult:
        return intake_in_steps(
            path,
            transaction=repo_transaction,
            store=store,
            pipeline=pipeline,
            today=today,
            run_id=RUN_ID,
            source=SOURCE,
        )

    return process


def _emit(event: str, file: str, outcome: str | None = None) -> None:
    print(json.dumps({"event": event, "file": file, "outcome": outcome}), flush=True)


def main() -> int:
    """``python -m invoiceflow.pipeline.local_intake``: read the inbox once, one JSON line per
    step on stdout. The review app runs this as a child process, so PDF rendering (pdfium,
    which is not thread-safe) never shares a process with the app's own page rendering."""
    read = local_processor()

    def process(path: Path) -> None:
        _emit("start", path.name)
        result = read(path)
        _emit("done", path.name, "skipped" if result.skipped else result.status.value)

    drain_inbox(process)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
