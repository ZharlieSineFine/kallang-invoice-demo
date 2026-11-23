"""An inbox card names why an invoice waits for a person: its open rules, or the value limit."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.inbox import inbox_card
from invoiceflow.contracts import DocStatus
from invoiceflow.rules.router import limit_reason


def test_an_invoice_over_the_value_limit_says_so(clean_bundle):
    # Every check passed; only its size sends it to a person (CR-012), so it has no rule.
    doc = replace(
        clean_bundle.document,
        status=DocStatus.NEEDS_REVIEW,
        status_reason=limit_reason(Decimal("5000.00")),
        open_rules=(),
    )
    assert inbox_card(doc, {}).rules == ("S$5,000 or more",)


def test_rules_are_shown_as_before(clean_bundle):
    doc = replace(clean_bundle.document, status=DocStatus.NEEDS_REVIEW, open_rules=("R02",))
    assert inbox_card(doc, {}).rules == ("R02",)


def test_a_clean_auto_passed_invoice_has_no_reason(clean_bundle):
    assert inbox_card(clean_bundle.document, {}).rules == ()
