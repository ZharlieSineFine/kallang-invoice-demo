"""Digital PDF text: pdfplumber words plus hidden-text classification."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from invoiceflow.contracts import Word
from invoiceflow.parse.config import ParseConfig
from invoiceflow.parse.hidden import word_from_pdfplumber


def extract_pdf_words(page: Any, config: ParseConfig) -> tuple[Word, ...]:
    """Words from one pdfplumber page, with hidden words kept and marked."""
    page_bbox = tuple(page.bbox)
    raw_words = page.extract_words(
        extra_attrs=["size", "non_stroking_color"],
        return_chars=True,
    )
    words: list[Word] = []
    for raw in raw_words:
        word = word_from_pdfplumber(raw, page_bbox, config)
        if word is not None:
            words.append(word)
    return tuple(words)


def visible_char_count(words: Sequence[Word]) -> int:
    return sum(len(word.text) for word in words if not word.hidden)


def hidden_words(words: Sequence[Word]) -> tuple[Word, ...]:
    return tuple(word for word in words if word.hidden)
