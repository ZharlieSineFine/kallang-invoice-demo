"""Digital PDF text: pdfplumber words plus hidden-text classification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber

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


@dataclass(frozen=True)
class TextLayerCheck:
    """The parser's first decision for a page: read its text layer, or OCR the page image.

    Only visible characters count, so white or 1 pt text cannot make a scan look digital.
    """

    visible_chars: int
    min_chars: int  # ``scanned_page_min_chars`` in config/rules.yaml
    rotation: int = 0
    is_pdf: bool = True  # an image upload has no text layer at all

    @property
    def is_upright(self) -> bool:
        return self.rotation == 0

    @property
    def uses_text_layer(self) -> bool:
        return self.is_pdf and self.visible_chars >= self.min_chars and self.is_upright


def check_text_layer(words: Sequence[Word], page: Any, config: ParseConfig) -> TextLayerCheck:
    return TextLayerCheck(
        visible_chars=visible_char_count(words),
        min_chars=config.scanned_page_min_chars,
        rotation=int(getattr(page, "rotation", 0) or 0),
    )


def text_layer_check_for_file(
    path: Path, page_no: int, config: ParseConfig
) -> TextLayerCheck | None:
    """Run the same check on a stored upload, to show why a page was read the way it was.
    ``None`` when the page does not exist."""
    with Path(path).open("rb") as handle:
        is_pdf = handle.read(5) == b"%PDF-"
    if not is_pdf:
        if page_no != 1:
            return None
        return TextLayerCheck(
            visible_chars=0, min_chars=config.scanned_page_min_chars, is_pdf=False
        )
    with pdfplumber.open(path) as pdf:
        if not 1 <= page_no <= len(pdf.pages):
            return None
        page = pdf.pages[page_no - 1]
        return check_text_layer(extract_pdf_words(page, config), page, config)
