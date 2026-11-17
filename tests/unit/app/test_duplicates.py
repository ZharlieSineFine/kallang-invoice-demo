"""The "Check the discarded copy" panel: lets a person confirm a discarded file really is
an exact copy of a stored one, on Demo Step 1 and on the Queue page."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from test_pages import _run

from app.duplicates import check_commands, comparison_rows, short_fingerprint
from app.models import DiscardedCopy
from app.pages import queue, story

SHA = "73448bbea448bcca7401abc0b926a8ca7fa560970de4a31f7037899219a0dd7d"
ARRIVED = datetime(2026, 11, 17, 3, 44, 41, tzinfo=UTC)  # 11:44:41 in Singapore


@pytest.fixture()
def copy(clean_bundle):
    original = replace(clean_bundle.document, received_at=ARRIVED)
    return DiscardedCopy(
        name="invoice (2).pdf", arrived_at=ARRIVED, sha256=SHA, kept_sha256=SHA, original=original
    )


def _texts(at) -> str:
    groups = (at.markdown, at.caption, at.success, at.warning, at.code)
    return "\n".join(item.value for group in groups for item in group)


def test_the_fingerprint_is_shortened_to_its_ends():
    assert short_fingerprint(SHA) == "73448bbe…a0dd7d"


def test_the_rows_put_the_copy_beside_the_original(copy):
    rows = comparison_rows(copy)
    assert rows["Discarded copy"] == [
        "invoice (2).pdf",
        "2026-11-17 11:44:41 SGT",
        "73448bbe…a0dd7d",
    ]
    assert rows["Kept original"] == ["invoice.pdf", "2026-11-17 11:44:41 SGT", "73448bbe…a0dd7d"]


def test_the_commands_name_the_copy_and_both_systems(copy):
    mac, windows = check_commands(copy)
    assert mac == 'shasum -a 256 "invoice (2).pdf"'
    assert windows == 'certutil -hashfile "invoice (2).pdf" SHA256'


def test_step_1_shows_the_panel_with_the_proof(fake_backend, copy):
    fake_backend.copies = (copy,)
    at = _run(story, fake_backend)
    assert [e.label for e in at.expander] == ["Check the discarded copy (1)"]
    assert "the two files are identical, byte for byte" in _texts(at)
    assert SHA in _texts(at)  # the full value, to compare with the command's output
    assert 'shasum -a 256 "invoice (2).pdf"' in _texts(at)
    assert "story_copy_0_download" in [b.key for b in at.get("download_button")]


def test_open_in_review_jumps_to_the_original(fake_backend, copy):
    fake_backend.copies = (copy,)
    at = _run(story, fake_backend)
    at.button(key="story_copy_0_open").click()
    at.run(timeout=30)
    assert at.session_state["selected_doc_id"] == copy.original.doc_id
    assert at.session_state["page"] == "Review"


def test_different_fingerprints_are_never_called_identical(fake_backend, copy):
    fake_backend.copies = (replace(copy, kept_sha256="0" * 64),)
    at = _run(story, fake_backend)
    assert not any("identical, byte for byte" in item.value for item in at.success)
    assert any("do not match" in item.value for item in at.warning)


def test_a_missing_stored_file_is_said_plainly(fake_backend, copy):
    missing = replace(copy.original, file_path="/nowhere/invoice.pdf")
    fake_backend.copies = (replace(copy, original=missing),)
    at = _run(story, fake_backend)
    assert "story_copy_0_download" not in [b.key for b in at.get("download_button")]
    assert "not on this computer" in _texts(at)


def test_no_panel_without_a_discarded_copy(fake_backend):
    at = _run(story, fake_backend)
    assert not at.expander


def test_the_queue_page_has_the_same_panel(fake_backend, copy):
    fake_backend.copies = (copy,)
    at = _run(queue, fake_backend)
    assert "Check the discarded copy (1)" in [e.label for e in at.expander]
    assert "queue_copy_0_open" in [b.key for b in at.button]
