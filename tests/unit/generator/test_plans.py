"""The 57-document composition (50 full run, 4 live demo, 3 over the auto-pass limit), seeded
content, and anomaly assignment."""

from __future__ import annotations

from decimal import Decimal

import pytest

from generator.plans import (
    ANOMALY_RULES,
    AV_1080,
    arrival_order,
    build_plans,
    is_live_demo,
    is_over_limit,
    plan_by_id,
)
from invoiceflow.contracts import DocType
from invoiceflow.rules import Router
from invoiceflow.settings import load_config


def test_fifty_for_the_full_run_four_for_the_live_demo_and_three_over_the_limit(plans):
    assert len(plans) == 57
    assert sum(is_live_demo(plan) for plan in plans) == 4
    assert sum(is_over_limit(plan) for plan in plans) == 3
    assert not hasattr(plans[0], "set_name")


def test_live_demo_invoices_show_both_ways_of_reading_a_page(plans):
    live = [plan for plan in plans if is_live_demo(plan)]
    digital = [plan for plan in live if plan.template != "C1"]
    scanned = [plan for plan in live if plan.template == "C1"]
    assert len(digital) == 2 and len(scanned) == 2  # pdfplumber text layer vs Tesseract OCR
    assert all(not plan.anomalies and not plan.expected_rules for plan in live)


def _group(plan) -> str:
    return "live" if is_live_demo(plan) else "over" if is_over_limit(plan) else "run"


def test_live_demo_invoices_arrive_after_the_full_run(plans):
    # Uploaded after the recorded run, so they must never look older than it. The three over
    # the limit came later still, so the first 54 keep their arrival times.
    groups = [_group(plan) for plan in arrival_order(plans)]
    assert groups == ["run"] * 50 + ["live"] * 4 + ["over"] * 3


def test_the_three_over_the_limit_are_clean_and_at_least_the_limit(plans):
    limit = Router(load_config("rules")).auto_pass_limit
    over = [plan for plan in plans if is_over_limit(plan)]
    assert [plan.invoice_number for plan in over] == [
        "SAV-2026-9701",
        "MEL-2026-9702",
        "BLP-2026-9703",
    ]
    assert all(not plan.anomalies and not plan.expected_rules for plan in over)
    assert all(_total(plan) >= limit for plan in over)
    assert all(plan.template != "C1" for plan in over)  # digital, so they read cleanly


def test_only_planted_repeats_share_an_invoice_number(plans):
    by_number: dict[str, list] = {}
    for plan in plans:
        by_number.setdefault(plan.invoice_number, []).append(plan)
    repeats = {number: group for number, group in by_number.items() if len(group) > 1}
    assert all(
        any({"resend", "duplicate_file"} & set(plan.anomalies) for plan in group)
        for group in repeats.values()
    )


def test_arrival_order_puts_originals_before_their_repeats_and_credit_notes(plans):
    order = {plan.document_id: index for index, plan in enumerate(arrival_order(plans))}
    by_number = {}
    for plan in arrival_order(plans):
        by_number.setdefault(plan.invoice_number, plan)
    for plan in plans:
        first = by_number[plan.invoice_number]
        if first.document_id != plan.document_id:
            assert not set(first.anomalies) & {"resend", "duplicate_file"}
            assert order[first.document_id] < order[plan.document_id]
        if plan.original_invoice_ref:
            assert order[by_number[plan.original_invoice_ref].document_id] < order[plan.document_id]


def test_document_ids_are_unique(plans):
    ids = [plan.document_id for plan in plans]
    assert len(ids) == len(set(ids))


def test_every_anomaly_is_used(plans):
    used = {anomaly for plan in plans for anomaly in plan.anomalies}
    assert used == set(ANOMALY_RULES)


def test_expected_rules_follow_the_anomaly_table(plans):
    for plan in plans:
        expected: list[str] = []
        for anomaly in plan.anomalies:
            for rule in ANOMALY_RULES[anomaly]:
                if rule not in expected:
                    expected.append(rule)
        assert list(plan.expected_rules) == expected


def test_each_document_has_at_most_one_anomaly(plans):
    assert all(len(plan.anomalies) <= 1 for plan in plans)


def test_the_slide_three_invoice_is_in_the_batch(plans):
    edited = {plan.document_id: plan for plan in plans}["live-02"]
    assert edited.anomalies == ("total_edited",)
    assert edited.total_override == Decimal("1090.00")
    assert edited.lines == AV_1080
    assert sum(line.amount for line in edited.lines) == Decimal("1080.00")


