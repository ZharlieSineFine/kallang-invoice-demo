"""The random audit sample on screen (CR-012): the label on an auto-passed invoice, the
person's audit result, and the monitoring panel on Demo Step 8."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from streamlit.testing.v1 import AppTest
from test_pages import _run, _script, _set_doc
from test_story import _advance, _with_batch

from app.audit import AUDIT_LABEL, monitor_lines
from app.inbox import inbox_card
from app.models import AuditSummary
from app.pages import queue, story
from invoiceflow.contracts import DocStatus

LIMIT_REASON = (
    "At or above the S$5,000.00 auto-pass limit: every check passed, "
    "but an invoice this large needs a person."
)


def _summary(picked=3, checked=1, with_error=0, fields=()):
    return AuditSummary(
        percent=Decimal("10"),
        picked=picked,
        checked=checked,
        with_error=with_error,
        error_fields=fields,
    )


def _texts(at) -> str:
    groups = (at.subheader, at.markdown, at.caption, at.info, at.success, at.warning, at.error)
    return "\n".join(item.value for group in groups for item in group)


def _sampled(backend, bundle, result=None):
    doc = replace(bundle.document, is_audit_sample=True, audit_result=result)
    backend.bundles[doc.doc_id] = replace(bundle, document=doc)
    return doc


def _review(backend, doc_id) -> AppTest:
    at = AppTest(
        _script("from app.pages import review\nreview.render(*__args, **__kwargs)"),
        default_timeout=30,
        args=(backend,),
        kwargs={},
    )
    _set_doc(at, doc_id).run(timeout=30)
    assert not at.exception, [str(exc) for exc in at.exception]
    return at


# The monitoring lines -------------------------------------------------------------------
def test_too_few_checked_says_so():
    assert monitor_lines(_summary()) == (
        "Picked: 3 · Checked by a person: 1 · With an error: 0",
        "Too few checked to estimate a rate yet (needs 30 or more).",
    )


def test_thirty_clean_checks_give_the_rule_of_three_bound():
    _, rate = monitor_lines(_summary(picked=40, checked=30))
    assert rate == "With 95% confidence, fewer than 10.0% of auto-passed invoices have an error."


def test_errors_are_counted_with_their_fields():
    lines = monitor_lines(_summary(checked=4, with_error=1, fields=(("payment_terms", 1),)))
    assert lines[1] == "1 of 4 checked had an error (25.0%). Fields: payment_terms (1)."


# The label ------------------------------------------------------------------------------
def test_the_inbox_card_carries_the_label(clean_bundle):
    doc = replace(clean_bundle.document, is_audit_sample=True)
    assert inbox_card(doc, {}).audit is True
    assert inbox_card(clean_bundle.document, {}).audit is False


def test_the_queue_table_shows_the_label(fake_backend, clean_bundle):
    _sampled(fake_backend, clean_bundle)
    at = _run(queue, fake_backend)
    table = at.dataframe[0].value
    assert AUDIT_LABEL in set(table["audit"])


def test_review_shows_the_label_and_why(fake_backend, clean_bundle):
    doc = _sampled(fake_backend, clean_bundle)
    at = _review(fake_backend, doc.doc_id)
    text = _texts(at)
    assert f":violet-badge[{AUDIT_LABEL}]" in text
    assert "picked at random for a person to check against the page" in text
    assert "it does not hold up the invoice" in text
    assert doc.status is DocStatus.AUTO_PASSED


def test_an_invoice_not_picked_has_no_audit_buttons(fake_backend, clean_bundle):
    at = _review(fake_backend, clean_bundle.document.doc_id)
    assert "audit_passed" not in [button.key for button in at.button]


# The person's audit ---------------------------------------------------------------------
def test_audit_passed_is_recorded(fake_backend, clean_bundle):
    doc = _sampled(fake_backend, clean_bundle)
    at = _review(fake_backend, doc.doc_id)
    at.button(key="audit_passed").click()
    at.run(timeout=30)
    assert fake_backend.calls[-1] == ("record_audit", (doc.doc_id, "demo.reviewer", False, ()))


def test_an_error_needs_the_fields_that_were_wrong(fake_backend, clean_bundle):
    doc = _sampled(fake_backend, clean_bundle)
    at = _review(fake_backend, doc.doc_id)
    at.button(key="audit_error").click()
    at.run(timeout=30)
    assert not [call for call in fake_backend.calls if call[0] == "record_audit"]
    assert "Choose the fields that were wrong" in _texts(at)


def test_an_error_is_recorded_with_its_fields(fake_backend, clean_bundle):
    doc = _sampled(fake_backend, clean_bundle)
    at = _review(fake_backend, doc.doc_id)
    at.multiselect(key="audit_fields").set_value(["total"])
    at.button(key="audit_error").click()
    at.run(timeout=30)
    assert fake_backend.calls[-1] == (
        "record_audit",
        (doc.doc_id, "demo.reviewer", True, ("total",)),
    )


def test_a_finished_audit_shows_its_result(fake_backend, clean_bundle):
    doc = _sampled(fake_backend, clean_bundle, result="passed")
    at = _review(fake_backend, doc.doc_id)
    assert "audit_passed" not in [button.key for button in at.button]
    assert "Audit passed: every field matched the page." in _texts(at)


# The value limit ------------------------------------------------------------------------
def test_review_says_why_a_clean_invoice_needs_a_person(fake_backend, clean_bundle):
    doc = replace(clean_bundle.document, status=DocStatus.NEEDS_REVIEW, status_reason=LIMIT_REASON)
    fake_backend.bundles[doc.doc_id] = replace(clean_bundle, document=doc, findings=())
    at = _review(fake_backend, doc.doc_id)
    assert LIMIT_REASON in [item.value for item in at.info]


# Demo Step 8 ----------------------------------------------------------------------------
def test_step_8_explains_and_counts_the_audit(fake_backend, evaluation, tmp_path):
    fake_backend.evaluation = evaluation
    fake_backend.audit = _summary()
    at = _run(story, _with_batch(fake_backend, tmp_path))
    _advance(at, 7)
    text = _texts(at)
    assert "Monitoring auto-passed invoices" in text
    assert "A random 10% of them is picked for a person to check" in text
    assert "Picked: 3 · Checked by a person: 1 · With an error: 0" in text
