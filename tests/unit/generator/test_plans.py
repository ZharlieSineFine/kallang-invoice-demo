"""The 50-document composition, seeded content, and anomaly assignment."""

from __future__ import annotations

from decimal import Decimal

import pytest

from generator.plans import (
    ANOMALY_RULES,
    AV_1080,
    build_plans,
    plan_by_id,
)
from invoiceflow.contracts import DocType


def test_counts_match_the_build_plan(plans):
    counts = {}
    for plan in plans:
        counts[plan.set_name] = counts.get(plan.set_name, 0) + 1
    assert counts == {"pre": 36, "live": 4, "benchmark": 10}
    assert len(plans) == 50


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


def test_live_set_has_the_slide_three_invoice(plans):
    live = {plan.document_id: plan for plan in plans if plan.set_name == "live"}
    assert set(live) == {"live-01", "live-02", "live-03", "live-04"}
    assert live["live-01"].anomalies == ()
    edited = live["live-02"]
    assert edited.anomalies == ("total_edited",)
    assert edited.total_override == Decimal("1090.00")
    assert edited.lines == AV_1080
    assert sum(line.amount for line in edited.lines) == Decimal("1080.00")


def test_live_set_covers_clean_total_bank_and_hidden(plans):
    live = [plan for plan in plans if plan.set_name == "live"]
    assert {anomaly for plan in live for anomaly in plan.anomalies} == {
        "total_edited",
        "bank_account_changed",
        "hidden_instructions",
    }


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
    b_invoices = [
        plan
        for plan in plans
        if plan.template.startswith("B") and plan.set_name in {"pre", "benchmark"}
    ]
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
    assert duplicate.set_name == original.set_name

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
    assert len(lookup) == 50
    assert lookup["live-02"].anomalies == ("total_edited",)
