"""The Read step's decision, shown as the rule the parser applied to the page.

The numbers come from running the parser's own check (``parse.pdf.text_layer_check_for_file``)
on the stored upload, so the screen shows the real decision, not a description of it. The
HTML sets its own text colors so it reads the same in both Streamlit themes.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

from app import ui
from invoiceflow.contracts import PageText, TextSource
from invoiceflow.parse import ParseConfig
from invoiceflow.parse.pdf import TextLayerCheck, text_layer_check_for_file

# background, text, border
_TAKEN = ("#e8f5e9", "#1b5e20", "#2e7d32")
_SKIPPED = ("#f6f8fa", "#8c959f", "#d0d7de")
_PANEL = (
    "border:1px solid #d0d7de;border-radius:8px;padding:0.75rem 0.9rem;"
    "background:#ffffff;color:#1f2328;margin-bottom:1rem;"
)
_STEP = "font-size:0.85rem;color:#57606a;margin-top:0.4rem;"
RULE_SOURCE = (
    "uses_text_layer = visible_chars >= scanned_page_min_chars and rotation == 0"
    "  # parse/pdf.py, value in config/rules.yaml"
)


@st.cache_data(show_spinner=False)
def _cached_check(path: str, modified: float, page_no: int) -> TextLayerCheck | None:
    del modified  # part of the cache key only
    return text_layer_check_for_file(Path(path), page_no, ParseConfig.from_repo())


def page_check(file_path: str | None, page_no: int) -> TextLayerCheck | None:
    """The check for one page of a stored upload, or ``None`` when the file is not there."""
    resolved = ui.resolve_path(file_path)
    if resolved is None or not resolved.is_file():
        return None
    try:
        return _cached_check(str(resolved), resolved.stat().st_mtime, page_no)
    except Exception:  # pdfminer raises several unrelated types; show the page without the rule
        return None


def _comparison(check: TextLayerCheck) -> str:
    enough = check.visible_chars >= check.min_chars
    text = f"{check.visible_chars} {'≥' if enough else '<'} {check.min_chars}"
    if check.is_pdf and enough and not check.is_upright:
        text += f", but the page is rotated {check.rotation}°"
    return text


def _branch(name: str, label: str, taken: bool) -> str:
    background, color, border = _TAKEN if taken else _SKIPPED
    weight = 600 if taken else 400
    mark = "✅" if taken else "▫️"
    return (
        f'<div data-branch="{name}" data-taken="{str(taken).lower()}" '
        f'style="background:{background};color:{color};border:1px solid {border};'
        f'border-radius:6px;padding:0.35rem 0.6rem;margin-top:0.35rem;font-weight:{weight};">'
        f"{mark} {escape(label)}</div>"
    )


def read_rule_html(check: TextLayerCheck) -> str:
    """Step 1 (what pdfplumber found), step 2 (the rule), and the branch it took."""
    found = (
        f"Visible characters found: <b>{check.visible_chars}</b>"
        if check.is_pdf
        else "This upload is an image, so it has no text layer."
    )
    uses = check.uses_text_layer
    return (
        f'<div class="read-rule" style="{_PANEL}">'
        '<div style="font-weight:700;">How the system read this page</div>'
        f'<div style="{_STEP}">Step 1 · pdfplumber looks for a text layer</div>'
        f"<div>{found}</div>"
        f'<div style="{_STEP}">Step 2 · Rule: {check.min_chars} or more visible characters '
        "on an upright page?</div>"
        f'<div style="font-family:monospace;font-size:1.05rem;margin-top:0.2rem;">'
        f"{escape(_comparison(check))}</div>"
        + _branch("text", "yes → Use the PDF text layer (pdfplumber)", uses)
        + _branch("ocr", "no → Render the page as an image → Tesseract OCR", not uses)
        + "</div>"
    )


def read_summary(check: TextLayerCheck, word_count: int) -> str:
    """One sentence for the step card: which way the page was read, and why."""
    if check.uses_text_layer:
        return (
            f"The system found {word_count} words on this page, read from its PDF text layer "
            f"({check.visible_chars} visible characters; {check.min_chars} needed)."
        )
    ocr = f"read the page image with OCR and found {word_count} words."
    if not check.is_pdf:
        return f"The upload is an image with no text layer, so the system {ocr}"
    if check.visible_chars >= check.min_chars:
        return f"The page is rotated, so the system {ocr}"
    return (
        f"The page's text layer had {check.visible_chars} visible characters, under the "
        f"{check.min_chars} needed, so the system {ocr}"
    )


def stored_note(check: TextLayerCheck, words: PageText) -> str | None:
    """Say so when the stored page was read differently from what the rule gives now."""
    stored_text_layer = words.source is TextSource.PDF_TEXT
    if stored_text_layer == check.uses_text_layer:
        return None
    if stored_text_layer:
        return "OCR found no words on this rotated page, so the system kept its text layer."
    return "This page was read with OCR under an earlier setting of the rule."
