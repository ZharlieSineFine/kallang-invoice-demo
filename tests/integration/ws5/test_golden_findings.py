"""The golden fixtures must produce their expected findings through the real rules.

- golden-a-clean           -> AUTO_PASSED, no findings
- golden-a-total-mismatch  -> NEEDS_REVIEW, exactly R02 on subtotal
"""

from datetime import date

import pytest

from invoiceflow.contracts import Confidence, DocStatus
from invoiceflow.pipeline.golden import GoldenSet, load_golden
from invoiceflow.pipeline.stages import PipelineDeps, check_stage
from invoiceflow.pipeline.stubs import (
    GoldenCoder,
    GoldenLLMClient,
    GoldenLocator,
    GoldenNormalizer,
    GoldenTextExtractor,
    GoldenVendorMatcher,
)
from invoiceflow.rules import Router, build_rules
from invoiceflow.settings import load_config

GOLDEN_TODAY = date(2026, 11, 4)


@pytest.fixture(scope="module")
def config():
    return load_config("rules")


@pytest.fixture(scope="module")
def golden() -> GoldenSet:
    return load_golden()


@pytest.fixture(scope="module")
def deps(golden, config) -> PipelineDeps:
    return PipelineDeps(
        text_extractor=GoldenTextExtractor(golden),
        llm_client=GoldenLLMClient(golden),
        vendor_matcher=GoldenVendorMatcher(),
        normalizer=GoldenNormalizer(golden),
        coder=GoldenCoder(golden),
        locator=GoldenLocator(golden),
        rules=build_rules(config),
        router=Router(config),
    )


def _run(fixture, golden, deps, config):
    document = deps.text_extractor.parse(
        fixture.pdf_path, file_id=fixture.file_id, doc_id=fixture.doc_id
    )
    return check_stage(
        document=document,
        extraction=fixture.extraction,
        master=golden.master,
        file_sha256=fixture.sha256,
        deps=deps,
        today=GOLDEN_TODAY,
        run_id="ws5",
        rules_config=config,
    )


def test_clean_fixture_has_no_findings(golden, deps, config):
    outcome = _run(golden.fixtures[0], golden, deps, config)
    assert outcome.findings == ()
    assert outcome.decision.status is DocStatus.AUTO_PASSED


def test_twin_fixture_flags_only_subtotal(golden, deps, config):
    fixture = golden.by_invoice_number("SAV-2026-0413")
    outcome = _run(fixture, golden, deps, config)
    assert outcome.decision.status is DocStatus.NEEDS_REVIEW
    assert [(f.rule_id, f.field) for f in outcome.findings] == [("R02", "subtotal")]
    finding = outcome.findings[0]
    assert finding.message == (
        "The line items add up to S$1,080.00, but the subtotal reads S$1,090.00."
    )
    assert finding.evidence == {"lines_sum": "1080.00", "subtotal": "1090.00"}


def test_twin_confidences_match_the_plan(golden, deps, config):
    fixture = golden.by_invoice_number("SAV-2026-0413")
    outcome = _run(fixture, golden, deps, config)
    confidence = {c.field: c.confidence for c in outcome.decision.confidences}
    assert confidence["subtotal"] is Confidence.LOW
    assert confidence["invoice_number"] is Confidence.HIGH
