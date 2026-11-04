"""Identifiers: uppercase, with spaces and hyphens removed.

``M2-1234567-8`` and ``M212345678`` are the same ID. The function is deliberately narrow:
it removes whitespace and hyphen-like characters, not every punctuation mark. Matching code
that has to survive a label prefix uses its own alphanumeric key.
"""

from __future__ import annotations

import re

from invoiceflow.normalize.text import clean_text

_ID_SEPARATORS = re.compile(r"[\s\-\u2010\u2011\u2012\u2013\u2014\u2212]")
_ID_LABEL = re.compile(
    r"^(?:uen|gst\s*reg(?:istration)?\s*(?:no|number)?|"
    r"company\s*reg(?:istration)?\s*(?:no|number)?|reg\s*no)\s*[:#]?\s*",
    re.IGNORECASE,
)


def normalize_id(value: str | None) -> str | None:
    """Uppercase an identifier and remove spaces and hyphens."""
    text = clean_text(value)
    if text is None:
        return None
    normalized = _ID_SEPARATORS.sub("", text).upper()
    return normalized or None


def strip_id_label(value: str | None) -> str | None:
    """Drop a leading ``UEN:`` / ``GST Reg No:`` label before normalizing."""
    text = clean_text(value)
    if text is None:
        return None
    return _ID_LABEL.sub("", text).strip() or None


def normalized_labeled_id(value: str | None) -> str | None:
    return normalize_id(strip_id_label(value))
