"""An exported invoice can be sent to SAP again whenever a person asks (user's request,
2026-11-20). Every send is kept: each batch keeps its own row for the invoice. The scheduled
export still sends only invoices not sent before, so nothing goes twice on its own."""

from __future__ import annotations

from uuid import UUID

from invoiceflow.contracts import DocStatus
from invoiceflow.pipeline.steps import export_approved
from invoiceflow.store.delete import apply_delete, plan_delete
from invoiceflow.store.erase import EraseTarget, plan_erase
from invoiceflow.store.repo import Repo

CLEAN = UUID("93fe9312-fe79-50bb-b5e7-d18e83dfaff2")  # AUTO_PASSED, exportable
MISMATCH = UUID("f7d4da3b-2611-5bce-8de5-94b1c185b9ad")  # NEEDS_REVIEW


def _all(conn, sql, *args):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def _sends(conn, doc_id) -> list[str]:
    rows = _all(
        conn,
        "SELECT r.batch_id FROM export_rows r JOIN export_batches b USING (batch_id) "
        "WHERE r.doc_id = %s ORDER BY b.created_at, b.batch_id",
        doc_id,
    )
    return [row[0] for row in rows]


def test_a_resent_invoice_goes_out_again_and_both_sends_are_kept(loaded):
    conn, store = loaded
    repo = Repo(conn)
    first = export_approved(repo=repo, store=store, batch_id="B-1")
    assert first.doc_ids == (CLEAN,)

    again = export_approved(repo=repo, store=store, batch_id="B-2", resend=(CLEAN,))

    assert again.doc_ids == (CLEAN,)
    assert again.resent == (CLEAN,)
    assert again.batch.row_count == first.batch.row_count
    assert _sends(conn, CLEAN) == ["B-1", "B-2"]
    assert _all(conn, "SELECT status FROM documents WHERE doc_id = %s", CLEAN) == [("EXPORTED",)]
    assert "SAV-2026-0412" in store.read(again.batch.csv_path).decode("utf-8")


def test_without_a_resend_the_next_run_sends_only_new_invoices(loaded):
    conn, store = loaded
    repo = Repo(conn)
    export_approved(repo=repo, store=store, batch_id="B-1")
    scheduled = export_approved(repo=repo, store=store, batch_id="B-2")
    assert scheduled.doc_ids == ()
    assert scheduled.resent == ()
    assert _sends(conn, CLEAN) == ["B-1"]


def test_only_an_invoice_sent_before_can_be_sent_again(loaded):
    conn, store = loaded
    run = export_approved(repo=Repo(conn), store=store, batch_id="B-1", resend=(MISMATCH,))
    assert MISMATCH not in run.doc_ids  # it still needs review and was never exported
    assert run.resent == ()


def test_a_resend_named_twice_goes_out_once(loaded):
    conn, store = loaded
    repo = Repo(conn)
    export_approved(repo=repo, store=store, batch_id="B-1")
    run = export_approved(repo=repo, store=store, batch_id="B-2", resend=(CLEAN, CLEAN))
    assert run.doc_ids == (CLEAN,)


def test_a_delete_records_every_batch_the_invoice_went_out_in(loaded):
    conn, store = loaded
    repo = Repo(conn)
    export_approved(repo=repo, store=store, batch_id="B-1")
    export_approved(repo=repo, store=store, batch_id="B-2", resend=(CLEAN,))
    plan = plan_delete(conn, (CLEAN,))
    assert plan[0].export_batch == "B-1, B-2"
    apply_delete(conn, plan, actor="test")
    assert _all(conn, "SELECT count(*) FROM export_rows") == [(0,)]
    assert _all(conn, "SELECT count(*) FROM export_batches") == [(2,)]  # SAP's files stay


def _two_batches(conn):
    """CLEAN and MISMATCH in B-1, then MISMATCH sent again alone in B-2."""
    Repo(conn).set_status(MISMATCH, DocStatus.EXPORTED, "exported")
    with conn.cursor() as cur:
        for batch_id in ("B-1", "B-2"):
            cur.execute(
                "INSERT INTO export_batches (batch_id, created_at, csv_path, csv_sha256, "
                "row_count, total, layout, mapping_version, manifest) VALUES "
                "(%s, now(), 'x.csv', %s, 1, 1, 'hypothetical', '1', '{}')",
                (batch_id, "a" * 64),
            )
        rows = (("B-1", CLEAN, 1), ("B-1", MISMATCH, 2), ("B-2", MISMATCH, 1))
        for batch_id, doc_id, row_no in rows:
            cur.execute(
                "INSERT INTO export_rows (batch_id, doc_id, first_row_no, row_count) "
                "VALUES (%s, %s, %s, 1)",
                (batch_id, doc_id, row_no),
            )


def test_erase_keeps_an_invoice_exported_while_another_batch_still_holds_it(loaded):
    conn, _ = loaded
    _two_batches(conn)
    (sha,) = _all(
        conn,
        "SELECT trim(b.sha256) FROM documents d JOIN bronze_files b USING (file_id) "
        "WHERE d.doc_id = %s",
        CLEAN,
    )[0]
    plan = plan_erase(conn, EraseTarget(sha256s=frozenset({sha})))
    assert plan.batch_ids == ("B-1",)
    assert plan.reverted == ()  # MISMATCH is still in B-2, so it stays exported
