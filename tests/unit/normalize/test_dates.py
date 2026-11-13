from datetime import date

import pytest

from invoiceflow.normalize import normalize_date


@pytest.mark.parametrize(
    "raw",
    ["12 Oct 2026", "12 October 2026", "12-Oct-2026", "12 Oct 26"],
)
def test_day_month_name_formats_are_not_ambiguous(raw):
    assert normalize_date(raw) == (date(2026, 10, 12), False)


def test_day_first_is_the_default_and_marks_ambiguity():
    assert normalize_date("12/10/2026") == (date(2026, 10, 12), False)
    assert normalize_date("12-10-2026") == (date(2026, 10, 12), False)
    assert normalize_date("12.10.2026") == (date(2026, 10, 12), False)


def test_us_locale_reads_month_first():
    assert normalize_date("12/10/2026", locale="US") == (date(2026, 12, 10), True)
    assert normalize_date("10/12/2026", locale="en_US") == (date(2026, 10, 12), True)


def test_a_clear_day_is_not_ambiguous():
    assert normalize_date("15/10/2026") == (date(2026, 10, 15), False)
    assert normalize_date("10/15/2026", locale="US") == (date(2026, 10, 15), False)


def test_iso_dates_are_unambiguous():
    assert normalize_date("2026-10-15") == (date(2026, 10, 15), False)
    assert normalize_date("2026/10/15") == (date(2026, 10, 15), False)


def test_month_first_name_format():
    assert normalize_date("Oct 12, 2026") == (date(2026, 10, 12), False)
    assert normalize_date("October 12 2026", locale="US") == (date(2026, 10, 12), False)


def test_empty_and_invalid_dates():
    assert normalize_date("") == (None, False)
    assert normalize_date("not a date") == (None, False)
    assert normalize_date("31/02/2026") == (None, False)
    assert normalize_date("2026-02-30") == (None, False)


def test_weekday_prefix_is_ignored():
    assert normalize_date("Monday, 12 Oct 2026") == (date(2026, 10, 12), False)


def test_a_day_first_vendor_is_not_ambiguous_even_when_both_parts_could_be_months():
    # A Singapore vendor prints day first, so 04/11/2026 means 4 November.
    assert normalize_date("04/11/2026", locale="SG") == (date(2026, 11, 4), False)


def test_a_month_first_vendor_is_ambiguous_only_if_swapping_changes_the_date():
    assert normalize_date("03/04/2026", locale="US") == (date(2026, 3, 4), True)
    assert normalize_date("03/03/2026", locale="US") == (date(2026, 3, 3), False)


def test_an_impossible_month_first_date_reads_day_first():
    # pre-usd-01: a US vendor printed 26/10/2026. Month 26 does not exist, so only one
    # reading is possible, and it is not ambiguous.
    assert normalize_date("26/10/2026", locale="US") == (date(2026, 10, 26), False)


def test_an_impossible_day_first_date_reads_month_first():
    assert normalize_date("10/26/2026", locale="SG") == (date(2026, 10, 26), False)