def test_a_type_a_invoice_uses_no_po_and_the_vendor_default(plans):
    no_po = [
        plan
        for plan in plans
        if plan.doc_type in {DocType.TAX_INVOICE, DocType.SIMPLIFIED_TAX_INVOICE}
        and plan.po_number is None
        and plan.venue is None
        and not plan.anomalies
    ]
    assert no_po, "at least one clean type A invoice must exercise the vendor default"
    assert any(plan.template == "A2" and plan.simplified for plan in no_po)


def test_type_b_invoices_name_their_venue(plans):
    b_invoices = [plan for plan in plans if plan.template.startswith("B")]
    assert b_invoices
    assert all(plan.venue for plan in b_invoices)


def test_simplified_invoices_stay_under_the_irate_limit(plans):
    simplified = [plan for plan in plans if plan.simplified]
    assert simplified
    for plan in simplified:
        gross = sum(line.amount for line in plan.lines)
        assert gross <= Decimal("1000.00"), plan.document_id


def test_duplicate_file_pair_and_resend_pair(plans):
    by_id = {plan.document_id: plan for plan in plans}
    duplicate = next(plan for plan in plans if "duplicate_file" in plan.anomalies)
    original = by_id[duplicate.copy_of]
    assert duplicate.invoice_number == original.invoice_number

    resend = next(plan for plan in plans if "resend" in plan.anomalies)
    earlier = by_id["pre-a-01"]
    assert resend.invoice_number == earlier.invoice_number
    assert resend.vendor_id == earlier.vendor_id
    assert resend.lines == earlier.lines


def test_statement_and_credit_notes_are_not_invoices(plans):
    statement = next(plan for plan in plans if "statement" in plan.anomalies)
    assert statement.doc_type is DocType.STATEMENT
    assert statement.statement_rows

    credit_notes = [plan for plan in plans if plan.doc_type is DocType.CREDIT_NOTE]
    assert len(credit_notes) == 2
    assert all(plan.original_invoice_ref for plan in credit_notes)
    assert all(line.amount < 0 for plan in credit_notes for line in plan.lines)


def test_us_vendor_uses_month_first_dates(plans):
    us = next(plan for plan in plans if "us_date_month_first" in plan.anomalies)
    assert us.locale == "US"
    assert us.invoice_date.isoformat() == "2026-03-04"


def test_venue_without_a_cost_center(plans):
    missing = next(plan for plan in plans if "venue_no_cost_center" in plan.anomalies)
    assert missing.venue == "Kallang Tennis Centre"
    assert missing.vendor_id == "V011"


def test_seed_changes_clean_content_but_not_the_shape(plans):
    other = build_plans(43)
    assert len(other) == len(plans)
    assert [p.document_id for p in other] == [p.document_id for p in plans]
    assert other != plans


def test_negative_seed_is_refused():
    with pytest.raises(ValueError, match="non-negative"):
        build_plans(-1)


def test_plan_lookup_matches(plans):
    lookup = plan_by_id(42)
    assert len(lookup) == 57
    assert lookup["live-02"].anomalies == ("total_edited",)


def _total(plan):
    from generator.money import compute_totals

    if plan.total_override is not None:
        return plan.total_override
    totals = compute_totals(
        tuple(line.amount for line in plan.lines),
        gst_rate_percent=plan.gst_rate_percent,
        simplified=plan.simplified,
    )
    return totals.total


def test_only_planted_duplicates_share_a_vendor_and_total_within_a_week(plans):
    # R05 holds a vendor's second invoice for the same total within 7 days. All 57 go through
    # one inbox, so any such pair must be a planted duplicate, or the answer key is wrong.
    invoices = [
        p
        for p in plans
        if p.doc_type in {DocType.TAX_INVOICE, DocType.INVOICE, DocType.SIMPLIFIED_TAX_INVOICE}
    ]
    clashes = [
        (a.document_id, b.document_id)
        for i, a in enumerate(invoices)
        for b in invoices[i + 1 :]
        if a.vendor_id == b.vendor_id
        and _total(a) == _total(b)
        and abs((a.invoice_date - b.invoice_date).days) <= 7
        and not ({"resend", "duplicate_file"} & set(a.anomalies + b.anomalies))
    ]
    assert clashes == []
