"""The Read step shows the rule it applied: the PDF text layer, or OCR of the page image."""

from __future__ import annotations

from test_pages import _run
from test_story import _advance, _text

from app.pages import story
from app.read_rule import page_check, read_rule_html, read_summary
from invoiceflow.parse.pdf import TextLayerCheck

DIGITAL = TextLayerCheck(visible_chars=612, min_chars=25)
SCAN = TextLayerCheck(visible_chars=0, min_chars=25)


def _taken(html: str) -> str:
    text_taken = 'data-branch="text" data-taken="true"' in html
    ocr_taken = 'data-branch="ocr" data-taken="true"' in html
    assert text_taken != ocr_taken, "exactly one branch is taken"
    return "text" if text_taken else "ocr"


def test_a_digital_page_takes_the_text_layer_branch():
    html = read_rule_html(DIGITAL)
    assert "Visible characters found" in html and "612" in html
    assert "612 ≥ 25" in html
    assert _taken(html) == "text"
    assert "pdfplumber" in html and "Tesseract OCR" in html


def test_a_scan_takes_the_ocr_branch():
    html = read_rule_html(SCAN)
    assert "0 &lt; 25" in html
    assert _taken(html) == "ocr"


def test_a_rotated_page_takes_the_ocr_branch_and_says_why():
    html = read_rule_html(TextLayerCheck(visible_chars=612, min_chars=25, rotation=90))
    assert "rotated" in html
    assert _taken(html) == "ocr"


def test_an_image_upload_says_it_has_no_text_layer():
    html = read_rule_html(TextLayerCheck(visible_chars=0, min_chars=25, is_pdf=False))
    assert "image" in html and "no text layer" in html
    assert _taken(html) == "ocr"


def test_the_summary_names_the_method_and_the_numbers():
    assert read_summary(DIGITAL, 106) == (
        "The system found 106 words on this page, read from its PDF text layer "
        "(612 visible characters; 25 needed)."
    )
    assert read_summary(SCAN, 98) == (
        "The page's text layer had 0 visible characters, under the 25 needed, so the system "
        "read the page image with OCR and found 98 words."
    )


def test_page_check_runs_on_the_stored_upload(clean_bundle):
    check = page_check(clean_bundle.document.file_path, 1)
    assert check is not None and check.uses_text_layer and check.visible_chars > 100


def test_page_check_is_none_without_a_stored_upload():
    assert page_check(None, 1) is None
    assert page_check("bronze/missing", 1) is None


def test_the_read_step_shows_the_rule_it_applied(fake_backend):
    at = _run(story, fake_backend)
    _advance(at, 1)
    text = _text(at)
    assert "How the system read this page" in text
    assert 'data-branch="text" data-taken="true"' in text
    assert "read from its PDF text layer" in text
