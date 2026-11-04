"""Where the boxes go: pure geometry, word lookup, and an image overlay for Streamlit.

Boxes are page fractions measured from the top-left (the contract in
``docs/CONTRACTS.md``). The functions here never mutate a page or a bundle; they return new
objects and, for the image, a new ``PIL.Image``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw
from rapidfuzz import fuzz

from app.models import FieldRow, FindingRow, LineItemRow
from invoiceflow.contracts import BBox, Confidence, MatchType, PageText, Word

PASSED = "#2e7d32"
FUZZY = "#f9a825"
FLAGGED = "#c62828"
SELECTED = "#1565c0"
_STATUS_COLOR = {"passed": PASSED, "fuzzy": FUZZY, "flagged": FLAGGED}
_TOKEN = re.compile(r"\S+")


@dataclass(frozen=True)
class BoxSpec:
    field: str
    bbox: BBox
    status: str
    label: str
    selected: bool = False

    @property
    def color(self) -> str:
        return SELECTED if self.selected else _STATUS_COLOR[self.status]


@dataclass(frozen=True)
class TextMatch:
    bbox: BBox | None
    match_type: MatchType
    score: float


def field_status(
    field_name: str,
    findings: Sequence[FindingRow],
    *,
    match_type: MatchType = MatchType.EXACT,
    confidence: Confidence = Confidence.HIGH,
) -> str:
    """Red for flagged, amber for fuzzy/medium, green for passed."""
    if any(
        finding.field == field_name or (finding.field or "").startswith(f"{field_name}.")
        for finding in findings
    ):
        return "flagged"
    if match_type is MatchType.FUZZY or confidence is Confidence.MEDIUM:
        return "fuzzy"
    if match_type is MatchType.NONE or confidence is Confidence.LOW:
        return "fuzzy"
    return "passed"


def scale_bbox(
    bbox: BBox, width: int, height: int, *, padding: float = 0.0
) -> tuple[int, int, int, int]:
    """Fractional box -> integer pixel box, clamped to the image."""
    if width <= 0 or height <= 0:
        raise ValueError("image needs a positive width and height")
    x0 = round(max(0.0, bbox.x0 - padding) * width)
    y0 = round(max(0.0, bbox.y0 - padding) * height)
    x1 = round(min(1.0, bbox.x1 + padding) * width)
    y1 = round(min(1.0, bbox.y1 + padding) * height)
    return x0, y0, max(x0, x1), max(y0, y1)


def crop_region(
    bbox: BBox, width: int, height: int, *, margin: float = 0.02
) -> tuple[int, int, int, int]:
    """A zoom crop around a box, with a small margin so the words are not clipped."""
    x0, y0, x1, y1 = scale_bbox(bbox, width, height, padding=margin)
    # Keep a little extra room above and below for ascenders/descenders.
    vertical = max(8, round((y1 - y0) * 0.6))
    horizontal = max(8, round((x1 - x0) * 0.2))
    return (
        max(0, x0 - horizontal),
        max(0, y0 - vertical),
        min(width, x1 + horizontal),
        min(height, y1 + vertical),
    )


def words_in_bbox(page: PageText, bbox: BBox) -> tuple[Word, ...]:
    """Visible words whose centre lies inside the box."""
    found = []
    for word in page.visible_words:
        cx = (word.bbox.x0 + word.bbox.x1) / 2
        cy = (word.bbox.y0 + word.bbox.y1) / 2
        if bbox.x0 <= cx <= bbox.x1 and bbox.y0 <= cy <= bbox.y1:
            found.append(word)
    return tuple(found)


def text_in_bbox(page: PageText, bbox: BBox) -> str:
    words = sorted(words_in_bbox(page, bbox), key=lambda w: (round(w.bbox.y0, 3), w.bbox.x0))
    return " ".join(w.text for w in words)


def _same_token(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def find_text_box(page: PageText, text: str | None) -> TextMatch:
    """Locate a printed value on a page, returning the union of its words' boxes.

    The first pass is an exact token sequence. A single token that is close but not equal
    (OCR noise) is reported as FUZZY when rapidfuzz scores it at least 90.
    """
    tokens = _TOKEN.findall((text or "").strip())
    if not tokens:
        return TextMatch(None, MatchType.NONE, 0.0)
    words = sorted(page.visible_words, key=lambda w: (round(w.bbox.y0, 3), w.bbox.x0))
    width = len(tokens)
    for start in range(0, len(words) - width + 1):
        window = words[start : start + width]
        if all(_same_token(word.text, token) for word, token in zip(window, tokens, strict=True)):
            box = window[0].bbox
            for word in window[1:]:
                box = box.union(word.bbox)
            return TextMatch(box, MatchType.EXACT, 100.0)
    if width == 1:
        best = max(words, key=lambda w: fuzz.ratio(w.text, tokens[0]), default=None)
        if best is not None:
            score = float(fuzz.ratio(best.text, tokens[0]))
            if score >= 90:
                return TextMatch(best.bbox, MatchType.FUZZY, score)
    return TextMatch(None, MatchType.NONE, 0.0)


def _line_item_boxes(
    page: PageText,
    line_items: Sequence[LineItemRow],
    findings: Sequence[FindingRow],
) -> list[BoxSpec]:
    boxes: list[BoxSpec] = []
    for index, item in enumerate(line_items):
        prefix = f"line_items[{index}]"
        for suffix, value in (
            ("description", item.description),
            ("amount", f"{item.amount:,.2f}" if item.amount is not None else None),
        ):
            match = find_text_box(page, value)
            if match.bbox is None and suffix == "amount" and item.amount is not None:
                match = find_text_box(page, f"{item.amount:.2f}")
            if match.bbox is None:
                continue
            field_name = f"{prefix}.{suffix}"
            boxes.append(
                BoxSpec(
                    field=field_name,
                    bbox=match.bbox,
                    status=field_status(
                        field_name,
                        findings,
                        match_type=match.match_type,
                        confidence=Confidence.HIGH,
                    ),
                    label=f"{field_name}: {value}",
                )
            )
    return boxes


def page_boxes(
    page: PageText,
    fields: Sequence[FieldRow],
    line_items: Sequence[LineItemRow],
    findings: Sequence[FindingRow],
    *,
    selected: str | None = None,
) -> tuple[BoxSpec, ...]:
    """Every box to draw on one page, with the selected field marked."""
    boxes: list[BoxSpec] = []
    for field in fields:
        if field.page_no != page.page_no or field.bbox is None:
            continue
        status = field_status(
            field.name,
            findings,
            match_type=field.match_type,
            confidence=field.confidence,
        )
        boxes.append(
            BoxSpec(
                field=field.name,
                bbox=field.bbox,
                status=status,
                label=f"{field.name}: {field.value_raw or ''}".strip(),
                selected=field.name == selected,
            )
        )
    for box in _line_item_boxes(page, line_items, findings):
        boxes.append(
            BoxSpec(
                field=box.field,
                bbox=box.bbox,
                status=box.status,
                label=box.label,
                selected=box.field == selected,
            )
        )
    return tuple(boxes)


def word_boxes(page: PageText, *, hidden_only: bool = False) -> tuple[BoxSpec, ...]:
    """A box per word the reader found; text a person cannot see is red."""
    return tuple(
        BoxSpec(
            field=f"word-{index}",
            bbox=word.bbox,
            status="flagged" if word.hidden else "passed",
            label=word.text,
        )
        for index, word in enumerate(page.words)
        if word.hidden or not hidden_only
    )


def draw_boxes(
    image: Image.Image,
    boxes: Iterable[BoxSpec],
    *,
    selected: str | None = None,
    line_width: int = 3,
) -> Image.Image:
    """Return a new image with coloured outlines; the selected box is thicker and blue."""
    canvas = image.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas)
    for box in boxes:
        x0, y0, x1, y1 = scale_bbox(box.bbox, canvas.width, canvas.height)
        width = 6 if (box.selected or box.field == selected) else line_width
        draw.rectangle((x0, y0, x1, y1), outline=box.color, width=width)
    return canvas


def load_page_text(path: str | Path) -> PageText:
    """Read ``page-1.words.json``; the fixture format is the ``PageText`` contract."""
    return PageText.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
