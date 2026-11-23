"""Deleting chosen documents from the Queue: the rows and files go, the log keeps a trace.

Unlike `make erase-live`, an exported invoice's SAP batch and the other invoices in it stay:
SAP already has them, so exporting them again would send them twice."""

from __future__ import annotations

import json
from uuid import UUID

from test_erase import KEPT, LIVE, _children, _mixed_batch, _one

from invoiceflow.contracts import DocStatus
from invoiceflow.store.delete import apply_delete, plan_delete, remove_deleted_files


def _deleted_events(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT actor, doc_id, payload FROM events WHERE type = 'document.deleted' "
            "ORDER BY event_id"
        )
        return cur.fetchall()


def test_the_chosen_document_goes_and_the_other_stays(loaded):
    conn, _ = loaded
    plan = plan_delete(conn, (LIVE,))
    assert [item.doc_id for item in plan] == [LIVE]

    apply_delete(conn, plan, actor="queue.reviewer")

    assert _one(conn, "SELECT count(*) FROM documents WHERE doc_id = %s", LIVE) == 0
    assert set(_children(conn, LIVE).values()) == {0}
    assert _one(conn, "SELECT count(*) FROM documents WHERE doc_id = %s", KEPT) == 1
    assert _one(conn, "SELECT count(*) FROM bronze_files") == 1


def test_the_delete_is_logged_with_what_was_deleted(loaded):
    conn, _ = loaded
    plan = plan_delete(conn, (LIVE,))
    apply_delete(conn, plan, actor="queue.reviewer")

    ((actor, doc_id, payload),) = _deleted_events(conn)
    assert actor == "queue.reviewer"
    assert doc_id == LIVE  # the log has no link to documents, so the trace outlives the row
    assert payload["invoice_number"] == "SAV-2026-0412"
    assert payload["sha256"] == plan[0].sha256
    assert payload["status"] == plan[0].status.value
    assert payload["export_batch"] is None


def test_an_exported_invoice_goes_but_its_sap_batch_and_the_others_stay(loaded):
    conn, _ = loaded
    _mixed_batch(conn, approved=False)
    plan = plan_delete(conn, (LIVE,))
    assert plan[0].export_batch == "B-LIVE"
    assert plan[0].status is DocStatus.EXPORTED

    apply_delete(conn, plan, actor="queue.reviewer")

    assert _one(conn, "SELECT count(*) FROM export_batches") == 1
    assert _one(conn, "SELECT count(*) FROM notifications") == 1
    assert _one(conn, "SELECT count(*) FROM export_rows") == 1  # KEPT's row only
    assert _one(conn, "SELECT status FROM documents WHERE doc_id = %s", KEPT) == "EXPORTED"
    ((_, _, payload),) = _deleted_events(conn)
    assert payload["export_batch"] == "B-LIVE"


def test_the_files_go_but_the_sap_file_stays(loaded, tmp_path):
    conn, store = loaded
    _mixed_batch(conn, approved=False)
    data = store.root
    plan = plan_delete(conn, (LIVE,))
    for folder in ("silver", "parsed"):
        for doc_id in (LIVE, KEPT):
            (data / folder / str(doc_id)).mkdir(parents=True, exist_ok=True)
    gold = data / "gold" / "B-LIVE"
    gold.mkdir(parents=True)
    (gold / "B-LIVE.csv").write_text("x")
    cache = tmp_path / "cache"
    cache.mkdir()
    for name, doc_id in (("live.json", LIVE), ("kept.json", KEPT)):
        (cache / name).write_text(json.dumps({"result": {"doc_id": str(doc_id)}}))
    apply_delete(conn, plan, actor="queue.reviewer")

    remove_deleted_files(plan, data_root=data, cache_dir=cache)

    assert not (data / plan[0].path).exists()
    assert not (data / "silver" / str(LIVE)).exists()
    assert not (data / "parsed" / str(LIVE)).exists()
    assert (data / "silver" / str(KEPT)).exists()
    assert (gold / "B-LIVE.csv").exists()
    assert not (cache / "live.json").exists()
    assert (cache / "kept.json").exists()


def test_unknown_ids_delete_nothing(loaded):
    conn, _ = loaded
    plan = plan_delete(conn, (UUID(int=1),))
    assert plan == ()
    apply_delete(conn, plan, actor="queue.reviewer")
    assert _one(conn, "SELECT count(*) FROM documents") == 2
    assert _deleted_events(conn) == []
