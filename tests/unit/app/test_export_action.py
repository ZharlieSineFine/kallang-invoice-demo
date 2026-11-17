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
    assert any("33 invoices" in item.value for item in at.success)


def test_invoices_held_back_are_named(fake_backend):
    backend = _no_batches(fake_backend, 2)
    backend.export_problems = ("SAV-2026-1001: no vendor number in the master",)
    at = _run(story, backend)
    _advance(at, EXPORT_STEP)
    at.button(key="story_run_export").click()
    at.run(timeout=30)
    assert any("SAV-2026-1001: no vendor number" in item.value for item in at.warning)


def test_no_button_when_nothing_is_ready(fake_backend):
    at = _run(story, _no_batches(fake_backend, 0))
    _advance(at, EXPORT_STEP)
    assert "story_run_export" not in [button.key for button in at.button]
    assert "Nothing is waiting for export" in _texts(at)


def test_the_batches_page_has_the_same_button(fake_backend):
    at = _run(batches, _no_batches(fake_backend, 5))
    assert at.button(key="batches_run_export").label == "Run the SAP export (5 ready)"
    assert not any("make export" in item.value for item in at.info)
