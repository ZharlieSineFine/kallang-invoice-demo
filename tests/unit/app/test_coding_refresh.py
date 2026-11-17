"""Coding lines follow a reviewer's corrections, and keep a reviewer's own coding choices."""

from __future__ import annotations

from decimal import Decimal

from app.coding_refresh import coding_changed, keep_reviewer_choices
from app.models import CodingRow
from invoiceflow.contracts import CodingLine, CodingSource


def _fresh(net: str, tax: str, lines=(1, 2)) -> CodingLine:
    return CodingLine(
        line_no=1,
        gl_account="610200",
        cost_center="KG1100",
        tax_code="TX",
        net_amount=Decimal(net),
        tax_amount=Decimal(tax),
        description="Equipment rental",
        source_line_nos=lines,
        coding_source=CodingSource.VENDOR_DEFAULT,
    )


def _row(net: str, tax: str, source=CodingSource.VENDOR_DEFAULT, lines=(1, 2), gl="610200"):
    return CodingRow(
        line_no=1,
        gl_account=gl,
        cost_center="KG1100",
        tax_code="TX",
        net_amount=Decimal(net),
        tax_amount=Decimal(tax),
        description="Equipment rental",
        coding_source=source,
        source_line_nos=lines,
    )


def test_new_amounts_count_as_a_change():
    assert coding_changed((_fresh("743.12", "66.88"),), (_row("523.12", "66.88"),))


def test_same_amounts_and_coding_are_not_a_change():
    assert not coding_changed((_fresh("743.12", "66.88"),), (_row("743.12", "66.88"),))


def test_a_different_number_of_lines_is_a_change():
    assert coding_changed((_fresh("743.12", "66.88"),), ())


def test_a_reviewers_gl_choice_is_kept_while_the_amounts_update():
    current = (_row("523.12", "66.88", source=CodingSource.REVIEWER, gl="610100"),)
    (line,) = keep_reviewer_choices((_fresh("743.12", "66.88"),), current)
    assert line.gl_account == "610100"
    assert line.coding_source is CodingSource.REVIEWER
    assert (line.net_amount, line.tax_amount) == (Decimal("743.12"), Decimal("66.88"))


def test_a_reviewer_choice_on_other_invoice_lines_is_not_copied():
    current = (_row("100.00", "9.00", source=CodingSource.REVIEWER, gl="610100", lines=(3,)),)
    (line,) = keep_reviewer_choices((_fresh("743.12", "66.88"),), current)
    assert line.gl_account == "610200"
    assert line.coding_source is CodingSource.VENDOR_DEFAULT
