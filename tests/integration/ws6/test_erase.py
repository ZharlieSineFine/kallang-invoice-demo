"""`make erase-live`: remove the live-demo invoices everywhere, keep every other invoice.

The golden clean invoice plays a live-demo invoice; the mismatch twin plays one of the 54."""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from invoiceflow.contracts import DocStatus
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.erase import EraseTarget, apply_erase, plan_erase, remove_files
from invoiceflow.store.fixtures import load_fixtures
from invoiceflow.store.repo import Repo

LIVE = UUID("93fe9312-fe79-50bb-b5e7-d18e83dfaff2")  # golden clean, SAV-2026-0412
KEPT = UUID("f7d4da3b-2611-5bce-8de5-94b1c185b9ad")  # golden mismatch, SAV-2026-0413


def _one(conn, sql, *args):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def _sha(conn, doc_id):
    return _one(
        conn,
        "SELECT b.sha256 FROM bronze_files b JOIN documents d USING (file_id) WHERE d.doc_id = %s",
        doc_id,
    )


@pytest.fixture()
def loaded(migrated, tmp_path):
    store = LocalBlobStore(tmp_path)
    load_fixtures(migrated, store)
    return migrated, store


def _by_file(conn):
    return EraseTarget(sha256s=frozenset({_sha(conn, LIVE)}))


def _children(conn, doc_id):
    tables = ("pages", "extractions", "fields", "line_items", "coding_lines", "findings", "reviews")
    return {
        table: _one(conn, f"SELECT count(*) FROM {table} WHERE doc_id = %s", doc_id)
        for table in tables
    }


def test_the_live_invoice_goes_and_the_other_stays(loaded):
    conn, _ = loaded
    assert any(_children(conn, LIVE).values())
    history = _one(conn, "SELECT count(*) FROM events WHERE doc_id = %s", LIVE)
    before = _children(conn, KEPT)

    plan = plan_erase(conn, _by_file(conn))
    assert plan.doc_ids == (LIVE,)
    apply_erase(conn, plan, actor="test")

    assert _one(conn, "SELECT count(*) FROM documents WHERE doc_id = %s", LIVE) == 0
    assert set(_children(conn, LIVE).values()) == {0}
    assert _one(conn, "SELECT count(*) FROM bronze_files WHERE sha256 = %s", plan.sha256s[0]) == 0
    assert _children(conn, KEPT) == before
    assert _one(conn, "SELECT count(*) FROM documents") == 1
    # The audit log is append-only: the history stays, and the erase is added to it.
    assert _one(conn, "SELECT count(*) FROM events WHERE doc_id = %s", LIVE) == history


def test_the_erase_is_logged_without_a_document(loaded):
    conn, _ = loaded
    apply_erase(conn, plan_erase(conn, _by_file(conn)), actor="test")
    payload = _one(
        conn, "SELECT payload FROM events WHERE type = 'live_demo.erased' AND doc_id IS NULL"
    )
    assert payload["invoice_numbers"] == ["SAV-2026-0412"]


def test_a_matching_invoice_number_is_found_even_from_another_file(loaded):
    conn, _ = loaded
    plan = plan_erase(conn, EraseTarget(invoice_numbers=frozenset({"SAV- 2026-0412"})))
    assert plan.doc_ids == (LIVE,)


def test_nothing_matches_nothing_changes(loaded):
    conn, _ = loaded
    plan = plan_erase(conn, EraseTarget(sha256s=frozenset({"0" * 64})))
    assert plan.doc_ids == ()
    apply_erase(conn, plan, actor="test")
    assert _one(conn, "SELECT count(*) FROM documents") == 2


