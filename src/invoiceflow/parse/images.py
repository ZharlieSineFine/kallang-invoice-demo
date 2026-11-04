"""Page rendering, EXIF correction, orientation detection, and Tesseract OCR."""

from __future__ import annotations

from pathlib import Path
from statistics import fmean

import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output

from invoiceflow.contracts import BBox, Word

_MIN_ORIENTATION_CONFIDENCE = 1.0
_ROTATIONS = {0, 90, 180, 270}


def render_page(document: pdfium.PdfDocument, page_index: int, *, dpi: int) -> Image.Image:
    """Render one PDF page, applying its /Rotate, at the requested DPI."""
    bitmap = document[page_index].render(scale=dpi / 72)
    try:
        return bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()


def render_pdf_page(path: Path, *, page_index: int = 0, dpi: int = 150) -> Image.Image:
    document = pdfium.PdfDocument(str(path))
    try:
        return render_page(document, page_index, dpi=dpi)
    finally:
        document.close()


def exif_oriented(image: Image.Image) -> Image.Image:
    """Apply the camera's EXIF orientation so boxes line up with the review image."""
    return ImageOps.exif_transpose(image).convert("RGB")


def correct_orientation(image: Image.Image) -> Image.Image:
    """Rotate a sideways page using Tesseract's orientation detection."""
    try:
        osd = pytesseract.image_to_osd(image, output_type=Output.DICT)
    except (pytesseract.TesseractError, RuntimeError, ValueError, OSError):
        return image
    rotate = _as_int(osd.get("rotate"), 0) % 360
    confidence = _as_float(osd.get("orientation_conf"), 0.0)
    if rotate not in _ROTATIONS or rotate == 0:
        return image
    if confidence < _MIN_ORIENTATION_CONFIDENCE:
        return image
    return image.rotate(-rotate, expand=True, resample=Image.Resampling.BICUBIC, fillcolor="white")


def downscale(image: Image.Image, *, from_dpi: int, to_dpi: int) -> Image.Image:
    if from_dpi <= to_dpi:
        return image
    width = max(1, round(image.width * to_dpi / from_dpi))
    height = max(1, round(image.height * to_dpi / from_dpi))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def save_page_image(image: Image.Image, path: Path, *, dpi: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, format="PNG", dpi=(dpi, dpi))
    return path


def ocr_words(image: Image.Image) -> tuple[tuple[Word, ...], float | None]:
    """Run Tesseract ``image_to_data``; return words with page-fraction boxes."""
    data = pytesseract.image_to_data(image, output_type=Output.DICT)
    width, height = image.size
    words: list[Word] = []
    confidences: list[float] = []
    for index, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text).strip()
        confidence = _as_float(data["conf"][index], -1.0)
        if not text or confidence < 0:
            continue
        left = _as_float(data["left"][index], 0.0)
        top = _as_float(data["top"][index], 0.0)
        box_width = _as_float(data["width"][index], 0.0)
        box_height = _as_float(data["height"][index], 0.0)
        words.append(
            Word(
                text=text,
                bbox=_pixel_box(left, top, box_width, box_height, width, height),
                conf=confidence,
                hidden=False,
            )
        )
        confidences.append(confidence)
    mean = round(fmean(confidences), 2) if confidences else None
    return tuple(words), mean


def _pixel_box(
    left: float, top: float, width: float, height: float, page_width: int, page_height: int
) -> BBox:
    x0 = _clamp(left / page_width if page_width else 0.0)
    y0 = _clamp(top / page_height if page_height else 0.0)
    x1 = _clamp((left + width) / page_width if page_width else 0.0)
    y1 = _clamp((top + height) / page_height if page_height else 0.0)
    return BBox(x0=min(x0, x1), y0=min(y0, y1), x1=max(x0, x1), y1=max(y0, y1))


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _as_int(value: object, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _as_float(value: object, fallback: float) -> float:
    try:
        return float(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback
