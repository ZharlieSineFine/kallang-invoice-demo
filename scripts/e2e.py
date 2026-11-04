#!/usr/bin/env python
"""``make e2e``: golden fixture inbox -> bronze -> silver -> export, in replay mode.

Runs against the dev database inside a transaction that always rolls back, so it verifies
the wiring without changing what the review app sees. The silver/gold blobs it writes under
``data/`` are the demo's synthetic artifacts.
"""

from __future__ import annotations

import shutil
from datetime import date

from invoiceflow.contracts import DocStatus
from invoiceflow.pipeline.golden import load_golden
from invoiceflow.pipeline.steps import (
    export_approved,
    golden_pipeline,
    intake_document,
    move_processed,
)
from invoiceflow.settings import data_dir
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.connection import connect
from invoiceflow.store.fixtures import truncate
from invoiceflow.store.migrate import apply_migrations
from invoiceflow.store.repo import Repo

GOLDEN_TODAY = date(2026, 11, 4)


def main() -> int:
    golden = load_golden()
    fixture = golden.fixtures[0]
    pipeline = golden_pipeline()
    store = LocalBlobStore(data_dir())

    inbox = data_dir() / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    dropped = inbox / f"{fixture.fixture_id}.pdf"
    shutil.copyfile(fixture.pdf_path, dropped)

    try:
        with connect() as conn, conn.transaction(force_rollback=True):
            apply_migrations(conn)
            truncate(conn)
            repo = Repo(conn)
            repo.save_master(pipeline.master)

            result = intake_document(
                dropped,
                repo=repo,
                store=store,
                pipeline=pipeline,
                today=GOLDEN_TODAY,
                run_id="e2e",
            )
            print(f"intake : {fixture.fixture_id} -> {result.status.value}")

            repo.set_status(result.doc_id, DocStatus.APPROVED, "e2e export test")
            first = export_approved(repo=repo, store=store)
            second = export_approved(repo=repo, store=store)
            print(f"export : batch {first.batch.batch_id} rows={first.batch.row_count}")
            print(f"export : batch {second.batch.batch_id} rows={second.batch.row_count}")
    finally:
        move_processed(dropped)

    if result.skipped or result.status is not DocStatus.AUTO_PASSED:
        print("e2e FAILED: the clean fixture did not reach AUTO_PASSED")
        return 1
    if first.batch.row_count != 1 or second.batch.row_count != 0:
        print("e2e FAILED: export-once behaviour is wrong")
        return 1
    print("e2e OK: inbox -> silver, export twice leaves the second batch empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
