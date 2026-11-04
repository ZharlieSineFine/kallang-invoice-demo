"""Currency codes, including the Singapore ``S$`` shorthand."""

from __future__ import annotations

import re

from invoiceflow.normalize.text import clean_text

_SYMBOLS = {
    "S$": "SGD",
    "SGD": "SGD",
    "SINGAPOREDOLLAR": "SGD",
    "SINGAPOREDOLLARS": "SGD",
    "US$": "USD",
    "USD": "USD",
    "USDOLLAR": "USD",
    "A$": "AUD",
    "AUD": "AUD",
    "HK$": "HKD",
    "HKD": "HKD",
    "RM": "MYR",
    "MYR": "MYR",
    "RMB": "CNY",
    "CNY": "CNY",
    "¥": "JPY",
    "JPY": "JPY",
    "₹": "INR",
    "INR": "INR",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "$": "SGD",
}
_CODE = re.compile(r"^[A-Z]{3}$")


def normalize_currency(value: str | None) -> str | None:
    """Map a printed currency to an ISO 4217 code; unknown three-letter codes pass through."""
    text = clean_text(value)
    if text is None:
        return None
    key = text.upper().replace(" ", "")
    if key in _SYMBOLS:
        return _SYMBOLS[key]
    if _CODE.fullmatch(key):
        return key
    return None


def infer_currency(*amounts: str | None) -> str | None:
    """Infer the currency from an ``S$``/``SGD`` prefix on a printed amount."""
    for raw in amounts:
        text = clean_text(raw)
        if text is None:
            continue
        upper = text.upper()
        for prefix, code in (("S$", "SGD"), ("SGD", "SGD"), ("US$", "USD"), ("USD", "USD")):
            if upper.startswith(prefix):
                return code
    return None
