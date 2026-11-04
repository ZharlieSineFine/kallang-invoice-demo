"""R01: values must be found on the page (exact, equal number, or fuzzy >= 90)."""

from invoiceflow.contracts import MatchType, Severity
from invoiceflow.rules.r01 import R01


def test_r01_passes_clean(clean_ctx, rules_config):
    assert R01(rules_config).check(clean_ctx) == ()


def test_r01_flags_value_not_found(clean_ctx, rules_config):
    locations = tuple(
        loc.model_copy(update={"match_type": MatchType.NONE, "score": 0.0})
        if loc.field == "invoice_number"
        else loc
        for loc in clean_ctx.locations
    )
    ctx = clean_ctx.model_copy(update={"locations": locations})
    findings = R01(rules_config).check(ctx)
    assert [f.field for f in findings] == ["invoice_number"]
    assert findings[0].severity is Severity.FLAG


def test_r01_flags_fuzzy_below_threshold(clean_ctx, rules_config):
    locations = tuple(
        loc.model_copy(update={"match_type": MatchType.FUZZY, "score": 80.0})
        if loc.field == "total"
        else loc
        for loc in clean_ctx.locations
    )
    ctx = clean_ctx.model_copy(update={"locations": locations})
    findings = R01(rules_config).check(ctx)
    assert [f.field for f in findings] == ["total"]


def test_r01_accepts_fuzzy_at_or_above_threshold(clean_ctx, rules_config):
    locations = tuple(
        loc.model_copy(update={"match_type": MatchType.FUZZY, "score": 90.0})
        if loc.field == "total"
        else loc
        for loc in clean_ctx.locations
    )
    ctx = clean_ctx.model_copy(update={"locations": locations})
    assert R01(rules_config).check(ctx) == ()
