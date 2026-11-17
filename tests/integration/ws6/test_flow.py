"""Integration: the full stub flow — golden fixture inbox-to-silver and export-once."""

from uuid import UUID

from invoiceflow.contracts import DocStatus
from invoiceflow.pipeline.steps import export_approved
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.fixtures import load_fixtures
from invoiceflow.store.repo import Repo

CLEAN_DOC = UUID("93fe9312-fe79-50bb-b5e7-d18e83dfaff2")
MISMATCH_DOC = UUID("f7d4da3b-2611-5bce-8de5-94b1c185b9ad")


def test_golden_fixtures_reach_silver(migrated, tmp_path):
    store = LocalBlobStore(tmp_path)
    report = load_fixtures(migrated, store)

    assert {d.status for d in report.documents} == {"AUTO_PASSED", "NEEDS_REVIEW"}
    assert {d.doc_id for d in report.documents} == {CLEAN_DOC, MISMATCH_DOC}

    with migrated.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM bronze_files")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM extractions WHERE valid")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM fields")
        assert cur.fetchone()[0] == 42
        cur.execute("SELECT count(*) FROM coding_lines")
        assert cur.fetchone()[0] == 2

    # Silver blobs exist for both documents.
    for doc_id in (CLEAN_DOC, MISMATCH_DOC):
        assert store.read(f"silver/{doc_id}/extraction.json").startswith(b"{")
        assert store.read(f"silver/{doc_id}/page-1.words.json").startswith(b"{")


def test_export_twice_leaves_second_batch_empty(migrated, tmp_path):
    store = LocalBlobStore(tmp_path)
    load_fixtures(migrated, store)
    repo = Repo(migrated)

    # The clean invoice is AUTO_PASSED and joins the export without a person. The twin is
    # approved here without its correction, so the batch checks must keep it out of the CSV.
    repo.set_status(MISMATCH_DOC, DocStatus.APPROVED, "approved for export test")

    first = export_approved(repo=repo, store=store)
    second = export_approved(repo=repo, store=store)

    assert first.batch.row_count == 1
    assert first.doc_ids == (CLEAN_DOC,)
    assert any("expected gross" in problem for problem in first.problems)
    header = store.read(first.batch.csv_path).decode("utf-8").splitlines()[0]
    assert header.startswith('"InvoiceID"')
    assert second.batch.row_count == 0
    assert second.doc_ids == ()
    assert repo.approved_not_exported() == (MISMATCH_DOC,)  # held back, not lost
    assert any("expected gross" in problem for problem in second.problems)

    with migrated.cursor() as cur:
        cur.execute("SELECT count(*) FROM export_batches")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM export_rows")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT status FROM documents WHERE doc_id = %s", (CLEAN_DOC,))
        assert cur.fetchone()[0] == "EXPORTED"
