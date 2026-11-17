"""Hidden-word detection from pdfplumber character data.

A word is evidence-hidden when any of its characters is painted near-white, is smaller
than the configured font size, or sits outside the visible page. Hidden words stay in
``PageText.words`` but never reach the model prompt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from invoiceflow.contracts import BBox, Word
from invoiceflow.parse.config import ParseConfig

_EPSILON = 0.01


def normalize_box(
    x0: float, top: float, x1: float, bottom: float, page_bbox: Sequence[float]
) -> BBox:
    """Turn PDF points into page fractions, clamped to the visible page."""
    left, page_top, right, page_bottom = (float(value) for value in page_bbox)
    width = right - left
    height = page_bottom - page_top
    x_start = _fraction(min(x0, x1), left, width)
    x_end = _fraction(max(x0, x1), left, width)
    y_start = _fraction(min(top, bottom), page_top, height)
    y_end = _fraction(max(top, bottom), page_top, height)
    return BBox(x0=x_start, y0=y_start, x1=x_end, y1=y_end)


def _fraction(value: float, origin: float, span: float) -> float:
    if span <= 0:
        return 0.0
    return min(1.0, max(0.0, (value - origin) / span))


def is_near_white(color: Any, min_lightness: float) -> bool:
    """True for white and near-white fills in gray, RGB, or CMYK."""
    values = _color_components(color)
    if not values:
        return False
    if len(values) == 1:
        return values[0] >= min_lightness
    if len(values) == 3:
        return min(values) >= min_lightness
    if len(values) == 4:
        # CMYK: white is (0, 0, 0, 0), so every ink channel must be near zero.
        return max(values) <= 1.0 - min_lightness
    return False


def _color_components(color: Any) -> tuple[float, ...] | None:
    if color is None:
        return None
    if isinstance(color, str):
        named = {"white": (1.0, 1.0, 1.0), "black": (0.0, 0.0, 0.0)}
        return named.get(color.strip().lower())
    if isinstance(color, (int, float)):
        values = (float(color),)
    elif isinstance(color, (tuple, list)):
        try:
            values = tuple(float(component) for component in color)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if not values:
        return None
    if any(component > 1.0 for component in values):
        values = tuple(component / 255.0 for component in values)
    return values


def is_off_page(
    x0: float, top: float, x1: float, bottom: float, page_bbox: Sequence[float]
) -> bool:
    """True when the box lies entirely outside the visible page rectangle."""
    left, page_top, right, page_bottom = (float(value) for value in page_bbox)
    return (
        x1 <= left + _EPSILON
        or x0 >= right - _EPSILON
        or bottom <= page_top + _EPSILON
        or top >= page_bottom - _EPSILON
    )


# Why a character (or word) is hidden. One function decides, so the parser's hidden flag and
# the review screen's explanation can never disagree.
TINY_FONT = "tiny_font"
WHITE_TEXT = "white_text"
OFF_PAGE = "off_page"
# Found by the OCR comparison (parse.visibility): in the text layer, not on the printed page.
NOT_VISIBLE = "not_visible"


def hidden_reasons(
    item: Mapping[str, Any], page_bbox: Sequence[float], config: ParseConfig
) -> tuple[str, ...]:
    """The hiding tricks one pdfplumber character or word uses; empty when it is visible."""
    reasons: list[str] = []
    size = _as_float(item.get("size"))
    if size is not None and size < config.hidden_max_font_size_pt:
        reasons.append(TINY_FONT)
    if is_near_white(item.get("non_stroking_color"), config.hidden_min_fill_lightness):
        reasons.append(WHITE_TEXT)
    if _word_box_is_off_page(item, page_bbox):
        reasons.append(OFF_PAGE)
    return tuple(reasons)


def word_hidden_reasons(
    raw: Mapping[str, Any], page_bbox: Sequence[float], config: ParseConfig
) -> tuple[str, ...]:
    """The reasons across a word's characters (or the word itself when it has none)."""
    chars = raw.get("chars")
    if isinstance(chars, Sequence) and not isinstance(chars, (str, bytes)) and chars:
        found = {reason for char in chars for reason in hidden_reasons(char, page_bbox, config)}
        return tuple(reason for reason in (TINY_FONT, WHITE_TEXT, OFF_PAGE) if reason in found)
    return hidden_reasons(raw, page_bbox, config)


def char_is_hidden(
    char: Mapping[str, Any], page_bbox: Sequence[float], config: ParseConfig
) -> bool:
    return bool(hidden_reasons(char, page_bbox, config))


def raw_word_is_hidden(
    raw: Mapping[str, Any], page_bbox: Sequence[float], config: ParseConfig
) -> bool:
    """Hidden test for a pdfplumber word that has no per-character data."""
    return bool(hidden_reasons(raw, page_bbox, config))


def _word_box_is_off_page(raw: Mapping[str, Any], page_bbox: Sequence[float]) -> bool:
    x0 = _as_float(raw.get("x0"))
    top = _as_float(raw.get("top"))
    x1 = _as_float(raw.get("x1"))
    bottom = _as_float(raw.get("bottom"))
    if None in (x0, top, x1, bottom):
        return False
    return is_off_page(x0, top, x1, bottom, page_bbox)  # type: ignore[arg-type]


def word_from_pdfplumber(
    raw: Mapping[str, Any], page_bbox: Sequence[float], config: ParseConfig
) -> Word | None:
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    hidden = bool(word_hidden_reasons(raw, page_bbox, config))
    bbox = normalize_box(
        _as_float(raw.get("x0")) or 0.0,
        _as_float(raw.get("top")) or 0.0,
        _as_float(raw.get("x1")) or 0.0,
        _as_float(raw.get("bottom")) or 0.0,
        page_bbox,
    )
    return Word(text=text, bbox=bbox, conf=None, hidden=hidden)


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
