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
