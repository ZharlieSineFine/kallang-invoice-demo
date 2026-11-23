"""After a reviewer's change, the rerun also checks the GST and each line's arithmetic
(user's report, 2026-11-20).

On KSS-2026-8202 the model read the quantity as 720 instead of 120. Following the flags, the
reviewer raised the line amount, the subtotal and the total to match, and the rerun said
"nothing open" although the GST, 205.20, was still 9% of the old 2,280.00 subtotal. The
rerun only recomputed lines-vs-subtotal and subtotal-plus-GST-vs-total.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.models import FieldRow, FindingRow, LineItemRow
from app.recheck import LineMath, RecheckInput, carried_findings, recheck, recompute_findings
from invoiceflow.contracts import DocStatus, DocType, Scope, Severity


def _kallang(rules_config, **changes) -> RecheckInput:
    """KSS-2026-8202 after the reviewer's three changes."""
    state = RecheckInput(
        invoice_number="KSS-2026-8202",
        document_type=DocType.TAX_INVOICE,
        subtotal=Decimal("13680.00"),
        gst_amount=Decimal("205.20"),
        gst_rate=Decimal("9"),
        total=Decimal("13885.20"),
        line_amounts=(Decimal("13680.00"),),
        lines=(LineMath(Decimal("720"), Decimal("19.00"), None, Decimal("13680.00")),),
        rules_config=rules_config,
    )
    return replace(state, **changes)


def _found(state) -> list[tuple[str, str]]:
    return [(finding.rule_id, finding.field) for finding in recompute_findings(state)]


def test_gst_that_no_longer_matches_the_subtotal_is_caught(rules_config):
    findings = recompute_findings(_kallang(rules_config))
    (gst,) = findings
    assert (gst.rule_id, gst.field) == ("R03", "gst_amount")
    assert gst.message == (
        "GST at 9% of the S$13,680.00 subtotal is S$1,231.20, but the GST reads S$205.20."
    )
    assert gst.evidence["expected_gst"] == "1231.20"
    assert recheck(_kallang(rules_config)).status is DocStatus.NEEDS_REVIEW


def test_the_printed_figures_pass(rules_config):
    printed = _kallang(
        rules_config,
        subtotal=Decimal("2280.00"),
        total=Decimal("2485.20"),
        line_amounts=(Decimal("2280.00"),),
        lines=(LineMath(Decimal("120"), Decimal("19.00"), None, Decimal("2280.00")),),
    )
    assert _found(printed) == []


def test_gst_within_rounding_passes(rules_config):
    assert ("R03", "gst_amount") not in _found(
        _kallang(rules_config, gst_amount=Decimal("1231.24"))
    )


def test_no_rate_means_no_gst_check(rules_config):
    assert _found(_kallang(rules_config, gst_rate=None)) == []


def test_gst_inside_an_inclusive_total_is_worked_out_from_the_total(rules_config):
    inclusive = _kallang(
        rules_config,
        subtotal=Decimal("1090.00"),
        total=Decimal("1090.00"),
        gst_amount=Decimal("90.00"),
        line_amounts=(Decimal("1090.00"),),
        lines=(),
        gst_inclusive=True,
    )
    assert _found(inclusive) == []


def test_a_line_that_does_not_work_out_is_caught(rules_config):
    misread = _kallang(
        rules_config,
        subtotal=Decimal("2280.00"),
        total=Decimal("2485.20"),
        line_amounts=(Decimal("2280.00"),),
        lines=(LineMath(Decimal("720"), Decimal("19.00"), None, Decimal("2280.00")),),
    )
    (line,) = recompute_findings(misread)
    assert (line.rule_id, line.field) == ("R02", "line_items[0].amount")
    assert line.message == (
        "Line 1 works out to S$13,680.00 (720 \u00d7 19.00), but the amount reads S$2,280.00. "
        "The subtotal, GST and total agree with each other, so check this line's quantity "
        "and unit price on the page first."
    )


def test_days_multiply_a_rental_line(rules_config):
    rental = LineMath(Decimal("2"), Decimal("100.00"), Decimal("3"), Decimal("600.00"))
    assert ("R02", "line_items[0].amount") not in _found(_kallang(rules_config, lines=(rental,)))


def test_from_bundle_reads_the_rate_and_the_lines(clean_bundle, rules_config):
    bundle = replace(
        clean_bundle,
        fields=(*clean_bundle.fields, FieldRow(name="gst_rate", value_raw="9%", value_norm="9")),
        line_items=(
            LineItemRow(
                line_no=1,
                quantity=Decimal("120"),
                days=None,
                unit_price=Decimal("19.00"),
                amount=Decimal("2280.00"),
            ),
        ),
    )
    state = RecheckInput.from_bundle(bundle, rules_config)
    assert state.gst_rate == Decimal("9")
    assert state.lines == (LineMath(Decimal("120"), Decimal("19.00"), None, Decimal("2280.00")),)


def _row(rule_id, field, evidence):
    return FindingRow(
        rule_id=rule_id,
        field=field,
        severity=Severity.FLAG,
        scope=Scope.FIELD,
        message="from intake",
        evidence=evidence,
    )


def test_intake_findings_the_rerun_works_out_again_are_not_kept_twice():
    previous = (
        _row("R03", "gst_amount", {"expected_gst": "1231.20"}),
        _row("R02", "line_items[0].amount", {"expected": "13680.00"}),
        _row("R03", "gst_amount", {}),  # "Simplified tax invoice must charge GST": kept
    )
    kept = carried_findings(previous)
    assert [(row.rule_id, row.field, row.evidence) for row in kept] == [
        ("R03", "gst_amount", {}),
    ]
