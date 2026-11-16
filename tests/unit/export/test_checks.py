"""Batch check tests: each failure mode plus a clean batch."""

from dataclasses import replace
from datetime import date
from uuid import uuid4

from invoiceflow.export.checks import BatchError, check_batch
from invoiceflow.export.exporter import build_rows

EXPORT_DATE = date(2026, 11, 4)


def _check(mapping, master, docs, previously_exported=frozenset()):
    rows = build_rows(mapping, docs, EXPORT_DATE)
    return check_batch(mapping, rows, docs, master, previously_exported=previously_exported)


def test_clean_batch_has_no_problems(mapping, golden, clean_doc):
    assert _check(mapping, golden.master.coding, (clean_doc,)) == ()


def test_required_column_blocks_batch(mapping, golden, clean_doc):
    doc = replace(clean_doc, invoice=clean_doc.invoice.model_copy(update={"invoice_number": None}))
    problems = _check(mapping, golden.master.coding, (doc,))
    assert any("required column(s) empty: Reference" in p for p in problems)


def test_duplicate_vendor_reference_blocks_batch(mapping, golden, clean_doc):
    twin = replace(clean_doc, doc_id=uuid4())
    problems = _check(mapping, golden.master.coding, (clean_doc, twin))
    assert any("appears twice" in p for p in problems)


def test_duplicate_reference_with_different_spacing_blocks_batch(mapping, golden, clean_doc):
    number = clean_doc.invoice.invoice_number
    spaced = clean_doc.invoice.model_copy(update={"invoice_number": number.replace("-", " - ")})
    twin = replace(clean_doc, doc_id=uuid4(), invoice=spaced)
    problems = _check(mapping, golden.master.coding, (clean_doc, twin))
    assert any("appears twice" in p for p in problems)


def test_reconcile_blocks_total_mismatch(mapping, golden, mismatch_doc):
    problems = _check(mapping, golden.master.coding, (mismatch_doc,))
    assert any("net" in p and "tax" in p and "gross" in p for p in problems)


def test_unknown_gl_blocks_batch(mapping, golden, clean_doc):
    line = clean_doc.coding_lines[0].model_copy(update={"gl_account": "999999"})
    doc = replace(clean_doc, coding_lines=(line,))
    problems = _check(mapping, golden.master.coding, (doc,))
    assert any("unknown GL account '999999'" in p for p in problems)


def test_unknown_cost_center_blocks_batch(mapping, golden, clean_doc):
    line = clean_doc.coding_lines[0].model_copy(update={"cost_center": "XXXXXX"})
    doc = replace(clean_doc, coding_lines=(line,))
    problems = _check(mapping, golden.master.coding, (doc,))
    assert any("unknown cost center 'XXXXXX'" in p for p in problems)


def test_unknown_tax_code_blocks_batch(mapping, golden, clean_doc):
    line = clean_doc.coding_lines[0].model_copy(update={"tax_code": "ZZ"})
    doc = replace(clean_doc, coding_lines=(line,))
    problems = _check(mapping, golden.master.coding, (doc,))
    assert any("unknown tax code 'ZZ'" in p for p in problems)


def test_already_exported_blocks_batch(mapping, golden, clean_doc):
    problems = _check(
        mapping,
        golden.master.coding,
        (clean_doc,),
        previously_exported=frozenset({clean_doc.doc_id}),
    )
    assert any("was exported before" in p for p in problems)


def test_batch_error_aggregates_problems():
    err = BatchError(("first problem", "second problem"))
    assert "first problem; second problem" in str(err)
    assert err.problems == ("first problem", "second problem")
