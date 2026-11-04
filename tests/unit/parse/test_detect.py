from __future__ import annotations

import io
import zipfile

from helpers import build_pdf, simple_text_pdf
from PIL import Image

from invoiceflow.contracts import FileKind
from invoiceflow.parse import detect_file_kind


def _write(path, data: bytes):
    path.write_bytes(data)
    return path


def test_pdf_is_detected_by_content_not_extension(tmp_path):
    path = _write(tmp_path / "looks-like-an-image.png", simple_text_pdf())
    assert detect_file_kind(path) is FileKind.PDF


def test_png_is_detected_by_content_not_extension(tmp_path):
    path = tmp_path / "looks-like-a-pdf.pdf"
    Image.new("RGB", (20, 20), "white").save(path, format="PNG")
    assert detect_file_kind(path) is FileKind.IMAGE


def test_jpeg_is_an_image(tmp_path):
    path = tmp_path / "photo.bin"
    Image.new("RGB", (20, 20), "white").save(path, format="JPEG")
    assert detect_file_kind(path) is FileKind.IMAGE


def test_peppol_xml_is_detected(tmp_path):
    path = tmp_path / "invoice.txt"
    path.write_text(
        '<?xml version="1.0"?>'
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
        'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        "<cbc:ID>INV-1</cbc:ID></Invoice>",
        encoding="utf-8",
    )
    assert detect_file_kind(path) is FileKind.PEPPOL_XML


def test_xlsx_is_detected_from_the_zip_directory(tmp_path):
    path = tmp_path / "workbook.dat"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    _write(path, buffer.getvalue())
    assert detect_file_kind(path) is FileKind.XLSX


def test_unknown_content_is_unknown(tmp_path):
    path = _write(tmp_path / "mystery.pdf", b"not a document at all")
    assert detect_file_kind(path) is FileKind.UNKNOWN


def test_empty_file_is_unknown(tmp_path):
    path = _write(tmp_path / "empty", b"")
    assert detect_file_kind(path) is FileKind.UNKNOWN


def test_bytes_are_accepted_as_well_as_paths(tmp_path):
    assert detect_file_kind(simple_text_pdf()) is FileKind.PDF
    image_bytes = io.BytesIO()
    Image.new("RGB", (5, 5), "white").save(image_bytes, format="PNG")
    assert detect_file_kind(image_bytes.getvalue()) is FileKind.IMAGE
    assert detect_file_kind(build_pdf([b"BT ET"])) is FileKind.PDF


def test_xlsx_is_detected_from_bytes(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    data = buffer.getvalue()
    assert detect_file_kind(data) is FileKind.XLSX


def test_a_zip_without_excel_parts_is_unknown(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
    path = _write(tmp_path / "document.zip", buffer.getvalue())
    assert detect_file_kind(path) is FileKind.UNKNOWN
    assert detect_file_kind(buffer.getvalue()) is FileKind.UNKNOWN


def test_generic_xml_without_a_peppol_namespace_is_unknown(tmp_path):
    path = tmp_path / "plain.xml"
    path.write_text("<Invoice><ID>1</ID></Invoice>", encoding="utf-8")
    assert detect_file_kind(path) is FileKind.UNKNOWN


def test_truncated_image_is_unknown(tmp_path):
    path = _write(tmp_path / "broken.png", b"\x89PNG\r\n\x1a\n" + b"not enough data")
    assert detect_file_kind(path) is FileKind.UNKNOWN