def _mixed_batch(conn, *, approved: bool):
    repo = Repo(conn)
    if approved:
        conn.execute(
            "INSERT INTO reviews (doc_id, reviewer, action) VALUES (%s, 'someone', 'APPROVE')",
            (KEPT,),
        )
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO export_batches (batch_id, created_at, csv_path, csv_sha256, row_count,
                   total, layout, mapping_version, manifest)
               VALUES ('B-LIVE', now(), 'gold/B-LIVE/B-LIVE.csv', %s, 2, 2354.40, 'hypothetical',
                   '1', '{}')""",
            ("a" * 64,),
        )
        cur.execute(
            "INSERT INTO notifications (kind, message, batch_id) "
            "VALUES ('export', 'done', 'B-LIVE')"
        )
        for row, doc_id in enumerate((LIVE, KEPT), start=1):
            cur.execute(
                "INSERT INTO export_rows (batch_id, doc_id, first_row_no, row_count) "
                "VALUES ('B-LIVE', %s, %s, 1)",
                (doc_id, row),
            )
    for doc_id in (LIVE, KEPT):
        repo.set_status(doc_id, DocStatus.EXPORTED, "exported in B-LIVE")


@pytest.mark.parametrize(("approved", "back_to"), [(False, "AUTO_PASSED"), (True, "APPROVED")])
def test_a_batch_with_a_live_invoice_is_removed_and_the_others_can_export_again(
    loaded, approved, back_to
):
    conn, _ = loaded
    _mixed_batch(conn, approved=approved)

    plan = plan_erase(conn, _by_file(conn))
    assert plan.batch_ids == ("B-LIVE",)
    assert plan.reverted == ((KEPT, DocStatus(back_to)),)
    apply_erase(conn, plan, actor="test")

    assert _one(conn, "SELECT count(*) FROM export_batches") == 0
    assert _one(conn, "SELECT count(*) FROM export_rows") == 0
    assert _one(conn, "SELECT count(*) FROM notifications") == 0
    assert _one(conn, "SELECT status FROM documents WHERE doc_id = %s", KEPT) == back_to
    assert Repo(conn).approved_not_exported() == (KEPT,)


def test_the_files_go_too(loaded, tmp_path):
    conn, store = loaded
    data = store.root
    plan = plan_erase(conn, _by_file(conn))
    for folder in ("silver", "parsed"):
        for doc_id in (LIVE, KEPT):
            (data / folder / str(doc_id)).mkdir(parents=True, exist_ok=True)
            (data / folder / str(doc_id) / "page-1.txt").write_text("x")
    gold = data / "gold" / "B-LIVE"
    gold.mkdir(parents=True)
    (gold / "B-LIVE.csv").write_text("x")
    cache = tmp_path / "cache"
    cache.mkdir()
    for name, doc_id in (("live.json", LIVE), ("kept.json", KEPT)):
        (cache / name).write_text(json.dumps({"result": {"doc_id": str(doc_id)}}))
    inbox = data / "inbox"
    inbox.mkdir()
    live_bytes = (data / plan.bronze_paths[0]).read_bytes()
    (inbox / "upload-copy.pdf").write_bytes(live_bytes)
    (inbox / "someone-else.pdf").write_bytes(b"%PDF other")

    plan = plan.with_batches(("B-LIVE",))
    removed = remove_files(plan, data_root=data, cache_dir=cache)

    assert not (data / plan.bronze_paths[0]).exists()
    assert not (data / "silver" / str(LIVE)).exists()
    assert not (data / "parsed" / str(LIVE)).exists()
    assert (data / "silver" / str(KEPT)).exists()
    assert (data / "parsed" / str(KEPT)).exists()
    assert not gold.exists()
    assert not (cache / "live.json").exists()
    assert (cache / "kept.json").exists()
    assert not (inbox / "upload-copy.pdf").exists()
    assert (inbox / "someone-else.pdf").exists()
    assert len(removed) >= 6


def test_a_rehearsal_erase_keeps_the_recorded_answers(loaded, tmp_path):
    # `make erase-live KEEP_ANSWERS=1`: the invoices go, so they can be uploaded again, but a
    # replay rehearsal still finds their model answers.
    conn, store = loaded
    plan = plan_erase(conn, _by_file(conn))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "live.json").write_text(json.dumps({"result": {"doc_id": str(LIVE)}}))

    remove_files(plan, data_root=store.root, cache_dir=None)

    assert not (store.root / plan.bronze_paths[0]).exists()
    assert (cache / "live.json").exists()


def test_after_an_erase_the_same_file_and_number_are_new_again(loaded):
    conn, _ = loaded
    repo = Repo(conn)
    assert "SAV-2026-0412" in {prior.invoice_number for prior in repo.prior_invoices(None)}
    sha = _sha(conn, LIVE)

    apply_erase(conn, plan_erase(conn, _by_file(conn)), actor="test")

    # Intake would not skip the file as already seen, and R05 has no earlier invoice to match.
    assert repo.unfinished_document(sha) is None
    assert _one(conn, "SELECT count(*) FROM bronze_files WHERE sha256 = %s", sha) == 0
    assert "SAV-2026-0412" not in {prior.invoice_number for prior in repo.prior_invoices(None)}
