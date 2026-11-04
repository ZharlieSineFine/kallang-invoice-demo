"""WS2: reading documents into words, boxes, hidden evidence, and prompt text."""

from invoiceflow.parse.config import ParseConfig
from invoiceflow.parse.detect import detect_file_kind
from invoiceflow.parse.errors import (
    EmptyDocumentError,
    FileTooLargeError,
    ParseError,
    TooManyPagesError,
    UnsupportedFileKindError,
)
from invoiceflow.parse.extractor import DocumentParser, parse_document
from invoiceflow.parse.reading import page_texts

__all__ = [
    "DocumentParser",
    "EmptyDocumentError",
    "FileTooLargeError",
    "ParseConfig",
    "ParseError",
    "TooManyPagesError",
    "UnsupportedFileKindError",
    "detect_file_kind",
    "page_texts",
    "parse_document",
]
