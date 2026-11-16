"""Finding a field's printed value, header or line item, for the fix panel and the backend."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.fields import LineField, line_field, printed_value, with_line_value


def test_line_field_names_are_parsed():
    assert line_field("line_items[2].amount") == LineField(2, "amount")
    assert line_field("subtotal") is None
    assert line_field("line_items[x].amount") is None


def test_printed_value_reads_header_and_line_fields(mismatch_bundle):
    assert printed_value(mismatch_bundle, "subtotal") == mismatch_bundle.field("subtotal").value_raw
    first = mismatch_bundle.line_items[0]
    assert printed_value(mismatch_bundle, "line_items[0].amount") == str(first.amount)
    assert printed_value(mismatch_bundle, "line_items[0].description") == first.description


@pytest.mark.parametrize("name", ["nope", "line_items[99].amount", "line_items[0].colour"])
def test_printed_value_refuses_unknown_fields(mismatch_bundle, name):
    with pytest.raises(ValueError, match="not a header field"):
        printed_value(mismatch_bundle, name)


def test_with_line_value_changes_one_value_of_one_line(mismatch_bundle):
    items = with_line_value(mismatch_bundle.line_items, LineField(0, "amount"), "500.00")
    assert items[0].amount == Decimal("500.00")
    assert items[0].description == mismatch_bundle.line_items[0].description
    assert [item.amount for item in items[1:]] == [
        item.amount for item in mismatch_bundle.line_items[1:]
    ]
    assert len(items) == len(mismatch_bundle.line_items)


def test_with_line_value_refuses_a_non_number_for_an_amount(mismatch_bundle):
    with pytest.raises(ValueError, match=r"not an amount|not a number"):
        with_line_value(mismatch_bundle.line_items, LineField(0, "amount"), "abc")


def test_a_header_field_the_model_did_not_read_is_empty_not_unknown(mismatch_bundle):
    from invoiceflow.contracts import HEADER_FIELDS

    stored = {field.name for field in mismatch_bundle.fields}
    missing = next(name for name in HEADER_FIELDS if name not in stored)
    assert printed_value(mismatch_bundle, missing) == ""
