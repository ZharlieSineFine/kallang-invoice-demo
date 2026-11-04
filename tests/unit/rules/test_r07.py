"""R07: file readable and model output valid."""

from invoiceflow.contracts import TextSource
from invoiceflow.rules.r07 import R07


def test_r07_passes_clean(clean_ctx, rules_config):
    assert R07(rules_config).check(clean_ctx) == ()


def test_r07_flags_low_confidence_ocr(clean_ctx, rules_config):
    page = clean_ctx.document.pages[0].model_copy(
        update={"source": TextSource.OCR, "ocr_mean_conf": 30.0}
    )
    document = clean_ctx.document.model_copy(update={"pages": (page,)})
    ctx = clean_ctx.model_copy(update={"document": document})
    findings = R07(rules_config).check(ctx)
    assert any("not readable" in f.message for f in findings)


def test_r07_flags_invalid_extraction(clean_ctx, rules_config):
    extraction = clean_ctx.extraction.model_copy(
        update={"valid": False, "extraction": None, "error": "not JSON"}
    )
    ctx = clean_ctx.model_copy(update={"extraction": extraction})
    findings = R07(rules_config).check(ctx)
    assert any("invalid" in f.message for f in findings)
