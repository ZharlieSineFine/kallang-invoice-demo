#!/usr/bin/env python
"""`make demo-data`: load the "yesterday" batch through the real pipeline and the live model.

Replaces the master data and every document in the target database, so it refuses to run on a
database that has documents unless ``--reset`` is given. Also runs the live set without saving
it, which records the replay cache for the documents uploaded during the demo.
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
    render_scoreboard,
    require_empty_or_reset,
)
from invoiceflow.pipeline.stages import process_document
from invoiceflow.pipeline.steps import build_pipeline, intake_document
from invoiceflow.settings import data_dir, load_config, repo_root, singapore_today
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.connection import connect, database_url
from invoiceflow.store.fixtures import truncate
from invoiceflow.store.migrate import apply_migrations
from invoiceflow.store.repo import Repo

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
            with connect() as conn, conn.transaction():
                result = intake_document(
                    doc.path,
                    repo=Repo(conn),
                    store=store,
                    pipeline=pipeline,
                    today=today,
                    run_id="demo-data",
                    file_id=doc.file_id,
                    doc_id=doc.doc_id,
                    source="demo-data",
                )
        except (psycopg.Error, ValueError) as error:
            # The document's transaction rolled back; report it and load the rest.
            scores.append(Score(doc.name, "FAILED", doc.expected, ()))
            print(f"{doc.name:<14} FAILED        {type(error).__name__}: {error}", flush=True)
            continue
        if result.skipped:
            scores.append(Score(doc.name, "SKIPPED", doc.expected, (), skipped=True))
        else:
            sample = eval_sample(doc.name, load_truth(doc), result.process)
            samples.append(sample)
            actual = sample.predicted_rules
            scores.append(Score(doc.name, result.status.value, doc.expected, actual))
        print(
            f"{doc.name:<14} {scores[-1].status:<13} {time.monotonic() - started:5.0f}s", flush=True
        )
    return tuple(scores), tuple(samples)


def _record_live_set(docs, pipeline, today) -> None:
    """Rehearse the demo's uploads: records the replay cache and saves nothing."""
    for doc in docs:
        result = process_document(
            doc.path,
            file_id=doc.file_id,
            doc_id=doc.doc_id,
            deps=pipeline.deps,
            master=pipeline.master,
            today=today,
            run_id="demo-data-live",
            rules_config=pipeline.rules_config,
        )
        rules = sorted({finding.rule_id for finding in result.findings})
        print(f"{doc.name:<14} {result.decision.status.value:<13} {rules} (not saved)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="replace existing documents")
    parser.add_argument("--stack", action="store_true", help="target the full stack's database")
    args = parser.parse_args()

    load_config("rules")  # also reads .env, so the environment is ready for the URL below
    if args.stack:
        _use_full_stack_database()
    root = data_dir() / "generated"
    docs = load_manifest(root, "pre")
    live = load_manifest(root, "live")
    pipeline = build_pipeline()
    store = LocalBlobStore(data_dir())
    today = singapore_today()

    _prepare_database(pipeline, reset=args.reset)
    scores, samples = _load_batch(docs, pipeline, store, today)
    _record_live_set(live, pipeline, today)

    report = evaluate(samples, set_name="pre")
    json_path, _ = write_report(report, repo_root() / "reports", for_dashboard=True)
    print(render_scoreboard(scores))
    print(f"accuracy {report.accuracy:.2f}% on {report.samples} documents; wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
