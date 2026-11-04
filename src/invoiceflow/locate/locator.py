"""Find each extracted value on the page.

The search index is every run of 1-8 consecutive visible words on a page, allowing a run to
cross at most two line breaks. Runs are compared in three tiers: exact text, equal numeric
value, then rapidfuzz WRatio >= 90. When a value appears more than once, the match next to
the field's label wins; line-item amounts also prefer the row of their description and the
rightmost column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz import fuzz

from invoiceflow.contracts import (
    BBox,
    FieldLocation,
    InvoiceExtraction,
    MatchType,
    PageText,
    ParsedDocument,
    Word,
)
from invoiceflow.locate.fields import (
    FIELD_LABELS,
    LINE_ITEM_FIELDS,
    LOCATABLE_HEADER_FIELDS,
)
from invoiceflow.normalize import normalize_percent, normalize_text, parse_amount

MAX_RUN_WORDS = 8
MAX_RUN_LINES = 3
FUZZY_MIN_SCORE = 90.0
_MIN_FUZZY_LENGTH_RATIO = 0.8
_LINE_TOLERANCE = 0.006
_ROW_TOLERANCE = 0.006
_LABEL_WINDOW = 6
_NON_WORD = re.compile(r"[^a-z0-9%$]+")


@dataclass(frozen=True)
class _Token:
    word: Word
    line: int
    order: int
    page_no: int


@dataclass(frozen=True)
class _Run:
    text: str
    bbox: BBox
    page_no: int
    line: int
    order: int
    tokens: tuple[_Token, ...]


@dataclass(frozen=True)
class _Candidate:
    run: _Run
    match_type: MatchType
    score: float


@dataclass(frozen=True)
class _PageIndex:
    tokens: tuple[_Token, ...]
    runs: tuple[_Run, ...]


def _center_y(box: BBox) -> float:
    return (box.y0 + box.y1) / 2


def _build_tokens(page: PageText) -> tuple[_Token, ...]:
    visible = sorted(page.visible_words, key=lambda w: (_center_y(w.bbox), w.bbox.x0))
    tokens: list[_Token] = []
    line_centers: list[float] = []
    line_counts: list[int] = []
    for word in visible:
        center = _center_y(word.bbox)
        if line_centers and abs(center - line_centers[-1]) <= _LINE_TOLERANCE:
            count = line_counts[-1] + 1
            line_centers[-1] = (line_centers[-1] * line_counts[-1] + center) / count
            line_counts[-1] = count
        else:
            line_centers.append(center)
            line_counts.append(1)
        tokens.append(
            _Token(
                word=word,
                line=len(line_centers) - 1,
                order=len(tokens),
                page_no=page.page_no,
            )
        )
    return tuple(tokens)


def _build_runs(tokens: tuple[_Token, ...]) -> tuple[_Run, ...]:
    runs: list[_Run] = []
    for start in range(len(tokens)):
        box = tokens[start].word.bbox
        first_line = tokens[start].line
        parts: list[str] = []
        for end in range(start, min(len(tokens), start + MAX_RUN_WORDS)):
            token = tokens[end]
            if token.line - first_line >= MAX_RUN_LINES:
                break
            parts.append(token.word.text)
            if end > start:
                box = box.union(token.word.bbox)
            runs.append(
                _Run(
                    text=" ".join(parts),
                    bbox=box,
                    page_no=token.page_no,
                    line=first_line,
                    order=tokens[start].order,
                    tokens=tokens[start : end + 1],
                )
            )
    return tuple(runs)


def _index_page(page: PageText) -> _PageIndex:
    tokens = _build_tokens(page)
    return _PageIndex(tokens=tokens, runs=_build_runs(tokens))


def _number(text: str) -> Decimal | None:
    if "%" in text:
        return normalize_percent(text)
    return parse_amount(text)


def _find_candidates(runs: tuple[_Run, ...], value: str) -> list[_Candidate]:
    target_key = normalize_text(value)
    if not target_key:
        return []

    exact = [
        _Candidate(run=run, match_type=MatchType.EXACT, score=100.0)
        for run in runs
        if normalize_text(run.text) == target_key
    ]
    if exact:
        return exact

    target_number = _number(value)
    if target_number is not None:
        numeric = []
        for run in runs:
            number = _number(run.text)
            if number is not None and number == target_number:
                numeric.append(_Candidate(run=run, match_type=MatchType.NUMERIC, score=100.0))
        if numeric:
            return numeric

    fuzzy = []
    for run in runs:
        run_key = normalize_text(run.text)
        shortest = min(len(target_key), len(run_key))
        longest = max(len(target_key), len(run_key))
        if not longest or shortest / longest < _MIN_FUZZY_LENGTH_RATIO:
            continue
        score = float(fuzz.WRatio(target_key, run_key))
        if score >= FUZZY_MIN_SCORE:
            fuzzy.append(_Candidate(run=run, match_type=MatchType.FUZZY, score=score))
    return fuzzy


def _word_key(word: Word) -> str:
    return _NON_WORD.sub("", normalize_text(word.text))


def _label_rank(field: str, run: _Run, tokens: tuple[_Token, ...]) -> tuple[int, int] | None:
    """How close the field's label is to the left on the same line.

    Returns ``(words_after_label, -label_specificity)``; lower is better. A label in
    ``Total Payable`` therefore beats a bare ``Total`` at the same distance.
    """
    labels = FIELD_LABELS.get(field, ())
    if not labels:
        return None
    same_line = [
        token
        for token in tokens
        if token.page_no == run.page_no and token.line == run.line and token.order < run.order
    ]
    if not same_line:
        return None

    keys = [_word_key(token.word) for token in same_line][-_LABEL_WINDOW:]
    best: tuple[int, int] | None = None
    for label in labels:
        wanted = label.split()
        for start in range(len(keys)):
            end = start + len(wanted)
            if end > len(keys) or keys[start:end] != wanted:
                continue
            candidate = (len(keys) - end, -len(wanted))
            if best is None or candidate < best:
                best = candidate
    return best


def _rank_candidate(candidate: _Candidate, field: str, tokens: tuple[_Token, ...]) -> tuple:
    label = _label_rank(field, candidate.run, tokens)
    label_key = (1, 99, 0) if label is None else (0, label[0], label[1])
    return (
        label_key,
        -candidate.score,
        len(candidate.run.tokens),
        candidate.run.page_no,
        candidate.run.order,
    )


def _row_candidates(candidates: list[_Candidate], row: float) -> list[_Candidate]:
    return [
        candidate
        for candidate in candidates
        if abs(_center_y(candidate.run.bbox) - row) <= _ROW_TOLERANCE
    ]


def _locate_value(
    field: str,
    value: str | None,
    indexes: dict[int, _PageIndex],
    *,
    row: float | None = None,
    page_no: int | None = None,
    prefer_right: bool = False,
) -> FieldLocation:
    if normalize_text(value) == "":
        return _not_found(field)

    if page_no is not None:
        candidates = _find_candidates(indexes[page_no].runs, value or "")
        if not candidates:
            candidates = _all_candidates(indexes, value or "")
    else:
        candidates = _all_candidates(indexes, value or "")
    if not candidates:
        return _not_found(field)

    if row is not None:
        on_row = _row_candidates(candidates, row)
        if on_row:
            chosen = (
                max(on_row, key=lambda c: (c.run.bbox.x1, -c.run.order))
                if prefer_right
                else min(on_row, key=lambda c: (c.run.bbox.x0, c.run.order))
            )
            return _found(field, chosen)

    chosen = min(
        candidates,
        key=lambda c: _rank_candidate(c, field, indexes[c.run.page_no].tokens),
    )
    return _found(field, chosen)


def _all_candidates(indexes: dict[int, _PageIndex], value: str) -> list[_Candidate]:
    return [
        candidate
        for page_no in sorted(indexes)
        for candidate in _find_candidates(indexes[page_no].runs, value)
    ]


def _found(field: str, candidate: _Candidate) -> FieldLocation:
    return FieldLocation(
        field=field,
        page_no=candidate.run.page_no,
        bbox=candidate.run.bbox,
        match_type=candidate.match_type,
        score=candidate.score,
        matched_text=candidate.run.text,
    )


def _not_found(field: str) -> FieldLocation:
    return FieldLocation(
        field=field,
        page_no=None,
        bbox=None,
        match_type=MatchType.NONE,
        score=0.0,
        matched_text=None,
    )


def locate(document: ParsedDocument, extraction: InvoiceExtraction) -> tuple[FieldLocation, ...]:
    """Locate every evidence field on the page, including NONE entries for misses."""
    indexes = {page.page_no: _index_page(page) for page in document.pages}
    locations: list[FieldLocation] = []

    for field in LOCATABLE_HEADER_FIELDS:
        locations.append(_locate_value(field, getattr(extraction, field, None), indexes))

    for index, item in enumerate(extraction.line_items):
        prefix = f"line_items[{index}]"
        description = _locate_value(f"{prefix}.description", item.description, indexes)
        description_row = _center_y(description.bbox) if description.bbox is not None else None
        locations.append(description)
        for field in LINE_ITEM_FIELDS:
            if field == "description":
                continue
            locations.append(
                _locate_value(
                    f"{prefix}.{field}",
                    getattr(item, field, None),
                    indexes,
                    row=description_row,
                    page_no=description.page_no,
                    prefer_right=field in {"amount", "unit_price"},
                )
            )
    return tuple(locations)


class Locator:
    """The ``Locator`` protocol implementation."""

    def locate(
        self, document: ParsedDocument, extraction: InvoiceExtraction
    ) -> tuple[FieldLocation, ...]:
        return locate(document, extraction)
