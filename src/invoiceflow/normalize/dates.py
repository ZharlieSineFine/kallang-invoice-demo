"""Singapore date formats.

Day comes first for a Singapore vendor; a vendor with a US locale reads month first. An
``ambiguous`` flag is returned when the first two numeric components are both 1-12, because
the same printed string is a valid date either way. Month-name and ISO dates are never
ambiguous.
"""

from __future__ import annotations

import re
from datetime import date

from invoiceflow.normalize.text import clean_text

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_WEEKDAY = re.compile(
    r"^(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+",
    re.IGNORECASE,
)
_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_NUMERIC = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$")
_DAY_MONTH = re.compile(
    r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-.]+([a-z]+)[\s,.\-]+(\d{2,4})$",
    re.IGNORECASE,
)
_MONTH_DAY = re.compile(
    r"^([a-z]+)[\s\-.]*(\d{1,2})(?:st|nd|rd|th)?[\s,.\-]+(\d{2,4})$",
    re.IGNORECASE,
)


def month_first(locale: str | None) -> bool:
    """US vendors read month first; everyone else in this demo reads day first."""
    text = clean_text(locale) or "SG"
    key = text.casefold().replace("_", "-")
    return key in {"us", "usa", "en-us", "united states"} or key.startswith("en-us")


def _year(raw: str) -> int:
    year = int(raw)
    if len(raw) <= 2:
        return 2000 + year if year < 70 else 1900 + year
    return year


def _make_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_number(name: str) -> int | None:
    return _MONTHS.get(name.casefold())


def normalize_date(value: str | None, *, locale: str = "SG") -> tuple[date | None, bool]:
    """Return ``(date, ambiguous)``; ``(None, False)`` when the text is not a date."""
    text = clean_text(value)
    if text is None:
        return None, False
    text = _WEEKDAY.sub("", text).strip()

    match = _ISO.fullmatch(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return _make_date(year, month, day), False

    match = _NUMERIC.fullmatch(text)
    if match:
        first, second, raw_year = match.groups()
        # A day-first vendor always prints day first. Only a month-first vendor's date can
        # be misread by a Singapore reader, and only if swapping the parts changes it.
        ambiguous = (
            month_first(locale) and first != second and int(first) <= 12 and int(second) <= 12
        )
        year = _year(raw_year)
        if month_first(locale):
            month, day = int(first), int(second)
        else:
            day, month = int(first), int(second)
        parsed = _make_date(year, month, day)
        if parsed is None:
            # The vendor's usual order gives no real date (month 26), so the other order is
            # the only possible reading, and it is not ambiguous.
            return _make_date(year, day, month), False
        return parsed, ambiguous

    match = _DAY_MONTH.fullmatch(text)
    if match:
        day_raw, month_name, raw_year = match.groups()
        month = _month_number(month_name)
        if month is None:
            return None, False
        return _make_date(_year(raw_year), month, int(day_raw)), False

    match = _MONTH_DAY.fullmatch(text)
    if match:
        month_name, day_raw, raw_year = match.groups()
        month = _month_number(month_name)
        if month is None:
            return None, False
        return _make_date(_year(raw_year), month, int(day_raw)), False

    return None, False


def parse_date(value: str | None, *, locale: str = "SG") -> date | None:
    """Convenience wrapper when the ambiguity flag is not needed."""
    return normalize_date(value, locale=locale)[0]
