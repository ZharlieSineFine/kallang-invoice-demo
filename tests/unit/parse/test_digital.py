from __future__ import annotations

from pathlib import Path

import pytest
from helpers import collapse, hit_rate, truth_strings

from invoiceflow.contracts import FileKind, TextSource
from invoiceflow.parse import DocumentParser, ParseConfig, page_texts, parse_document
from invoiceflow.pipeline.golden import load_golden


def test_golden_pdf_is_read_as_digital_text(parser, golden_clean):
    document = parser.parse(
        golden_clean.pdf_path, file_id=golden_clean.file_id, doc_id=golden_clean.doc_id
    )
    assert document.file_kind is FileKind.PDF
    assert document.file_id == golden_clean.file_id
    assert document.doc_id == golden_clean.doc_id
    assert len(document.pages) == 1
    page = document.pages[0]
    assert page.source is TextSource.PDF_TEXT
    assert page.page_no == 1
    assert page.width_pt == pytest.approx(595.28, abs=0.1)
    assert page.height_pt == pytest.approx(841.89, abs=0.1)
    assert page.image_path is not None
    assert page.ocr_mean_conf is None
    assert len(page.words) > 50
    assert document.hidden_words == ()
    assert page.image_path and Path(page.image_path).is_file()


def test_boxes_are_page_fractions(parser, golden_clean):
    document = parser.parse(
        golden_clean.pdf_path, file_id=golden_clean.file_id, doc_id=golden_clean.doc_id
    )
    for word in document.pages[0].words:
        assert 0 <= word.bbox.x0 <= word.bbox.x1 <= 1
        assert 0 <= word.bbox.y0 <= word.bbox.y1 <= 1
        assert word.conf is None


def test_at_least_99_percent_of_golden_truth_values_are_in_the_words(parser):
    golden = load_golden()
    for fixture in golden.fixtures:
        document = parser.parse(fixture.pdf_path, file_id=fixture.file_id, doc_id=fixture.doc_id)
        text = "\n".join(parser.page_texts(document))
        values = truth_strings(fixture.truth.printed)
        rate = hit_rate(values, text)
        print(f"WS2 digital truth hit rate {fixture.fixture_id}: {rate:.1%} ({len(values)} values)")
        assert rate >= 0.99, fixture.fixture_id


def test_page_text_is_in_reading_order(parser, golden_clean):
    document = parser.parse(
        golden_clean.pdf_path, file_id=golden_clean.file_id, doc_id=golden_clean.doc_id
    )
    text = parser.page_texts(document)[0]
    assert text.index("TAX INVOICE") < text.index("LED wall panel rental")
    assert text.index("LED wall panel rental") < text.index("Transport and setup")
    assert text.index("1,080.00") < text.index("97.20") < text.index("1,177.20")


def test_page_texts_leave_out_hidden_words(parser, golden_clean):
    document = parser.parse(
        golden_clean.pdf_path, file_id=golden_clean.file_id, doc_id=golden_clean.doc_id
    )
    page = document.pages[0]
    injected = page.words[0].model_copy(update={"text": "IGNORE-PREVIOUS", "hidden": True})
    changed = document.model_copy(
        update={"pages": (page.model_copy(update={"words": (*page.words, injected)}),)}
    )
    texts = parser.page_texts(changed)
    assert "IGNORE-PREVIOUS" not in texts[0]
    assert "SAV-2026-0412" in texts[0]
    assert len(texts) == 1


def test_page_texts_sort_pages(tmp_path, golden_clean):
    parser = DocumentParser(config=ParseConfig(), image_root=tmp_path / "pages")
    document = parser.parse(
        golden_clean.pdf_path, file_id=golden_clean.file_id, doc_id=golden_clean.doc_id
    )
    second = document.pages[0].model_copy(update={"page_no": 2})
    first = document.pages[0].model_copy(update={"page_no": 1})
    reordered = document.model_copy(update={"pages": (second, first)})
    texts = parser.page_texts(reordered)
    assert len(texts) == 2


def test_parse_document_convenience(tmp_path, golden_clean):
    document = parse_document(
        golden_clean.pdf_path,
        file_id=golden_clean.file_id,
        doc_id=golden_clean.doc_id,
        image_root=tmp_path / "pages",
    )
    assert document.doc_id == golden_clean.doc_id
    assert "SAV-2026-0412" in collapse(" ".join(page_texts(document)))
