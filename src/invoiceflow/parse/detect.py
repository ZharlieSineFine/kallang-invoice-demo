"""Content-based file type detection (the extension is never trusted)."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from invoiceflow.contracts import FileKind

_PDF_MAGIC = b"%PDF-"
_PDF_HEADER_WINDOW = 1024
_XML_HEADER_BYTES = 64 * 1024
_INVOICE_ROOT = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?Invoice\b", re.IGNORECASE)
_PEPPOL_MARKERS = ("peppol", "ubl", "oasis:names:specification")


def detect_file_kind(source: Path | bytes | bytearray) -> FileKind:
    """Detect PDF, IMAGE, PEPPOL_XML, XLSX, or UNKNOWN from the bytes."""
    if isinstance(source, (bytes, bytearray)):
        return _detect_bytes(bytes(source))
    return _detect_path(Path(source))


def _detect_path(path: Path) -> FileKind:
    with path.open("rb") as handle:
        header = handle.read(_PDF_HEADER_WINDOW)
    if _looks_like_pdf(header):
        return FileKind.PDF

    if _opens_as_image(path):
        return FileKind.IMAGE

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if _is_xlsx(archive.namelist()):
                return FileKind.XLSX

    with path.open("rb") as handle:
        xml_head = handle.read(_XML_HEADER_BYTES)
    if _looks_like_peppol(xml_head):
        return FileKind.PEPPOL_XML
    return FileKind.UNKNOWN


def _detect_bytes(data: bytes) -> FileKind:
    if _looks_like_pdf(data[:_PDF_HEADER_WINDOW]):
        return FileKind.PDF
    if _opens_as_image(io.BytesIO(data)):
        return FileKind.IMAGE
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if _is_xlsx(archive.namelist()):
                return FileKind.XLSX
    if _looks_like_peppol(data[:_XML_HEADER_BYTES]):
        return FileKind.PEPPOL_XML
    return FileKind.UNKNOWN


def _looks_like_pdf(header: bytes) -> bool:
    return _PDF_MAGIC in header


def _opens_as_image(source: Path | io.BytesIO) -> bool:
    try:
        with Image.open(source) as image:
            image.verify()
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def _is_xlsx(names: list[str]) -> bool:
    return any(name == "xl/workbook.xml" or name.startswith("xl/worksheets/") for name in names)


def _looks_like_peppol(data: bytes) -> bool:
    if b"<" not in data:
        return False
    text = data.decode("utf-8", errors="ignore")
    if not _INVOICE_ROOT.search(text):
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _PEPPOL_MARKERS)
