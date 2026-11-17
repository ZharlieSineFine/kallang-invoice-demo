#!/usr/bin/env python
"""`make demo-data`: a rehearsal of the recorded demo, run without Airflow.

Every generated document goes through the real pipeline and the live model in the demo's
order: all 57 in ``invoices/`` (the 50 of the recorded full run, the 4 first shown live, then
the 3 over the auto-pass limit), oldest arrival first, exactly as the inbox will take them.
Each result is scored against the answer key, and every model answer is recorded, so
``LLM_MODE=replay`` can repeat the run without the model.

Replaces the master data and every document in the target database, so it refuses to run on a
database that has documents unless ``--reset`` is given.
"""

from __future__ import annotations

import argparse
import os
import time
from urllib.parse import urlsplit, urlunsplit

import psycopg

from invoiceflow.evaluate.cli import write_report
from invoiceflow.evaluate.metrics import evaluate
from invoiceflow.pipeline.demo_data import (
    Score,
    eval_sample,
    load_manifest,
    load_truth,
    not_yet_stored,
    render_scoreboard,
    require_empty_or_reset,
)
from invoiceflow.pipeline.steps import build_pipeline, intake_in_steps
from invoiceflow.settings import data_dir, load_config, repo_root, singapore_today
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.connection import connect, database_url
from invoiceflow.store.fixtures import truncate
from invoiceflow.store.migrate import apply_migrations
from invoiceflow.store.repo import Repo, repo_transaction

STACK_PORT_ENV = "AP_STACK_DB_PORT"
DEFAULT_STACK_PORT = "5434"


def _use_full_stack_database() -> None:
    """Point at the full stack's Postgres, which `make up` publishes on its own port."""
    url = urlsplit(database_url())
    credentials = url.netloc.rpartition("@")[0]
    port = os.environ.get(STACK_PORT_ENV, DEFAULT_STACK_PORT)
    netloc = f"{credentials}@127.0.0.1:{port}"
    os.environ["AP_DATABASE_URL"] = urlunsplit(url._replace(netloc=netloc))


def _prepare_database(pipeline, *, reset: bool) -> None:
    with connect() as conn, conn.transaction():
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM documents")
            count = int(cur.fetchone()[0])
        require_empty_or_reset(document_count=count, reset=reset)
        truncate(conn)
        Repo(conn).save_master(pipeline.master)


def _load_batch(docs, pipeline, store, today):
    scores, samples = [], []
    for doc in docs:
        started = time.monotonic()
        try:
            # Committed in steps, like the DAG, so the Queue shows the invoice being read.
            result = intake_in_steps(
                doc.path,
                transaction=repo_transaction,
                store=store,
                pipeline=pipeline,
                today=today,
                run_id="demo-data",
                file_id=doc.file_id,
                doc_id=doc.doc_id,
                source="demo-data",
            )
        except (psycopg.Error, ValueError, LookupError) as error:
            # LookupError covers a replay cache miss (CacheMiss), e.g. a scan OCR'd by a
            # different Tesseract version on another machine.
            # Nothing of the document is left behind; report it and load the rest.
            scores.append(Score(doc.name, "FAILED", doc.expected, (), folder=doc.folder))
            print(f"{doc.name:<22} FAILED        {type(error).__name__}: {error}", flush=True)
            continue
        if result.skipped:
            scores.append(
                Score(doc.name, "SKIPPED", doc.expected, (), skipped=True, folder=doc.folder)
            )
        else:
            sample = eval_sample(doc.name, load_truth(doc), result.process)
            samples.append(sample)
            actual = sample.predicted_rules
            scores.append(
                Score(doc.name, result.status.value, doc.expected, actual, folder=doc.folder)
            )
        print(
            f"{doc.name:<22} {scores[-1].status:<13} {time.monotonic() - started:5.0f}s", flush=True
        )
    return tuple(scores), tuple(samples)


def _add_new(docs, pipeline, store, today) -> int:
    """`make demo-add`: load only the generated documents not stored yet, keeping everything
    else (reviews, exports, master data). The evaluation report is left alone: it scores the
    whole set, so `make demo-ready` rewrites it."""
    with connect() as conn, conn.transaction():
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT trim(sha256) FROM bronze_files")
            stored = {row[0] for row in cur.fetchall()}
    new = not_yet_stored(docs, stored)
    if not new:
        print("Nothing to add: every generated document is already stored.")
        return 0
    scores, _ = _load_batch(new, pipeline, store, today)
    print(render_scoreboard(scores))
    print("Evaluation report unchanged; `make demo-ready` rescores the whole set.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="replace existing documents")
    parser.add_argument(
        "--add-new",
        action="store_true",
        help="load only the generated documents not stored yet; keep everything else",
    )
    parser.add_argument("--stack", action="store_true", help="target the full stack's database")
    args = parser.parse_args()

    load_config("rules")  # also reads .env, so the environment is ready for the URL below
    if args.stack:
        _use_full_stack_database()
    root = data_dir() / "generated"
    docs = load_manifest(root)
    pipeline = build_pipeline()
    store = LocalBlobStore(data_dir())
    today = singapore_today()

    if args.add_new:
        return _add_new(docs, pipeline, store, today)
    _prepare_database(pipeline, reset=args.reset)
    scores, samples = _load_batch(docs, pipeline, store, today)

    report = evaluate(samples, set_name="demo")
    json_path, _ = write_report(report, repo_root() / "reports", for_dashboard=True)
    print(render_scoreboard(scores))
    print(f"accuracy {report.accuracy:.2f}% on {report.samples} documents; wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
