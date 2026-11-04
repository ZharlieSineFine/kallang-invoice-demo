"""The WS2 ``TextExtractor``: PDF/scan reading, hidden text, and prompt text."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError

from invoiceflow.contracts import FileKind, PageText, ParsedDocument, TextSource, Word
from invoiceflow.parse.config import ParseConfig
from invoiceflow.parse.detect import detect_file_kind
from invoiceflow.parse.errors import (
    EmptyDocumentError,
    FileTooLargeError,
    ParseError,
    TooManyPagesError,
    UnsupportedFileKindError,
)
from invoiceflow.parse.images import (
    correct_orientation,
    downscale,
    exif_oriented,
    ocr_words,
    render_page,
    save_page_image,
)
from invoiceflow.parse.pdf import extract_pdf_words, hidden_words, visible_char_count
from invoiceflow.parse.reading import page_texts
from invoiceflow.settings import data_dir


@dataclass(frozen=True)
class DocumentParser:
    """Reads a PDF or image into a ``ParsedDocument`` with page-fraction boxes."""

    config: ParseConfig = field(default_factory=ParseConfig.from_repo)
    image_root: Path | None = None

    def parse(self, path: Path, *, file_id: UUID, doc_id: UUID) -> ParsedDocument:
        path = Path(path)
        size = path.stat().st_size
        if size == 0:
            raise EmptyDocumentError(f"{path.name} is empty")
        if size > self.config.max_file_bytes:
            raise FileTooLargeError(size, self.config.max_file_bytes)

        file_kind = detect_file_kind(path)
        if file_kind is FileKind.PDF:
            pages = self._parse_pdf(path, doc_id)
        elif file_kind is FileKind.IMAGE:
            pages = (self._parse_image(path, doc_id),)
        else:
            raise UnsupportedFileKindError(file_kind)
        if not pages:
            raise EmptyDocumentError(f"{path.name} has no readable pages")
        return ParsedDocument(
            doc_id=doc_id, file_id=file_id, file_kind=file_kind, pages=tuple(pages)
        )

    def page_texts(self, document: ParsedDocument) -> tuple[str, ...]:
        return page_texts(document)

    # ------------------------------------------------------------------ PDF

    def _parse_pdf(self, path: Path, doc_id: UUID) -> tuple[PageText, ...]:
        try:
            pdf = pdfplumber.open(path)
        except Exception as exc:  # pdfminer raises several unrelated error types
            raise ParseError(f"cannot open PDF {path.name}: {exc}") from exc
        try:
            plumber_pages = list(pdf.pages)
            if len(plumber_pages) > self.config.max_pages:
                raise TooManyPagesError(len(plumber_pages), self.config.max_pages)
            if not plumber_pages:
                raise EmptyDocumentError(f"{path.name} has no pages")
            try:
                document = pdfium.PdfDocument(str(path))
            except Exception as exc:
                raise ParseError(f"cannot render PDF {path.name}: {exc}") from exc
            try:
                return tuple(
                    self._parse_pdf_page(document, index, page, doc_id)
                    for index, page in enumerate(plumber_pages)
                )
            finally:
                document.close()
        finally:
            pdf.close()

    def _parse_pdf_page(
        self, document: pdfium.PdfDocument, index: int, page: object, doc_id: UUID
    ) -> PageText:
        page_no = index + 1
        words = extract_pdf_words(page, self.config)
        visible = visible_char_count(words)
        rotation = int(getattr(page, "rotation", 0) or 0)
        if visible >= self.config.scanned_page_min_chars and rotation == 0:
            review = render_page(document, index, dpi=self.config.review_dpi)
            image_path = self._write_image(review, doc_id, page_no)
            return PageText(
                page_no=page_no,
                width_pt=float(page.width),
                height_pt=float(page.height),
                source=TextSource.PDF_TEXT,
                words=words,
                image_path=image_path,
            )
        return self._ocr_pdf_page(document, index, page_no, doc_id, words)

    def _ocr_pdf_page(
        self,
        document: pdfium.PdfDocument,
        index: int,
        page_no: int,
        doc_id: UUID,
        pdf_words: tuple[Word, ...],
    ) -> PageText:
        ocr_image = correct_orientation(render_page(document, index, dpi=self.config.ocr_dpi))
        review = downscale(ocr_image, from_dpi=self.config.ocr_dpi, to_dpi=self.config.review_dpi)
        image_path = self._write_image(review, doc_id, page_no)
        words, mean_conf = ocr_words(ocr_image)
        width_pt = review.width * 72 / self.config.review_dpi
        height_pt = review.height * 72 / self.config.review_dpi
        hidden = hidden_words(pdf_words)
        if not words and visible_char_count(pdf_words) > 0:
            # Rotated digital PDF whose OCR found nothing: keep the PDF text.
            return PageText(
                page_no=page_no,
                width_pt=width_pt,
                height_pt=height_pt,
                source=TextSource.PDF_TEXT,
                words=pdf_words,
                image_path=image_path,
            )
        return PageText(
            page_no=page_no,
            width_pt=width_pt,
            height_pt=height_pt,
            source=TextSource.OCR,
            words=(*words, *hidden),
            image_path=image_path,
            ocr_mean_conf=mean_conf,
        )

    # ---------------------------------------------------------------- image

    def _parse_image(self, path: Path, doc_id: UUID) -> PageText:
        try:
            with Image.open(path) as opened:
                opened.load()
                oriented = exif_oriented(opened)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ParseError(f"cannot open image {path.name}: {exc}") from exc
        image = correct_orientation(oriented)
        image_path = self._write_image(image, doc_id, 1)
        words, mean_conf = ocr_words(image)
        return PageText(
            page_no=1,
            width_pt=float(image.width),
            height_pt=float(image.height),
            source=TextSource.OCR,
            words=words,
            image_path=image_path,
            ocr_mean_conf=mean_conf,
        )

    # --------------------------------------------------------------- files

    def _write_image(self, image: Image.Image, doc_id: UUID, page_no: int) -> str:
        root = Path(self.image_root) if self.image_root is not None else data_dir() / "parsed"
        path = root / str(doc_id) / f"page-{page_no:03d}.png"
        save_page_image(image, path, dpi=self.config.review_dpi)
        return str(path.resolve())


def parse_document(
    path: Path,
    *,
    file_id: UUID,
    doc_id: UUID,
    config: ParseConfig | None = None,
    image_root: Path | None = None,
) -> ParsedDocument:
    """Convenience wrapper for callers that do not need to reuse a parser."""
    parser = DocumentParser(
        config=config if config is not None else ParseConfig.from_repo(),
        image_root=image_root,
    )
    return parser.parse(path, file_id=file_id, doc_id=doc_id)
