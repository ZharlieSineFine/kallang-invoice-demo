"""Text cleanup shared by normalization and matching.

NFKC folds full-width characters, zero-width characters are removed, runs of whitespace
collapse to one space, and ``normalize_text`` case-folds for comparisons. ``clean_text``
keeps the printed case for values that are stored in a normalized invoice.
"""

from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_WHITESPACE = re.compile(r"\s+")


def clean_text(value: str | None) -> str | None:
    """NFKC, zero-width removal, and collapsed whitespace; case is preserved."""
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", value)
    text = _ZERO_WIDTH.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text or None


def normalize_text(value: str | None) -> str:
    """``clean_text`` plus case folding, for keys and fuzzy comparisons."""
    text = clean_text(value)
    return text.casefold() if text else ""


# A hyphen, dash, or slash, with any spaces around it. Spaces there never carry meaning in a
# reference, but OCR often adds them ("GSH- 2026-9004").
_SPACED_SEPARATOR = re.compile(r"\s*([-/\u2010-\u2015\u2212])\s*")
_NOT_ALPHANUMERIC = re.compile(r"[^0-9A-Z]")


def clean_reference(value: str | None) -> str | None:
    """``clean_text``, then remove spaces around hyphens, dashes, and slashes.

    Only those spaces go: "INV 2026 01" keeps its spaces, and case is kept, so the stored
    value is still what the invoice printed.
    """
    text = clean_text(value)
    return _SPACED_SEPARATOR.sub(r"\1", text) if text else None


def invoice_number_key(value: str | None) -> str:
    """The key duplicate checks compare: letters and digits only, uppercase.

    "GSH- 2026-9004", "gsh 2026 9004", and "GSH/2026/9004" are one invoice. A different
    character ("9OO4" against "9004") is not folded, because it can change meaning.
    """
    return _NOT_ALPHANUMERIC.sub("", (clean_text(value) or "").upper())


REFERENCE_CLEANUP_REASON = "spaces around a hyphen or slash removed (a common OCR slip)"


def reference_cleanup(printed: str | None) -> tuple[str, str] | None:
    """``(printed, cleaned)`` when ``clean_reference`` changed more than outer spaces, else
    ``None``. Feeds the audit event and the on-screen note."""
    cleaned = clean_reference(printed)
    if printed is None or cleaned is None or cleaned == clean_text(printed):
        return None
    return printed, cleaned
