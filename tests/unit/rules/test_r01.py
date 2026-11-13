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


def _without_value(ctx, field):
    """The model left ``field`` empty, so the locator has nothing to place on the page."""
    locations = tuple(
        loc.model_copy(update={"match_type": MatchType.NONE, "score": 0.0})
        if loc.field == field
        else loc
        for loc in ctx.locations
    )
    extraction = ctx.extraction.extraction
    if field.startswith("line_items[0]."):
        first = extraction.line_items[0].model_copy(update={field.split(".", 1)[1]: None})
        printed = extraction.model_copy(update={"line_items": (first, *extraction.line_items[1:])})
    else:
        printed = extraction.model_copy(update={field: None})
    result = ctx.extraction.model_copy(update={"extraction": printed})
    return ctx.model_copy(update={"locations": locations, "extraction": result})


def test_r01_ignores_a_header_value_the_model_left_empty(clean_ctx, rules_config):
    assert R01(rules_config).check(_without_value(clean_ctx, "po_number")) == ()


def test_r01_ignores_a_line_value_the_model_left_empty(clean_ctx, rules_config):
    assert R01(rules_config).check(_without_value(clean_ctx, "line_items[0].amount")) == ()
