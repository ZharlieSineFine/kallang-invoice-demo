"""Amounts and percentages.

Printed money is a string: ``S$1,090.00``, ``SGD 1 090.00``, ``(1,090.00)``. Everything is
parsed to ``Decimal``; floats are never accepted. Money fields are rounded half-up to cents
through ``money()`` from the contracts.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from invoiceflow.contracts.money import money
from invoiceflow.normalize.text import clean_text

_CURRENCY_PREFIX = re.compile(
    r"^(?:S\$|SGD|US\$|USD|A\$|AUD|HK\$|HKD|RM|MYR|CNY|RMB|JPY|INR|EUR|GBP|"
    r"[$€£¥₹฿])\s*",
    re.IGNORECASE,
)
_CURRENCY_SUFFIX = re.compile(
    r"\s*(?:S\$|SGD|US\$|USD|A\$|AUD|HK\$|HKD|RM|MYR|CNY|RMB|JPY|INR|EUR|GBP)$",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_SEPARATORS = re.compile(r"[\s,']")
_NEGATIVE_SIGNS = {"-", "\u2212", "\u2013"}


def _strip_money_decorations(value: str) -> tuple[str, bool]:
    """Remove currency marks, parentheses, signs, and thousands separators."""
    text = clean_text(value) or ""
    negative = False

    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    text = _CURRENCY_PREFIX.sub("", text).strip()
    text = _CURRENCY_SUFFIX.sub("", text).strip()

    if text[:1] in _NEGATIVE_SIGNS:
        negative = True
        text = text[1:].strip()
    elif text[:1] == "+":
        text = text[1:].strip()
    elif text[-1:] in _NEGATIVE_SIGNS:
        negative = True
        text = text[:-1].strip()

    compact = re.sub(r"[\s']", "", text)
    if "," in compact and not _GROUPED.fullmatch(compact):
        return "", negative
    return _SEPARATORS.sub("", compact), negative


def parse_amount(value: str | None) -> Decimal | None:
    """Parse a printed money amount without rounding. Returns None when it is not money."""
    if value is None:
        return None
    text, negative = _strip_money_decorations(value)
    if not text or not _NUMBER.fullmatch(text):
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def normalize_amount(value: str | None) -> Decimal | None:
    """Parse a printed money amount and round half-up to two decimal places."""
    amount = parse_amount(value)
    return money(amount) if amount is not None else None


def normalize_percent(value: str | None) -> Decimal | None:
    """Parse ``9%`` or ``9.00 %`` as ``Decimal('9')``; other text is not a percentage."""
    text = clean_text(value)
    if not text or "%" not in text:
        return None
    number = text.replace("%", "").strip()
    compact = re.sub(r"[\s']", "", number)
    if "," in compact and not _GROUPED.fullmatch(compact):
        return None
    number = _SEPARATORS.sub("", compact)
    if not _NUMBER.fullmatch(number):
        return None
    try:
        return Decimal(number)
    except InvalidOperation:
        return None
