"""The OCR comparison: which text-layer words a person cannot see on the rendered page.

Every hiding trick ends the same way: the word is in the PDF's text layer but not on the
printed page. So render the page, read it with Tesseract the way a person sees it (black
ink on white paper, no contrast stretching, which would bring faint text back), and mark
text-layer words that OCR does not find at their position. OCR misses some real words, so
only runs of missing words on one line count, short runs are ignored, and each run gets a
second look: OCR on a crop of just that area. Visible text is easy to read in a small
crop; hidden text is still not there.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

import pytesseract
from PIL import Image
from pytesseract import Output

from invoiceflow.contracts import BBox, Word

_PAD = 0.004  # page fractions: how far an OCR word may sit from the text-layer word
_SAME_LINE = 0.006
_CROP_MARGIN = 0.01
_MATCH_RATIO = 0.75  # a misread letter or two ('trarsfer'); 'account' is not 'without'
# A pixel lighter than this (0 = black, 255 = white) counts as paper. Tesseract picks its own
# cut-off per image, and on a crop of faint text alone it would read text a person cannot;
# a fixed cut-off keeps the question "can a person read this?". Text at #c8c8c8 or lighter
# on white is below WCAG's lowest contrast for any text, so it counts as unreadable.
INK_CUTOFF = 200


def _as_seen(image: Image.Image) -> Image.Image:
    """Black ink on white paper, as a person reads the page."""
    return image.convert("L").point(lambda value: 0 if value < INK_CUTOFF else 255)


# OCR's usual lookalikes ("AI" read as "al", "O" as "0"), compared as one character.
_LOOKALIKE = str.maketrans({"l": "i", "1": "i", "0": "o", "5": "s", "8": "b"})
# A run of missing words shorter than this many letters and digits is OCR noise; it is too
# short to carry an instruction.
MIN_RUN_CHARS = 4


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower()).translate(_LOOKALIKE)


def _ocr_boxes(
    image: Image.Image, *, psm: int | None = None, frame: BBox | None = None
) -> tuple[tuple[str, BBox], ...]:
    """OCR words with page-fraction boxes. ``frame`` is where ``image`` sits on the page
    when it is a crop."""
    config = f"--psm {psm}" if psm is not None else ""
    data = pytesseract.image_to_data(_as_seen(image), output_type=Output.DICT, config=config)
    width, height = image.size
    frame = frame or BBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
    span_x, span_y = frame.x1 - frame.x0, frame.y1 - frame.y0
    found = []
    for index, raw in enumerate(data["text"]):
        text = _norm(raw or "")
        if not text:
            continue
        left, top = data["left"][index], data["top"][index]
        right, bottom = left + data["width"][index], top + data["height"][index]
        box = BBox(
            x0=min(1.0, frame.x0 + span_x * left / width),
            y0=min(1.0, frame.y0 + span_y * top / height),
            x1=min(1.0, frame.x0 + span_x * right / width),
            y1=min(1.0, frame.y0 + span_y * bottom / height),
        )
        found.append((text, box))
    return tuple(found)


def _near(a: BBox, b: BBox) -> bool:
    return not (
        b.x1 < a.x0 - _PAD or b.x0 > a.x1 + _PAD or b.y1 < a.y0 - _PAD or b.y0 > a.y1 + _PAD
    )


def _similar(wanted: str, read: str) -> bool:
    if wanted == read:
        return True
    contained = min(len(wanted), len(read)) >= 3 and (wanted in read or read in wanted)
    return contained or SequenceMatcher(None, wanted, read).ratio() >= _MATCH_RATIO


def _seen(word: Word, ocr: Sequence[tuple[str, BBox]]) -> bool:
    wanted = _norm(word.text)
    if not wanted:
        return True
    return any(_near(word.bbox, box) and _similar(wanted, text) for text, box in ocr)


def _runs(words: Sequence[Word], missing: set[int]) -> list[list[int]]:
    """Consecutive missing words on one line; a single seen word between two missing runs on
    the same line joins them (OCR sometimes matches it to a neighbor)."""
    runs: list[list[int]] = []
    for index in sorted(missing):
        last = runs[-1][-1] if runs else None
        same_line = (
            last is not None and abs(words[last].bbox.y0 - words[index].bbox.y0) < _SAME_LINE
        )
        if same_line and index - last <= 2:
            runs[-1].extend(range(last + 1, index + 1))
        else:
            runs.append([index])
    return runs


def _found_in_crop(image: Image.Image, group: Sequence[Word]) -> bool:
    """Second look: OCR just the area of a missed run. True when at least half of its words
    are read at their own positions (real text printed nearby does not count)."""
    width, height = image.size
    frame = BBox(
        x0=max(0.0, min(word.bbox.x0 for word in group) - _CROP_MARGIN),
        y0=max(0.0, min(word.bbox.y0 for word in group) - _CROP_MARGIN),
        x1=min(1.0, max(word.bbox.x1 for word in group) + _CROP_MARGIN),
        y1=min(1.0, max(word.bbox.y1 for word in group) + _CROP_MARGIN),
    )
    left, top = int(frame.x0 * width), int(frame.y0 * height)
    right, bottom = int(frame.x1 * width), int(frame.y1 * height)
    if right <= left or bottom <= top:
        return False
    ocr = _ocr_boxes(image.crop((left, top, right, bottom)), psm=6, frame=frame)
    wanted = [word for word in group if _norm(word.text)]
    return bool(wanted) and sum(_seen(word, ocr) for word in wanted) >= len(wanted) / 2


def unseen_words(words: Sequence[Word], image: Image.Image) -> frozenset[int]:
    """Indices of text-layer words (not already hidden) a person cannot see on ``image``,
    the page rendered at OCR resolution."""
    ocr = _ocr_boxes(image)
    missing = {i for i, word in enumerate(words) if not word.hidden and not _seen(word, ocr)}
    flagged: set[int] = set()
    for run in _runs(words, missing):
        group = [words[i] for i in run]
        if sum(len(_norm(word.text)) for word in group) < MIN_RUN_CHARS:
            continue
        if not _found_in_crop(image, group):
            flagged.update(run)
    return frozenset(flagged)


def mark_unseen(words: Sequence[Word], image: Image.Image) -> tuple[Word, ...]:
    unseen = unseen_words(words, image)
    return tuple(
        word.model_copy(update={"hidden": True}) if index in unseen else word
        for index, word in enumerate(words)
    )
