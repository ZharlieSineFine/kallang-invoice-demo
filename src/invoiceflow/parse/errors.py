"""Errors raised while reading a document."""

from __future__ import annotations

from invoiceflow.contracts import FileKind


class ParseError(Exception):
    """A document cannot be read as an invoice."""


class FileTooLargeError(ParseError):
    def __init__(self, size_bytes: int, max_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
        super().__init__(f"file is {size_bytes} bytes; the limit is {max_bytes}")


class TooManyPagesError(ParseError):
    def __init__(self, page_count: int, max_pages: int) -> None:
        self.page_count = page_count
        self.max_pages = max_pages
        super().__init__(f"document has {page_count} pages; the limit is {max_pages}")


class UnsupportedFileKindError(ParseError):
    def __init__(self, file_kind: FileKind) -> None:
        self.file_kind = file_kind
        super().__init__(f"cannot read a {file_kind.value} document")


class EmptyDocumentError(ParseError):
    """The file has no pages, or none that could be read."""
