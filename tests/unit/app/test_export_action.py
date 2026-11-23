"""The "Run the SAP export" button on Demo Step 7 and the Batches page."""

from __future__ import annotations

from test_pages import _run
from test_story import _advance

from app.pages import batches, story

EXPORT_STEP = 6  # Step 7 of 8


def _texts(at) -> str:
    groups = (at.markdown, at.caption, at.info, at.success, at.warning)
    return "\n".join(item.value for group in groups for item in group)


def _no_batches(backend, ready: int):
    backend.batches = lambda: ()
    backend.ready = ready
    return backend


def test_step_7_offers_the_export_when_invoices_are_ready(fake_backend):
    at = _run(story, _no_batches(fake_backend, 33))
    _advance(at, EXPORT_STEP)
    button = at.button(key="story_run_export")
    assert button.label == "Run the SAP export (33 ready)"
    assert "passed or approved" in _texts(at)


def test_clicking_the_button_runs_the_export_and_says_what_it_wrote(fake_backend):
    at = _run(story, _no_batches(fake_backend, 33))
    _advance(at, EXPORT_STEP)
    at.button(key="story_run_export").click()
    at.run(timeout=30)
    assert not at.exception
    assert fake_backend.calls[-1][0] == "run_export"
    assert any(
        'data-tone="success"' in item.value and "Exported 33 invoices to SAP" in item.value
        for item in at.markdown
    )


def test_invoices_held_back_are_named(fake_backend):
    backend = _no_batches(fake_backend, 2)
    backend.export_problems = ("SAV-2026-1001: no vendor number in the master",)
    at = _run(story, backend)
    _advance(at, EXPORT_STEP)
    at.button(key="story_run_export").click()
    at.run(timeout=30)
    assert any(
        'data-tone="warning"' in item.value and "SAV-2026-1001: no vendor number" in item.value
        for item in at.markdown
    )


def test_no_button_when_nothing_is_ready(fake_backend):
    at = _run(story, _no_batches(fake_backend, 0))
    _advance(at, EXPORT_STEP)
    assert "story_run_export" not in [button.key for button in at.button]
    assert "Nothing is waiting for export" in _texts(at)


def test_the_batches_page_has_the_same_button(fake_backend):
    at = _run(batches, _no_batches(fake_backend, 5))
    assert at.button(key="batches_run_export").label == "Run the SAP export (5 ready)"
    assert not any("make export" in item.value for item in at.info)


# ---- Sending an exported invoice again (user's request, 2026-11-20) ----------------------


def _sent_before(backend, count: int = 2):
    from datetime import UTC, datetime
    from decimal import Decimal
    from uuid import uuid4

    from app.models import ExportedInvoice

    backend.history = tuple(
        ExportedInvoice(
            doc_id=uuid4(),
            invoice_number=f"SAV-2026-04{10 + n}",
            vendor="Stagecraft AV Rentals Pte. Ltd.",
            total=Decimal("1177.20"),
            batches=("B-1", "B-4") if n == 0 else ("B-1",),
            last_sent=datetime(2026, 11, 19, 10, 0, tzinfo=UTC),
        )
        for n in range(count)
    )
    return backend


def _resend_ids(backend):
    return [args[0] for name, args in backend.calls if name == "run_export"]


def test_invoices_sent_before_can_be_ticked_to_send_again(fake_backend):
    backend = _sent_before(_no_batches(fake_backend, 0))
    at = _run(batches, backend)
    assert "batches_run_export" not in [button.key for button in at.button]
    assert "Send again (2 sent before)" in [expander.label for expander in at.expander]
    first = backend.history[0]
    picker = at.multiselect(key="batches_run_export_resend")
    assert picker.format_func(first.doc_id) == (
        "SAV-2026-0410 · Stagecraft AV Rentals Pte. Ltd. · S$1,177.20 · sent in B-1, B-4"
    )

    picker.select(first.doc_id).run(timeout=30)
    assert at.button(key="batches_run_export").label == "Run the SAP export (1 sent again)"
    at.button(key="batches_run_export").click().run(timeout=30)

    assert _resend_ids(backend) == [(first.doc_id,)]
    card = "\n".join(m.value for m in at.markdown if 'data-notice="card"' in m.value)
    assert "Exported 1 invoice to SAP" in card
    assert "sent before: SAV-2026-0410" in card
    assert at.multiselect(key="batches_run_export_resend").value == []  # cleared after


def test_new_and_resent_invoices_go_out_together(fake_backend):
    backend = _sent_before(_no_batches(fake_backend, 3))
    at = _run(batches, backend)
    picker = at.multiselect(key="batches_run_export_resend")
    picker.set_value([item.doc_id for item in backend.history]).run(timeout=30)
    assert at.button(key="batches_run_export").label == (
        "Run the SAP export (3 ready + 2 sent again)"
    )
    at.multiselect(key="batches_run_export_resend").set_value([]).run(timeout=30)
    assert at.button(key="batches_run_export").label == "Run the SAP export (3 ready)"


def test_the_picker_has_no_buttons_of_its_own(fake_backend):
    """The list already offers "Select all" and a clear-all x (user, 2026-11-23: remove the
    duplicate), so the only button is the export itself."""
    at = _run(batches, _sent_before(_no_batches(fake_backend, 3)))
    assert [button.key for button in at.button] == ["batches_run_export"]
