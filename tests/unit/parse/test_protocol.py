from __future__ import annotations

import sys

from invoiceflow.contracts import TextExtractor
from invoiceflow.parse import DocumentParser


def test_parser_satisfies_the_text_extractor_protocol(tmp_path):
    assert isinstance(DocumentParser(image_root=tmp_path), TextExtractor)


def test_parser_does_not_import_pymupdf():
    import invoiceflow.parse  # noqa: F401

    forbidden = {"fitz", "pymupdf", "pymupdf4llm"}
    assert forbidden.isdisjoint(sys.modules)


def test_parser_source_does_not_mention_pymupdf():
    from pathlib import Path

    import invoiceflow.parse as package

    for path in Path(package.__file__).parent.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "pymupdf" not in text
        assert "fitz" not in text
