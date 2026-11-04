from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytesseract
import pytest
from helpers import (
    hit_rate,
    image_pdf,
    save_with_exif,
    text_image,
    truth_strings,
)
from helpers import (
    render_pdf_page as render_with_pdfium,
)
from PIL import Image

from invoiceflow.contracts import TextSource
from invoiceflow.parse import ParseConfig
from invoiceflow.parse.images import correct_orientation, render_pdf_page
from invoiceflow.pipeline.golden import load_golden


def _parse_image(parser, path: Path):
    return parser.parse(path, file_id=uuid4(), doc_id=uuid4())


def test_image_is_read_with_ocr(parser, tmp_path):
    path = tmp_path / "photo.png"
    text_image("HELLO INVOICE").save(path)
    document = _parse_image(parser, path)
    page = document.pages[0]
    assert page.source is TextSource.OCR
    assert page.ocr_mean_conf is not None and page.ocr_mean_conf > 0
    assert page.image_path and Path(page.image_path).is_file()
    assert "HELLO" in parser.page_texts(document)[0].upper()


def test_photo_exif_rotation_is_corrected(parser, tmp_path):
    upright = text_image("ROTATED PHOTO", size=(600, 200))
    sideways = upright.rotate(90, expand=True)
    assert sideways.size == (200, 600)
    path = tmp_path / "photo.jpg"
    save_with_exif(path, sideways, 6)

    document = _parse_image(parser, path)
    page = document.pages[0]
    assert page.width_pt == pytest.approx(600)
    assert page.height_pt == pytest.approx(200)
    assert "ROTATED" in parser.page_texts(document)[0].upper()


def test_orientation_detection_rotates_a_sideways_page(monkeypatch):
    image = text_image("SIDEWAYS", size=(300, 100))
    monkeypatch.setattr(
        pytesseract, "image_to_osd", lambda *args, **kwargs: {"rotate": 90, "orientation_conf": 12}
    )
    rotated = correct_orientation(image)
    assert rotated.size == (100, 300)


def test_orientation_detection_needs_confidence(monkeypatch):
    image = text_image("NORMAL", size=(300, 100))
    monkeypatch.setattr(
        pytesseract, "image_to_osd", lambda *args, **kwargs: {"rotate": 90, "orientation_conf": 0}
    )
    assert correct_orientation(image).size == (300, 100)


def test_orientation_detection_failure_is_not_fatal(monkeypatch):
    image = text_image("NORMAL", size=(300, 100))

    def boom(*args, **kwargs):
        raise pytesseract.TesseractError(1, "too few characters")

    monkeypatch.setattr(pytesseract, "image_to_osd", boom)
    assert correct_orientation(image).size == (300, 100)


def test_pdf_is_rendered_at_150_dpi_for_review(parser, golden_clean):
    document = parser.parse(
        golden_clean.pdf_path, file_id=golden_clean.file_id, doc_id=golden_clean.doc_id
    )
    with Image.open(document.pages[0].image_path) as image:
        assert image.width == pytest.approx(595.28 * 150 / 72, abs=2)


def test_pdf_is_rendered_at_300_dpi_for_ocr(golden_clean):
    image = render_pdf_page(golden_clean.pdf_path, dpi=300)
    assert image.width == pytest.approx(595.28 * 300 / 72, abs=2)


def test_scanned_pdf_goes_through_ocr(parser, golden_clean, tmp_path):
    page_image = render_with_pdfium(golden_clean.pdf_path, dpi=200)
    path = tmp_path / "scan.pdf"
    path.write_bytes(image_pdf(page_image))

    document = parser.parse(path, file_id=uuid4(), doc_id=uuid4())
    page = document.pages[0]
    assert document.file_kind.value == "PDF"
    assert page.source is TextSource.OCR
    assert page.ocr_mean_conf is not None
    assert "SAV-2026-0412" in parser.page_texts(document)[0]


def test_type_c_scan_hit_rate_is_at_least_90_percent(parser, golden_clean, tmp_path):
    scan = tmp_path / "scan.png"
    render_with_pdfium(golden_clean.pdf_path, dpi=300).save(scan, format="PNG")

    document = _parse_image(parser, scan)
    text = "\n".join(parser.page_texts(document))
    values = truth_strings(golden_clean.truth.printed)
    rate = hit_rate(values, text)
    print(f"WS2 type C scan truth hit rate: {rate:.1%} ({len(values)} values)")
    assert rate >= 0.90


def test_config_defaults_are_used(parser):
    assert parser.config.ocr_dpi == 300
    assert parser.config.review_dpi == 150
    assert parser.config.scanned_page_min_chars == 25
    assert parser.config.hidden_max_font_size_pt == pytest.approx(2.0)
    assert parser.config.hidden_min_fill_lightness == pytest.approx(0.95)


def test_golden_set_still_loads():
    assert len(load_golden().fixtures) == 2
    assert ParseConfig().max_pages == 20


def test_downscale_is_a_no_op_at_the_same_dpi():
    image = text_image("SAME DPI", size=(300, 100))
    from invoiceflow.parse.images import downscale

    assert downscale(image, from_dpi=150, to_dpi=150) is image


def test_ocr_with_no_words_returns_a_none_mean(monkeypatch):
    from invoiceflow.parse.images import ocr_words

    monkeypatch.setattr(
        pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {
            "text": [],
            "conf": [],
            "left": [],
            "top": [],
            "width": [],
            "height": [],
        },
    )
    words, mean = ocr_words(text_image(size=(100, 50)))
    assert words == () and mean is None


def test_ocr_skips_blank_and_negative_confidence_blocks(monkeypatch):
    from invoiceflow.parse.images import ocr_words

    monkeypatch.setattr(
        pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {
            "text": ["", "HELLO", "block"],
            "conf": ["-1", "90", "-1"],
            "left": [0, 10, 0],
            "top": [0, 10, 0],
            "width": [0, 40, 0],
            "height": [0, 20, 0],
        },
    )
    words, mean = ocr_words(text_image(size=(100, 50)))
    assert [word.text for word in words] == ["HELLO"]
    assert mean == pytest.approx(90)


def test_bad_orientation_output_is_ignored(monkeypatch):
    monkeypatch.setattr(
        pytesseract,
        "image_to_osd",
        lambda *args, **kwargs: {"rotate": "nonsense", "orientation_conf": "nonsense"},
    )
    assert correct_orientation(text_image(size=(300, 100))).size == (300, 100)
