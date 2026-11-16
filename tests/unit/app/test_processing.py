"""The "Processing…" card: a document the model is still reading shows up in the Queue."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest
from test_pages import _run, _run_main

from app.flow import batch_outcomes
from app.inbox import inbox_card
from app.models import DocumentBundle, DocumentSummary
from app.pages import queue, review
from invoiceflow.contracts import DocStatus

PROCESSING_ID = uuid5(NAMESPACE_URL, "processing")


def _processing_summary() -> DocumentSummary:
    return DocumentSummary(
        doc_id=PROCESSING_ID,
        status=DocStatus.RECEIVED,
        file_name="VTR-2026-9001.pdf",
        file_path="bronze/ab/abc",
        received_at=datetime(2026, 11, 13, 9, 0, tzinfo=UTC),
    )


@pytest.fixture()
def busy_backend(fake_backend):
    fake_backend.bundles[PROCESSING_ID] = DocumentBundle(document=_processing_summary())
    return fake_backend


def _text(at) -> str:
    return "\n".join(item.value for item in at.markdown)


@pytest.mark.parametrize("status", [DocStatus.RECEIVED, DocStatus.PARSED, DocStatus.EXTRACTED])
def test_a_document_without_an_outcome_is_processing(status):
    assert DocumentSummary(doc_id=PROCESSING_ID, status=status).is_processing


def test_a_document_with_an_outcome_is_not_processing():
    assert not DocumentSummary(doc_id=PROCESSING_ID, status=DocStatus.NEEDS_REVIEW).is_processing


def test_a_processing_card_names_the_file_and_shows_the_uploaded_page():
    card = inbox_card(_processing_summary(), {})
    assert card.tone == "processing"
    assert card.outcome == "Processing…"
    assert card.vendor == "VTR-2026-9001.pdf"
    assert card.image_path == "bronze/ab/abc"
    assert card.amount == "—"


def test_the_flow_strip_counts_a_document_being_read_as_received_not_read(clean_bundle):
    done = clean_bundle.document
    summaries = {
        outcome.name: outcome.summary
        for outcome in batch_outcomes((done, done, _processing_summary()))
    }
    assert summaries["Intake"] == "3 received"
    assert summaries["Read"] == "2 read, 1 in progress"
    assert summaries["Extract"] == "2 extracted"


def test_the_queue_shows_the_document_being_read_before_the_rest(busy_backend):
    at = _run(queue, busy_backend)
    text = _text(at)
    assert "Processing…" in text
    assert "VTR-2026-9001.pdf" in text
    assert text.index("Processing…") < text.index("Auto passed")
    # It has no outcome yet, so it is not in the table and there is nothing to open.
    assert all("VTR-2026-9001" not in frame.value.to_string() for frame in at.dataframe)
    assert f"inbox_open_{PROCESSING_ID}" not in [button.key for button in at.button]


def test_the_queue_still_opens_a_finished_document_while_another_is_read(
    busy_backend, mismatch_bundle
):
    at = _run_main(busy_backend)
    at.sidebar.radio(key="page").set_value("Queue").run(timeout=30)
    at.button(key=f"inbox_open_{mismatch_bundle.document.doc_id}").click()
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["page"] == "Review"


def test_review_does_not_offer_a_document_still_being_read(busy_backend):
    at = _run(review, busy_backend)
    options = [option for box in at.selectbox for option in box.options]
    assert options
    assert not any("VTR-2026-9001" in option or "received" in option.lower() for option in options)


def test_a_processing_thumbnail_renders_the_stored_pdf_which_has_no_extension(golden, tmp_path):
    from app.inbox import _thumbnail

    stored = tmp_path / "e3b0c44298fc1c149afbf4c8996fb924"  # bronze files are named by hash
    stored.write_bytes(golden.fixtures[0].pdf_path.read_bytes())
    data = _thumbnail(str(stored))
    assert data is not None and data[:2] == b"\xff\xd8"  # a JPEG thumbnail
