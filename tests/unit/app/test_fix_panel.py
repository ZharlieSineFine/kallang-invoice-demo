"""Review page: each finding leads straight to its field, with plain choices to fix it."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from test_pages import _run, _set_doc

from app.models import FindingRow
from app.pages import review
from invoiceflow.contracts import DocStatus, Scope, Severity


def _open(backend, bundle):
    at = _set_doc(_run(review, backend), bundle.document.doc_id)
    at.run(timeout=30)
    assert not at.exception, [str(exc) for exc in at.exception]
    return at


def _text(at) -> str:
    groups = (at.markdown, at.caption, at.subheader, at.warning, at.info)
    return "\n".join(item.value for group in groups for item in group)


def _value_key(bundle, field: str) -> str:
    return f"fix_value_{bundle.document.doc_id}_{field}"


def test_the_page_opens_on_the_first_flagged_field(fake_backend, mismatch_bundle):
    at = _open(fake_backend, mismatch_bundle)
    assert at.selectbox(key="review_field").value == "subtotal"


def _bank_hold(backend, bundle):
    """Like the real R08: a hold on the bank account field, next to the R02 flag."""
    hold = FindingRow(
        rule_id="R08",
        field="bank_account",
        severity=Severity.HOLD,
        scope=Scope.FIELD,
        message="The bank account differs from the vendor master.",
        run_id="fixtures",
    )
    document = replace(bundle.document, status=DocStatus.ON_HOLD)
    changed = replace(bundle, document=document, findings=(hold, *bundle.findings))
    backend.bundles[changed.document.doc_id] = changed
    return changed


def test_each_finding_has_a_button_that_selects_its_field(fake_backend, mismatch_bundle):
    bundle = _bank_hold(fake_backend, mismatch_bundle)
    at = _open(fake_backend, bundle)
    at.selectbox(key="review_field").set_value("total").run(timeout=30)
    at.button(key="fix_0").click().run(timeout=30)
    assert at.selectbox(key="review_field").value == "bank_account"


def test_the_panel_shows_the_value_and_two_explained_choices(fake_backend, mismatch_bundle):
    at = _open(fake_backend, mismatch_bundle)
    text = _text(at)
    assert "Fixing: subtotal" in text
    assert "Read on the invoice" in text
    assert at.button(key="btn_correct").label == "Save correction"
    assert at.button(key="btn_confirm").label == "Correct as printed"
    assert "rerun the checks" in text
    assert "clears the flag" in text


def test_correct_as_printed_clears_the_flag(fake_backend, mismatch_bundle):
    doc_id = mismatch_bundle.document.doc_id
    at = _open(fake_backend, mismatch_bundle)
    at.button(key="btn_confirm").click().run(timeout=30)
    assert ("confirm", (doc_id, "subtotal", "demo.reviewer")) in fake_backend.calls
    after = fake_backend.bundles[doc_id]
    assert not [f for f in after.findings if f.field == "subtotal"]
    assert after.document.status is DocStatus.NEEDS_REVIEW


def test_save_correction_sends_the_typed_value(fake_backend, mismatch_bundle):
    at = _open(fake_backend, mismatch_bundle)
    at.text_input(key=_value_key(mismatch_bundle, "subtotal")).set_value("1,080.00").run()
    at.button(key="btn_correct").click().run(timeout=30)
    calls = [call for call in fake_backend.calls if call[0] == "correct"]
    assert calls and calls[0][1][1:3] == ("subtotal", "1,080.00")


def test_a_flagged_line_value_is_fixed_in_the_panel(fake_backend, mismatch_bundle):
    line_flag = FindingRow(
        rule_id="R02",
        field="line_items[0].amount",
        severity=Severity.FLAG,
        scope=Scope.FIELD,
        message="Line 1 works out to S$540.00, but the amount reads S$500.00.",
        run_id="fixtures",
    )
    bundle = replace(mismatch_bundle, findings=(line_flag,))
    fake_backend.bundles[bundle.document.doc_id] = bundle
    at = _open(fake_backend, bundle)
    assert at.selectbox(key="review_field").value == "line_items[0].amount"
    at.text_input(key=_value_key(bundle, "line_items[0].amount")).set_value("500.00").run()
    at.button(key="btn_correct").click().run(timeout=30)
    (call,) = [call for call in fake_backend.calls if call[0] == "edit_line_items"]
    items = call[1][1]
    assert items[0].amount == Decimal("500.00")
    assert len(items) == len(bundle.line_items)


def test_a_held_field_says_the_hold_needs_a_release(fake_backend, mismatch_bundle):
    at = _open(fake_backend, _bank_hold(fake_backend, mismatch_bundle))
    assert at.selectbox(key="review_field").value == "bank_account"
    assert "does not release the hold" in _text(at)


def test_release_hold_only_appears_for_an_invoice_on_hold(fake_backend, mismatch_bundle):
    at = _open(fake_backend, mismatch_bundle)
    assert "btn_release" not in [button.key for button in at.button]
    assert "Pay it" in _text(at) and "Don't pay it" in _text(at)


def _with_finding(backend, bundle, field, rule="R06"):
    finding = FindingRow(
        rule_id=rule,
        field=field,
        severity=Severity.FLAG,
        scope=Scope.FIELD,
        message="A value is missing.",
        run_id="fixtures",
    )
    changed = replace(bundle, findings=(finding,))
    backend.bundles[changed.document.doc_id] = changed
    return changed


def test_a_missing_invoice_value_can_be_typed_in(fake_backend, mismatch_bundle):
    from invoiceflow.contracts import HEADER_FIELDS

    stored = {field.name for field in mismatch_bundle.fields}
    missing = next(name for name in HEADER_FIELDS if name not in stored)
    bundle = _with_finding(fake_backend, mismatch_bundle, missing, rule="R03")
    at = _open(fake_backend, bundle)
    assert at.selectbox(key="review_field").value == missing
    assert f"Fixing: {missing}" in _text(at)


def test_a_coding_finding_points_to_the_coding_table(fake_backend, mismatch_bundle):
    bundle = _with_finding(fake_backend, mismatch_bundle, "coding_lines[0].gl_account")
    at = _open(fake_backend, bundle)
    assert "Coding table" in _text(at)
    assert "fix_0" not in [button.key for button in at.button]


def test_a_master_data_finding_says_it_is_not_on_the_invoice(fake_backend, mismatch_bundle):
    bundle = _with_finding(fake_backend, mismatch_bundle, "sap_vendor_no")
    at = _open(fake_backend, bundle)
    assert "vendor master" in _text(at)
    assert "fix_0" not in [button.key for button in at.button]
