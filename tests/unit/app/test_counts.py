"""Every page counts what came in the same way (user's report, 2026-11-20).

The Queue listed three documents under Discarded (one copy, two non-invoices) while the
Demo's flow strip said "58 received, 1 discarded". Now one count is shared: received is every
stored document plus every discarded copy; discarded is the copies plus the non-invoices; the
rest are the invoices.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from test_pages import _run

from app.counts import intake_counts
from app.flow import batch_outcomes
from app.models import DiscardedCopy, DocumentSummary
from app.pages import dashboard, queue, story
from invoiceflow.contracts import DocStatus


def _docs(*statuses: DocStatus) -> list[DocumentSummary]:
    return [DocumentSummary(doc_id=uuid4(), status=status) for status in statuses]


def test_received_discarded_and_invoices_add_up():
    other = DocStatus.NOT_INVOICE
    docs = _docs(DocStatus.EXPORTED, other, other, DocStatus.RECEIVED)
    counts = intake_counts(docs, copies=1)
    assert counts.received == 5
    assert counts.discarded == 3
    assert counts.invoices == 2  # one still being read counts as an invoice
    assert counts.received == counts.discarded + counts.invoices


def test_the_breakdown_names_both_kinds():
    assert intake_counts(_docs(DocStatus.NOT_INVOICE), copies=1).breakdown == (
        "1 copy of a file already in, 1 not an invoice"
    )
    two = _docs(DocStatus.NOT_INVOICE, DocStatus.NOT_INVOICE)
    assert intake_counts(two, copies=2).breakdown == (
        "2 copies of files already in, 2 not invoices"
    )
    assert intake_counts(_docs(DocStatus.EXPORTED), copies=0).breakdown == ""


def test_the_intake_box_counts_the_non_invoices_as_discarded():
    docs = _docs(DocStatus.EXPORTED, DocStatus.NOT_INVOICE, DocStatus.NOT_INVOICE)
    summaries = {outcome.name: outcome.summary for outcome in batch_outcomes(docs, copies=1)}
    assert summaries["Intake"] == "4 received, 3 discarded"
    # A non-invoice was read before anyone knew; Check says what it turned out to be.
    assert summaries["Read"] == "3 read"
    assert "2 not invoices" in summaries["Check"]


@pytest.fixture()
def mixed(fake_backend, clean_bundle, mismatch_bundle):
    """One invoice that passed, one non-invoice, and one discarded copy of the invoice."""
    statement = replace(mismatch_bundle.document, status=DocStatus.NOT_INVOICE)
    fake_backend.bundles[statement.doc_id] = replace(mismatch_bundle, document=statement)
    fake_backend.copies = (
        DiscardedCopy("a (2).pdf", None, "a" * 64, "a" * 64, clean_bundle.document),
    )
    return fake_backend


def _strip(at) -> str:
    return "\n".join(item.value for item in at.markdown if 'data-stage="Intake"' in item.value)


def _metric(at, label: str):
    return next(metric.value for metric in at.metric if metric.label == label)


@pytest.mark.parametrize("page", [story, queue, dashboard])
def test_every_page_shows_the_same_intake(mixed, page):
    at = _run(page, mixed)
    assert "3 received, 2 discarded" in _strip(at)


def test_the_queue_and_demo_list_the_same_discarded_documents(mixed):
    for page in (story, queue):
        at = _run(page, mixed)
        assert "Discarded (2)" in [expander.label for expander in at.expander]


def test_the_queue_and_dashboard_count_the_same_invoices(mixed):
    assert _metric(_run(queue, mixed), "Invoices") == "1"
    assert _metric(_run(dashboard, mixed), "Invoices") == "1"


def test_the_demo_sentence_uses_the_same_numbers(mixed):
    at = _run(story, mixed)
    text = "\n".join(item.value for item in at.markdown)
    assert (
        "3 documents arrived and 2 were discarded (1 copy of a file already in, "
        "1 not an invoice). The other 1 is an invoice: 1 passed or approved." in text
    )
