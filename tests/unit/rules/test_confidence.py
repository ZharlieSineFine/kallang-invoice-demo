"""Field confidence comes from the checks, not the model."""

from invoiceflow.contracts import Confidence, Finding, MatchType, Scope, Severity
from invoiceflow.rules.confidence import field_confidences


def _finding(field, severity=Severity.FLAG):
    return Finding(
        rule_id="R01",
        rule_version="t",
        severity=severity,
        scope=Scope.FIELD,
        field=field,
        message="m",
    )


def test_exact_and_numeric_are_high(clean_ctx):
    confidences = {c.field: c.confidence for c in field_confidences(clean_ctx, ())}
    assert confidences["invoice_number"] is Confidence.HIGH
    assert all(c is Confidence.HIGH for c in confidences.values())


def test_fuzzy_is_medium(clean_ctx):
    locations = tuple(
        loc.model_copy(update={"match_type": MatchType.FUZZY}) if loc.field == "total" else loc
        for loc in clean_ctx.locations
    )
    ctx = clean_ctx.model_copy(update={"locations": locations})
    confidences = {c.field: c.confidence for c in field_confidences(ctx, ())}
    assert confidences["total"] is Confidence.MEDIUM


def test_not_found_is_low(clean_ctx):
    locations = tuple(
        loc.model_copy(update={"match_type": MatchType.NONE, "score": 0.0})
        if loc.field == "total"
        else loc
        for loc in clean_ctx.locations
    )
    ctx = clean_ctx.model_copy(update={"locations": locations})
    confidences = {c.field: c.confidence for c in field_confidences(ctx, ())}
    assert confidences["total"] is Confidence.LOW


def test_flagged_field_is_low(clean_ctx):
    confidences = {
        c.field: c.confidence for c in field_confidences(clean_ctx, (_finding("subtotal"),))
    }
    assert confidences["subtotal"] is Confidence.LOW
    assert confidences["invoice_number"] is Confidence.HIGH


def test_info_findings_do_not_flag(clean_ctx):
    confidences = {
        c.field: c.confidence
        for c in field_confidences(clean_ctx, (_finding("subtotal", Severity.INFO),))
    }
    assert confidences["subtotal"] is Confidence.HIGH
