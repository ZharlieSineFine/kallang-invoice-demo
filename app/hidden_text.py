"""The R09 hidden-text panel and its marker on the page image.

The words, the tricks, and the positions come from rerunning the parser's own detector
(``parse.pdf.hidden_text_for_file``) on the stored upload, so the panel always agrees with
the check that raised the hold. What the model was given comes from its recorded run.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path

import streamlit as st

from app import ui
from app.boxes import BoxSpec
from app.formatting import format_money
from app.models import DocumentBundle, FindingRow
from invoiceflow.contracts import BBox
from invoiceflow.parse import ParseConfig
from invoiceflow.parse.hidden import NOT_VISIBLE, OFF_PAGE, TINY_FONT, WHITE_TEXT
from invoiceflow.parse.pdf import HiddenPassage, HiddenText, hidden_text_for_file

HIDDEN_MESSAGE = "Hidden text detected"
OUTPUT_MESSAGE = "Instruction-like text appeared in the model output"
_MIN_WIDTH = 0.12  # page fractions: a marker a person can see even for 1 pt text
_MIN_HEIGHT = 0.025
_PANEL = (
    "background:#fdecea;color:#3b0d0c;border:1px solid #e57373;border-left:6px solid #c62828;"
    "border-radius:8px;padding:0.65rem 0.85rem;margin:0.25rem 0 0.75rem 0;font-size:0.92rem;"
)
_QUOTE = (
    "font-family:monospace;background:#ffffff;color:#1f2328;border:1px solid #e0a8a8;"
    "border-radius:4px;padding:0.1rem 0.4rem;"
)


@dataclass(frozen=True)
class HiddenSummary:
    page_no: int
    text: str
    words: int
    reasons: tuple[str, ...]
    location: str
    passage: HiddenPassage


def _off_page_side(passage: HiddenPassage, width: float, height: float) -> str | None:
    if passage.top >= height:
        return "below the bottom edge of the page"
    if passage.bottom <= 0:
        return "above the top edge of the page"
    if passage.x0 >= width:
        return "to the right of the page"
    if passage.x1 <= 0:
        return "to the left of the page"
    return None


def _third(value: float, span: float, names: tuple[str, str, str]) -> str:
    share = min(1.0, max(0.0, value / span)) if span > 0 else 0.0
    return names[0] if share < 1 / 3 else names[1] if share < 2 / 3 else names[2]


def _location(passage: HiddenPassage, hidden: HiddenText) -> str:
    across = _third((passage.x0 + passage.x1) / 2, hidden.width, ("left", "center", "right"))
    down = _third((passage.top + passage.bottom) / 2, hidden.height, ("top", "middle", "bottom"))
    side = _off_page_side(passage, hidden.width, hidden.height)
    page = f"page {hidden.page_no}"
    if side is None:
        return (
            f"{page}, center"
            if (down, across) == ("middle", "center")
            else (f"{page}, {down} {across}")
        )
    if side.startswith(("below", "above")):
        edge = "bottom" if side.startswith("below") else "top"
        where = "below" if edge == "bottom" else "above"
        if across == "center":
            return f"{page}, just {where} the middle of the {edge} edge"
        return f"{page}, just {where} the {edge}-{across} corner"
    return f"{page}, just {side}, near the {down}"


def _reason_labels(passage: HiddenPassage, hidden: HiddenText) -> tuple[str, ...]:
    labels: list[str] = []
    if WHITE_TEXT in passage.reasons:
        labels.append("white text")
    if TINY_FONT in passage.reasons:
        size = f"{round(passage.font_size, 1):g} pt" if passage.font_size is not None else "tiny"
        labels.append(f"{size} font")
    if OFF_PAGE in passage.reasons:
        labels.append(_off_page_side(passage, hidden.width, hidden.height) or "outside the page")
    if NOT_VISIBLE in passage.reasons:
        labels.append("not visible on the printed page (checked by reading the page image)")
    return tuple(labels)


def summarize(hidden: HiddenText) -> tuple[HiddenSummary, ...]:
    return tuple(
        HiddenSummary(
            page_no=hidden.page_no,
            text=passage.text,
            words=len(passage.text.split()),
            reasons=_reason_labels(passage, hidden),
            location=_location(passage, hidden),
            passage=passage,
        )
        for passage in hidden.passages
    )


def _span(start: float, end: float, minimum: float) -> tuple[float, float]:
    """A range at least ``minimum`` wide around the clamped middle, kept inside 0..1."""
    low, high = sorted((min(1.0, max(0.0, start)), min(1.0, max(0.0, end))))
    size = max(high - low, minimum)
    middle = (low + high) / 2
    first = min(max(middle - size / 2, 0.0), 1.0 - size)
    return first, first + size


def marker_box(summary: HiddenSummary, hidden: HiddenText, index: int = 0) -> BoxSpec:
    passage = summary.passage
    x0, x1 = _span(passage.x0 / hidden.width, passage.x1 / hidden.width, _MIN_WIDTH)
    y0, y1 = _span(passage.top / hidden.height, passage.bottom / hidden.height, _MIN_HEIGHT)
    return BoxSpec(
        field=f"hidden-{summary.page_no}-{index}",
        bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
        status="flagged",
        label=f"Hidden text: {summary.text}",
    )


def effect_lines(
    *, images_sent: int | None, output_flagged: bool, total: str | None
) -> tuple[str, ...]:
    if images_sent == 0:
        given = (
            "The model was sent the page text with these words removed and no page image, so "
            "it never received them."
        )
    elif images_sent:
        given = "The model was sent the page text with these words removed, plus the page image."
    else:
        given = "The model was sent the page text with these words removed."
    answer = (
        "R09 found instruction phrases in the model's answer."
        if output_flagged
        else "R09 found none of the instruction phrases it looks for in the model's answer."
    )
    lines = [given, answer]
    try:
        amount = Decimal(total) if total else None
    except InvalidOperation:
        amount = None
    if amount is not None:
        lines.append(f"The model read the total as {format_money(amount)}.")
    return tuple(lines)


@st.cache_data(show_spinner=False)
def _cached_hidden(path: str, modified: float, page_no: int) -> HiddenText | None:
    del modified  # part of the cache key only
    return hidden_text_for_file(Path(path), page_no, ParseConfig.from_repo())


def page_hidden_text(bundle: DocumentBundle, page_no: int) -> HiddenText | None:
    resolved = ui.resolve_path(bundle.document.file_path)
    if resolved is None or not resolved.is_file():
        return None
    try:
        return _cached_hidden(str(resolved), resolved.stat().st_mtime, page_no)
    except Exception:  # pdfminer raises several unrelated types; show the page without it
        return None


def hidden_markers(bundle: DocumentBundle, page_no: int) -> tuple[BoxSpec, ...]:
    """Red markers for the hidden text on one page, when R09 found any."""
    if not any(_is_hidden_finding(finding) for finding in bundle.findings):
        return ()
    hidden = page_hidden_text(bundle, page_no)
    if hidden is None:
        return ()
    return tuple(
        marker_box(summary, hidden, index) for index, summary in enumerate(summarize(hidden))
    )


def _is_hidden_finding(finding: FindingRow) -> bool:
    return finding.rule_id == "R09" and finding.message.startswith(HIDDEN_MESSAGE)


def _pages(finding: FindingRow) -> tuple[int, ...]:
    raw = str(finding.evidence.get("pages", ""))
    return tuple(int(part) for part in raw.replace(" ", "").split(",") if part.isdigit())


def panel_html(summaries: tuple[HiddenSummary, ...], effects: tuple[str, ...]) -> str:
    total = sum(summary.words for summary in summaries)
    noun = "word" if total == 1 else "words"
    items = "".join(
        '<div style="margin-top:0.4rem;">'
        f'<span style="{_QUOTE}">{escape(summary.text)}</span>'
        f'<div style="margin-top:0.25rem;">Why you can\'t see it: '
        f"{escape(' · '.join(summary.reasons))}</div>"
        f"<div>Where: {escape(summary.location)} (marked in red on the image)</div>"
        "</div>"
        for summary in summaries
    )
    effect = "".join(f"<li>{escape(line)}</li>" for line in effects)
    return (
        f'<div data-hidden-words="{total}" style="{_PANEL}">'
        f'<div style="font-weight:700;">Hidden text ({total} {noun}, invisible on the printed '
        "page):</div>"
        f"{items}"
        '<div style="margin-top:0.5rem;font-weight:700;">What the model was given:</div>'
        f'<ul style="margin:0.1rem 0 0 1.1rem;padding:0;">{effect}</ul>'
        "</div>"
    )


def render_hidden_text(bundle: DocumentBundle, finding: FindingRow) -> None:
    """The panel under an R09 hidden-text finding card."""
    if not _is_hidden_finding(finding):
        return
    pages = _pages(finding) or tuple(page.page_no for page in bundle.pages)
    found = [page_hidden_text(bundle, page_no) for page_no in pages]
    summaries = tuple(summary for hidden in found if hidden for summary in summarize(hidden))
    if not summaries:
        st.caption("The uploaded file is not available here, so the hidden words cannot be shown.")
        return
    extraction = bundle.extraction
    effects = effect_lines(
        images_sent=extraction.images_sent if extraction else None,
        output_flagged=any(f.message.startswith(OUTPUT_MESSAGE) for f in bundle.findings),
        total=str((extraction.parsed or {}).get("total") or "") if extraction else None,
    )
    st.markdown(panel_html(summaries, effects), unsafe_allow_html=True)
