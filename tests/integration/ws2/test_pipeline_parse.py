"""Integration: the real WS2 parser behind the Phase 0 pipeline stubs."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from invoiceflow.contracts import DocStatus, InvoiceExtraction
from invoiceflow.parse import DocumentParser, page_texts
from invoiceflow.pipeline.golden import load_golden
from invoiceflow.pipeline.stages import process_document
from invoiceflow.pipeline.stubs import golden_deps
from invoiceflow.settings import load_config

TODAY = date(2026, 11, 4)


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _strings(nested)


def _truth_strings(printed: InvoiceExtraction) -> tuple[str, ...]:
    data = printed.model_dump(mode="json")
    data.pop("document_type", None)
    return tuple(value for value in _strings(data) if value.strip())


def _hit_rate(values: tuple[str, ...], text: str) -> float:
    haystack = re.sub(r"\s+", " ", text)
    return sum(re.sub(r"\s+", " ", value) in haystack for value in values) / len(values)


@pytest.fixture(scope="module")
def golden():
    return load_golden()


def test_real_parser_drives_the_phase0_pipeline(golden, tmp_path):
    deps = replace(golden_deps(golden), text_extractor=DocumentParser(image_root=tmp_path))
    clean = golden.fixtures[0]
    result = process_document(
        clean.pdf_path,
        file_id=clean.file_id,
        doc_id=clean.doc_id,
        deps=deps,
        master=golden.master,
        today=TODAY,
        run_id="ws2-integration",
        rules_config=load_config("rules"),
    )
    assert result.decision.status is DocStatus.AUTO_PASSED
    assert result.findings == ()
    assert result.document.file_kind.value == "PDF"
    assert result.document.pages[0].source.value == "PDF_TEXT"
    assert "SAV-2026-0412" in page_texts(result.document)[0]


def test_both_golden_pdfs_meet_the_digital_hit_rate(golden, tmp_path):
    parser = DocumentParser(image_root=tmp_path)
    for fixture in golden.fixtures:
        document = parser.parse(fixture.pdf_path, file_id=fixture.file_id, doc_id=fixture.doc_id)
        text = "\n".join(parser.page_texts(document))
        rate = _hit_rate(_truth_strings(fixture.truth.printed), text)
        assert rate >= 0.99, (fixture.fixture_id, rate)


def test_page_images_land_under_the_requested_root(golden, tmp_path):
    parser = DocumentParser(image_root=tmp_path)
    fixture = golden.fixtures[0]
    document = parser.parse(fixture.pdf_path, file_id=fixture.file_id, doc_id=fixture.doc_id)
    image_path = Path(document.pages[0].image_path or "")
    assert image_path.is_file()
    assert tmp_path in image_path.parents
