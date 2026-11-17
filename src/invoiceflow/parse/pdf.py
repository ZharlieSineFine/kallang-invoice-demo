"""Digital PDF text: pdfplumber words plus hidden-text classification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium

from invoiceflow.contracts import Word
from invoiceflow.parse.config import ParseConfig
from invoiceflow.parse.hidden import (
    NOT_VISIBLE,
    OFF_PAGE,
    TINY_FONT,
    WHITE_TEXT,
    word_from_pdfplumber,
    word_hidden_reasons,
)


def _raw_words(page: Any) -> list[dict[str, Any]]:
    return page.extract_words(extra_attrs=["size", "non_stroking_color"], return_chars=True)


def extract_pdf_words(page: Any, config: ParseConfig) -> tuple[Word, ...]:
    """Words from one pdfplumber page, with hidden words kept and marked."""
    page_bbox = tuple(page.bbox)
    raw_words = _raw_words(page)
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


@dataclass(frozen=True)
class HiddenPassage:
    """Consecutive hidden words on one line, with how they are hidden and where (PDF points,
    measured from the page's top-left corner; they may lie outside the page)."""

    text: str
    reasons: tuple[str, ...]
    font_size: float | None
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True)
class HiddenText:
    page_no: int
    width: float
    height: float
    passages: tuple[HiddenPassage, ...]


_SAME_LINE_PT = 2.0


def _passages(
    raw_words: Sequence[dict[str, Any]],
    page_bbox,
    config,
    unseen: frozenset[int] = frozenset(),
) -> tuple[HiddenPassage, ...]:
    passages: list[HiddenPassage] = []
    current: list[tuple[dict[str, Any], tuple[str, ...]]] = []

    def close() -> None:
        if not current:
            return
        words = [raw for raw, _ in current]
        found = {reason for _, reasons in current for reason in reasons}
        sizes = [float(raw["size"]) for raw in words if raw.get("size") is not None]
        passages.append(
            HiddenPassage(
                text=" ".join(str(raw["text"]).strip() for raw in words),
                reasons=tuple(
                    r for r in (TINY_FONT, WHITE_TEXT, OFF_PAGE, NOT_VISIBLE) if r in found
                ),
                font_size=min(sizes) if sizes else None,
                x0=min(float(raw["x0"]) for raw in words),
                top=min(float(raw["top"]) for raw in words),
                x1=max(float(raw["x1"]) for raw in words),
                bottom=max(float(raw["bottom"]) for raw in words),
            )
        )
        current.clear()

    position = -1  # the word's index among non-empty words, as in extract_pdf_words
    for raw in raw_words:
        if not str(raw.get("text") or "").strip():
            continue
        position += 1
        reasons = word_hidden_reasons(raw, page_bbox, config)
        if not reasons and position in unseen:
            reasons = (NOT_VISIBLE,)
        if not reasons:
            close()
            continue
        if current and abs(float(raw["top"]) - float(current[-1][0]["top"])) > _SAME_LINE_PT:
            close()
        current.append((raw, reasons))
    close()
    return tuple(passages)


def hidden_text_for_file(path: Path, page_no: int, config: ParseConfig) -> HiddenText | None:
    """The hidden words of one page of a stored upload, grouped into passages, with the
    reasons the parser marked them hidden. ``None`` for a missing page or a non-PDF upload
    (a scan has no text layer to hide words in)."""
    with Path(path).open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            return None
    with pdfplumber.open(path) as pdf:
        if not 1 <= page_no <= len(pdf.pages):
            return None
        page = pdf.pages[page_no - 1]
        raw_words = _raw_words(page)
        unseen = _unseen(path, page_no, page, config) if config.hidden_ocr_compare else frozenset()
        return HiddenText(
            page_no=page_no,
            width=float(page.width),
            height=float(page.height),
            passages=_passages(raw_words, tuple(page.bbox), config, unseen),
        )


def _unseen(path: Path, page_no: int, page: Any, config: ParseConfig) -> frozenset[int]:
    """The OCR comparison, exactly as the parser runs it on a text-layer page."""
    words = extract_pdf_words(page, config)
    if not check_text_layer(words, page, config).uses_text_layer:
        return frozenset()
    from invoiceflow.parse.images import render_page
    from invoiceflow.parse.visibility import unseen_words

    document = pdfium.PdfDocument(str(path))
    try:
        return unseen_words(words, render_page(document, page_no - 1, dpi=config.ocr_dpi))
    finally:
        document.close()
