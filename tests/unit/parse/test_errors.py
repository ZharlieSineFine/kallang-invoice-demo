from __future__ import annotations

from uuid import uuid4

import pytest
from helpers import build_pdf, simple_text_pdf

from invoiceflow.contracts import FileKind
from invoiceflow.parse import DocumentParser, ParseConfig, parse_document
from invoiceflow.parse.errors import (
    EmptyDocumentError,
    FileTooLargeError,
    ParseError,
    TooManyPagesError,
    UnsupportedFileKindError,
)


def _parse(parser, path):
    return parser.parse(path, file_id=uuid4(), doc_id=uuid4())


def test_file_over_the_size_limit_is_rejected(tmp_path):
    path = tmp_path / "invoice.pdf"
    path.write_bytes(simple_text_pdf())
    parser = DocumentParser(config=ParseConfig(max_file_bytes=10), image_root=tmp_path / "pages")
    with pytest.raises(FileTooLargeError) as caught:
        _parse(parser, path)
    assert caught.value.size_bytes > caught.value.max_bytes


def test_pdf_over_the_page_limit_is_rejected(tmp_path):
    path = tmp_path / "two-pages.pdf"
    path.write_bytes(build_pdf([b"BT ET", b"BT ET"]))
    parser = DocumentParser(config=ParseConfig(max_pages=1), image_root=tmp_path / "pages")
    with pytest.raises(TooManyPagesError) as caught:
        _parse(parser, path)
    assert caught.value.page_count == 2


def test_unsupported_kind_is_rejected_with_the_detected_kind(tmp_path):
    path = tmp_path / "invoice.txt"
    path.write_text("<Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'/>")
    with pytest.raises(UnsupportedFileKindError) as caught:
        parse_document(path, file_id=uuid4(), doc_id=uuid4())
    assert caught.value.file_kind is FileKind.PEPPOL_XML


def test_unknown_kind_is_rejected(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("just some notes")
    with pytest.raises(UnsupportedFileKindError) as caught:
        parse_document(path, file_id=uuid4(), doc_id=uuid4())
    assert caught.value.file_kind is FileKind.UNKNOWN


def test_empty_pdf_is_rejected(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(build_pdf([]))
    with pytest.raises(EmptyDocumentError):
        _parse(DocumentParser(image_root=tmp_path / "pages"), path)


def test_corrupt_pdf_raises_a_parse_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7 not really a pdf")
    with pytest.raises(ParseError):
        _parse(DocumentParser(image_root=tmp_path / "pages"), path)


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_document(tmp_path / "absent.pdf", file_id=uuid4(), doc_id=uuid4())
