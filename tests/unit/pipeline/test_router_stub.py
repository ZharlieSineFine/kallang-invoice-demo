"""The placeholder router (WS5 replaces it) and the invalid-extraction path."""

from datetime import date

import pytest

from invoiceflow.contracts import DocStatus, DocType, Finding, Scope, Severity
from invoiceflow.pipeline.stages import check_stage
from invoiceflow.pipeline.stubs import SeverityRouter, golden_deps
from invoiceflow.settings import load_config


@pytest.fixture(scope="module")
def ctx(golden, clean):
    deps = golden_deps(golden)
    document = deps.text_extractor.parse(clean.pdf_path, file_id=clean.file_id, doc_id=clean.doc_id)
    outcome = check_stage(
        document=document,
        extraction=clean.extraction,
        master=golden.master,
        file_sha256=clean.sha256,
        deps=deps,
        today=date(2026, 11, 4),
        run_id="t",
        rules_config=load_config("rules"),
    )
    return outcome.context


def _finding(severity, field=None):
    return Finding(
        rule_id="R05",
        rule_version="t",
        severity=severity,
        scope=Scope.FIELD if field else Scope.DOCUMENT,
        field=field,
        message="m",
    )


@pytest.mark.parametrize(
    ("severity", "status"),
    [
        (Severity.INFO, DocStatus.AUTO_PASSED),
        (Severity.FLAG, DocStatus.NEEDS_REVIEW),
        (Severity.HOLD, DocStatus.ON_HOLD),
        (Severity.MANUAL, DocStatus.MANUAL_ENTRY),
    ],
)
def test_highest_severity_decides(ctx, severity, status):
    decision = SeverityRouter().route(ctx, (_finding(Severity.INFO), _finding(severity)))
    assert decision.status is status


def test_info_findings_are_not_reasons(ctx):
    assert SeverityRouter().route(ctx, (_finding(Severity.INFO),)).reasons == ()


def test_statement_is_not_an_invoice(ctx):
    statement = ctx.model_copy(
        update={"invoice": ctx.invoice.model_copy(update={"document_type": DocType.STATEMENT})}
    )
    assert SeverityRouter().route(statement, ()).status is DocStatus.NOT_INVOICE


def test_invalid_extraction_goes_to_manual_entry(golden, clean):
    deps = golden_deps(golden)
    document = deps.text_extractor.parse(clean.pdf_path, file_id=clean.file_id, doc_id=clean.doc_id)
    broken = clean.extraction.model_copy(
        update={"valid": False, "extraction": None, "error": "not JSON"}
    )
    outcome = check_stage(
        document=document,
        extraction=broken,
        master=golden.master,
        file_sha256=clean.sha256,
        deps=deps,
        today=date(2026, 11, 4),
        run_id="t",
        rules_config={},
    )
    assert outcome.context.invoice is None
    assert outcome.decision.status is DocStatus.MANUAL_ENTRY
