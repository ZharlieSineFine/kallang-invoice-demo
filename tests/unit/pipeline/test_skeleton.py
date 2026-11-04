from datetime import date
from uuid import uuid4

import pytest

from invoiceflow.contracts import (
    Coder,
    Confidence,
    DocStatus,
    LLMClient,
    Locator,
    Normalizer,
    Router,
    Rule,
    TextExtractor,
    VendorMatcher,
)
from invoiceflow.pipeline import skeleton
from invoiceflow.pipeline.golden import GoldenFixtureNotFound
from invoiceflow.pipeline.stages import process_document, sha256_file
from invoiceflow.pipeline.stubs import golden_deps
from invoiceflow.settings import load_config

TODAY = date(2026, 11, 4)


def _run(golden, fixture, **kwargs):
    return process_document(
        fixture.pdf_path,
        file_id=fixture.file_id,
        doc_id=fixture.doc_id,
        deps=golden_deps(golden, **kwargs),
        master=golden.master,
        today=TODAY,
        run_id="test-run",
        rules_config=load_config("rules"),
    )


def test_stubs_satisfy_the_interfaces(golden):
    deps = golden_deps(golden)
    assert isinstance(deps.text_extractor, TextExtractor)
    assert isinstance(deps.llm_client, LLMClient)
    assert isinstance(deps.vendor_matcher, VendorMatcher)
    assert isinstance(deps.normalizer, Normalizer)
    assert isinstance(deps.coder, Coder)
    assert isinstance(deps.locator, Locator)
    assert all(isinstance(rule, Rule) for rule in deps.rules)
    assert isinstance(deps.router, Router)


def test_clean_invoice_passes(golden, clean):
    result = _run(golden, clean)
    assert result.decision.status is DocStatus.AUTO_PASSED
    assert result.findings == ()
    assert result.context.vendor.vendor_id == "V001"
    assert result.context.purchase_order.po_number == "4500012345"
    assert result.context.coding_lines == clean.truth.expected_coding
    assert result.file_sha256 == clean.sha256


def test_mismatch_goes_to_review_with_subtotal_low(golden, mismatch):
    result = _run(golden, mismatch)
    assert result.decision.status is DocStatus.NEEDS_REVIEW
    assert [(f.rule_id, f.field) for f in result.findings] == [("R02", "subtotal")]
    confidence = {c.field: c.confidence for c in result.decision.confidences}
    assert confidence["subtotal"] is Confidence.LOW
    assert confidence["invoice_number"] is Confidence.HIGH


def test_pilot_mode_sends_clean_invoices_to_review(golden, clean):
    assert _run(golden, clean, auto_approve_clean=False).decision.status is DocStatus.NEEDS_REVIEW


def test_prompt_text_leaves_out_hidden_words(golden, clean):
    deps = golden_deps(golden)
    document = deps.text_extractor.parse(clean.pdf_path, file_id=uuid4(), doc_id=uuid4())
    hidden = document.pages[0].words[0].model_copy(update={"hidden": True, "text": "IGNORE"})
    page = document.pages[0].model_copy(update={"words": (*document.pages[0].words, hidden)})
    texts = deps.text_extractor.page_texts(document.model_copy(update={"pages": (page,)}))
    assert "IGNORE" not in texts[0]
    assert "SAV-2026-0412" in texts[0]


def test_unknown_file_fails_clearly(golden, tmp_path):
    stray = tmp_path / "stray.pdf"
    stray.write_bytes(b"%PDF-1.7 not a golden fixture")
    with pytest.raises(GoldenFixtureNotFound):
        golden_deps(golden).text_extractor.parse(stray, file_id=uuid4(), doc_id=uuid4())


def test_sha256_file(clean):
    assert sha256_file(clean.pdf_path) == clean.sha256


def test_skeleton_cli(capsys):
    assert skeleton.main() == 0
    out = capsys.readouterr().out
    assert "golden-a-clean" in out and "AUTO_PASSED" in out
    assert "golden-a-total-mismatch" in out and "NEEDS_REVIEW" in out and "R02" in out
