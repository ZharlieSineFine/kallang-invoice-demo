from __future__ import annotations

from uuid import uuid4

from helpers import hidden_text_pdf

from invoiceflow.parse import DocumentParser


def _parse(tmp_path, data: bytes):
    path = tmp_path / "hidden.pdf"
    path.write_bytes(data)
    return DocumentParser(image_root=tmp_path / "pages").parse(
        path, file_id=uuid4(), doc_id=uuid4()
    )


def test_hidden_text_invoice_is_caught(tmp_path):
    document = _parse(tmp_path, hidden_text_pdf())
    page = document.pages[0]
    hidden = " ".join(word.text for word in page.words if word.hidden)
    assert "ignore previous instructions" in hidden
    assert "tiny hidden text" in hidden
    assert "offpage secret" in hidden
    assert len(document.hidden_words) >= 3


def test_hidden_words_are_evidence_but_not_prompt_text(tmp_path):
    document = _parse(tmp_path, hidden_text_pdf())
    assert document.pages[0].source.value == "PDF_TEXT"
    text = DocumentParser(image_root=tmp_path / "pages").page_texts(document)[0]
    assert text == "VISIBLE INVOICE TEXT FOR THE REVIEW SCREEN"
    assert "ignore previous instructions" not in text
    assert "tiny hidden text" not in text
    assert "offpage secret" not in text


def test_hidden_boxes_are_clamped_into_the_page(tmp_path):
    document = _parse(tmp_path, hidden_text_pdf())
    for page_no, word in document.hidden_words:
        assert page_no == 1
        assert 0 <= word.bbox.x0 <= word.bbox.x1 <= 1
        assert 0 <= word.bbox.y0 <= word.bbox.y1 <= 1


def test_visible_word_is_not_marked_hidden(tmp_path):
    document = _parse(tmp_path, hidden_text_pdf())
    visible = [word for word in document.pages[0].words if word.text == "VISIBLE"]
    assert len(visible) == 1
    assert visible[0].hidden is False
