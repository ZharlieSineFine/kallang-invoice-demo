"""Queue: delete one document from its card, or tick several and delete them together. A
dialog asks first and warns when an invoice is already in SAP. Non-invoices are listed under
Discarded, not with the invoices."""

from __future__ import annotations

from dataclasses import replace

from test_pages import _run

from app.pages import queue
from invoiceflow.contracts import DocStatus


def _with_status(backend, bundle, status):
    document = replace(bundle.document, status=status)
    backend.bundles[document.doc_id] = replace(bundle, document=document)
    return document.doc_id


def _buttons(at) -> list[str]:
    return [button.key for button in at.button]


def _boxes(at) -> list[str]:
    return [box.key for box in at.checkbox]


def _deletes(backend) -> list[tuple]:
    return [args for name, args in backend.calls if name == "delete_documents"]


def _notices(at, kind: str) -> str:
    """The pop-up ("popup") or the card next to the buttons ("card")."""
    return "\n".join(m.value for m in at.markdown if f'data-notice="{kind}"' in m.value)


def _texts(at) -> str:
    groups = (at.markdown, at.caption, at.warning, at.success, at.info)
    return "\n".join(item.value for group in groups for item in group)


def test_every_card_has_a_select_box_and_a_delete_button(
    fake_backend, clean_bundle, mismatch_bundle
):
    at = _run(queue, fake_backend)
    for bundle in (clean_bundle, mismatch_bundle):
        doc_id = bundle.document.doc_id
        assert f"queue_delete_{doc_id}" in _buttons(at)
        assert f"queue_pick_{doc_id}" in _boxes(at)


def test_a_document_still_being_read_cannot_be_deleted(fake_backend, clean_bundle):
    doc_id = _with_status(fake_backend, clean_bundle, DocStatus.RECEIVED)
    at = _run(queue, fake_backend)
    assert f"queue_delete_{doc_id}" not in _buttons(at)
    assert f"queue_pick_{doc_id}" not in _boxes(at)


def test_delete_on_a_card_asks_first_then_deletes_only_that_one(
    fake_backend, clean_bundle, mismatch_bundle
):
    doc_id = mismatch_bundle.document.doc_id
    at = _run(queue, fake_backend)
    at.button(key=f"queue_delete_{doc_id}").click().run(timeout=30)
    assert _deletes(fake_backend) == []  # nothing goes before the person confirms
    assert "SAV-2026-0413" in _texts(at)

    at.button(key="queue_delete_confirm").click().run(timeout=30)

    assert _deletes(fake_backend) == [((doc_id,), "demo.reviewer")]
    assert doc_id not in fake_backend.bundles
    assert clean_bundle.document.doc_id in fake_backend.bundles
    assert "Deleted SAV-2026-0413" in _notices(at, "popup")
    card = _notices(at, "card")
    assert "Deleted SAV-2026-0413" in card
    assert 'data-tone="success"' in card
    assert mismatch_bundle.document.vendor_name in card


def test_cancel_deletes_nothing(fake_backend, mismatch_bundle):
    doc_id = mismatch_bundle.document.doc_id
    at = _run(queue, fake_backend)
    at.button(key=f"queue_delete_{doc_id}").click().run(timeout=30)
    at.button(key="queue_delete_cancel").click().run(timeout=30)
    assert _deletes(fake_backend) == []
    assert doc_id in fake_backend.bundles
    assert "queue_delete_confirm" not in _buttons(at)


def test_tick_several_and_delete_them_together(fake_backend, clean_bundle, mismatch_bundle):
    ids = [bundle.document.doc_id for bundle in (clean_bundle, mismatch_bundle)]
    at = _run(queue, fake_backend)
    assert at.button(key="queue_delete_selected_top").disabled  # nothing ticked yet
    for doc_id in ids:
        at.checkbox(key=f"queue_pick_{doc_id}").check()
    at.run(timeout=30)
    assert at.button(key="queue_delete_selected_top").label == "Delete selected (2)"
    assert at.button(key="queue_delete_selected_bottom").label == "Delete selected (2)"

    at.button(key="queue_delete_selected_bottom").click().run(timeout=30)
    at.button(key="queue_delete_confirm").click().run(timeout=30)

    ((deleted, _),) = _deletes(fake_backend)
    assert set(deleted) == set(ids)
    assert fake_backend.bundles == {}


def test_select_all_ticks_every_shown_document(fake_backend, clean_bundle, mismatch_bundle):
    at = _run(queue, fake_backend)
    at.button(key="queue_select_all_top").click().run(timeout=30)
    for bundle in (clean_bundle, mismatch_bundle):
        assert at.checkbox(key=f"queue_pick_{bundle.document.doc_id}").value
    at.button(key="queue_select_none_top").click().run(timeout=30)
    assert at.button(key="queue_delete_selected_top").disabled


def test_an_exported_invoice_can_be_deleted_after_a_warning(fake_backend, clean_bundle):
    doc_id = _with_status(fake_backend, clean_bundle, DocStatus.EXPORTED)
    at = _run(queue, fake_backend)
    at.button(key=f"queue_delete_{doc_id}").click().run(timeout=30)

    warning = " ".join(item.value for item in at.warning)
    assert "already exported to SAP" in warning
    assert "out of step" in warning

    at.button(key="queue_delete_confirm").click().run(timeout=30)
    assert doc_id not in fake_backend.bundles
    card = _notices(at, "card")
    assert "SAP still has it" in card
    assert 'data-tone="warning"' in card


def test_no_sap_warning_for_an_invoice_not_yet_exported(fake_backend, mismatch_bundle):
    at = _run(queue, fake_backend)
    at.button(key=f"queue_delete_{mismatch_bundle.document.doc_id}").click().run(timeout=30)
    assert not any("SAP" in item.value for item in at.warning)


def test_a_non_invoice_is_listed_under_discarded_not_with_the_invoices(fake_backend, clean_bundle):
    doc_id = _with_status(fake_backend, clean_bundle, DocStatus.NOT_INVOICE)
    at = _run(queue, fake_backend)

    assert "Discarded (1)" in [expander.label for expander in at.expander]
    assert f"inbox_open_{doc_id}" not in _buttons(at)  # not in the main grid
    assert DocStatus.NOT_INVOICE not in at.multiselect(key="queue_statuses").options
    number = clean_bundle.document.invoice_number
    assert not any(number in frame.value.to_string() for frame in at.dataframe)
    assert "Not invoices (1)" in _texts(at)
    assert f"queue_delete_{doc_id}" in _buttons(at)
    assert f"queue_pick_{doc_id}" in _boxes(at)
    assert f"queue_copy_review_{doc_id}" in _buttons(at)
