from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from helpers import simple_text_pdf

import invoiceflow.parse.extractor as extractor_module
from invoiceflow.contracts import FileKind, TextSource
from invoiceflow.parse import DocumentParser, ParseError


def test_rotated_digital_page_with_no_ocr_words_falls_back_to_pdf_text(monkeypatch, tmp_path):
    monkeypatch.setattr(extractor_module, "ocr_words", lambda image: ((), None))
    path = tmp_path / "rotated.pdf"
    path.write_bytes(simple_text_pdf("HELLO INVOICE", rotate=90))

    document = DocumentParser(image_root=tmp_path / "pages").parse(
        path, file_id=uuid4(), doc_id=uuid4()
    )
    page = document.pages[0]
    assert page.source is TextSource.PDF_TEXT
    assert page.words
    assert page.image_path and Path(page.image_path).is_file()


def test_default_image_root_uses_the_data_directory(monkeypatch, tmp_path, golden_clean):
    monkeypatch.setattr(extractor_module, "data_dir", lambda: tmp_path / "data")
    document = DocumentParser().parse(
        golden_clean.pdf_path, file_id=golden_clean.file_id, doc_id=golden_clean.doc_id
    )
    image_path = Path(document.pages[0].image_path or "")
    assert image_path.is_file()
    assert image_path.is_relative_to(tmp_path / "data")


def test_a_file_detected_as_an_image_but_impossible_to_open_raises_parse_error(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(extractor_module, "detect_file_kind", lambda path: FileKind.IMAGE)
    path = tmp_path / "pretend.png"
    path.write_text("not an image")
    with pytest.raises(ParseError):
        DocumentParser(image_root=tmp_path / "pages").parse(path, file_id=uuid4(), doc_id=uuid4())


def test_a_pdf_that_cannot_be_rendered_raises_parse_error(monkeypatch, tmp_path, golden_clean):
    def boom(*args, **kwargs):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(extractor_module.pdfium, "PdfDocument", boom)
    with pytest.raises(ParseError):
        DocumentParser(image_root=tmp_path / "pages").parse(
            golden_clean.pdf_path,
            file_id=golden_clean.file_id,
            doc_id=golden_clean.doc_id,
        )
