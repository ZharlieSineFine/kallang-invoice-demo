"""Swap the three WS4 stubs for the real implementations and run the golden checks.

Everything else stays a Phase 0 stub, so this proves the contracts are enough for the
pipeline to use WS4 without changing its neighbours.
"""

from dataclasses import replace

from invoiceflow.contracts import FileKind, ParsedDocument
from invoiceflow.locate import Locator
from invoiceflow.normalize import Normalizer, VendorMatcher
from invoiceflow.pipeline.golden import load_golden
from invoiceflow.pipeline.skeleton import GOLDEN_TODAY
from invoiceflow.pipeline.stages import check_stage
from invoiceflow.pipeline.stubs import golden_deps
from invoiceflow.settings import load_config


def test_golden_pipeline_runs_with_the_real_ws4_stages():
    golden = load_golden()
    rules_config = load_config("rules")
    base = golden_deps(golden, auto_approve_clean=True)
    deps = replace(
        base,
        vendor_matcher=VendorMatcher(),
        normalizer=Normalizer(),
        locator=Locator(),
    )

    for fixture in golden.fixtures:
        document = ParsedDocument(
            doc_id=fixture.doc_id,
            file_id=fixture.file_id,
            file_kind=FileKind.PDF,
            pages=(fixture.page,),
        )
        outcome = check_stage(
            document=document,
            extraction=fixture.extraction,
            master=golden.master,
            file_sha256=fixture.sha256,
            deps=deps,
            today=GOLDEN_TODAY,
            run_id="ws4-integration",
            rules_config=rules_config,
        )

        assert outcome.context.vendor is not None
        assert outcome.context.vendor.vendor_id == "V001"
        assert outcome.context.invoice is not None
        assert outcome.context.normalization_problems == ()
        assert len(outcome.context.locations) == 24
        assert all(location.bbox is not None for location in outcome.context.locations)
        assert outcome.decision.status is fixture.expected_status
        assert [finding.rule_id for finding in outcome.findings] == list(
            fixture.truth.expected_rules
        )
