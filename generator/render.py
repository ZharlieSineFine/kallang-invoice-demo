"""Render documents to PDF and damage type C scans with Augraphy.

WeasyPrint on macOS needs Homebrew's Pango, which is not on the default library path. We set
``DYLD_FALLBACK_LIBRARY_PATH`` before importing WeasyPrint so ``make test`` works without a
wrapper. Fonts are bundled in ``fonts/`` and referenced by relative URL from ``base_url``.
"""

from __future__ import annotations

import os
import sys
from hashlib import sha256
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from generator.money import fmt_money, fmt_plain
from generator.plans import DocumentPlan
from generator.seeds import Seeds
from generator.truth import bank_account, document_title, printed_date, totals_for, vendor_for

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_FILE = {
    "A1": "invoice_a1.html",
    "A2": "invoice_a2.html",
    "B1": "invoice_b1.html",
    "B2": "invoice_b2.html",
    "C1": "invoice_c1.html",
    "CN": "credit_note.html",
    "SOA": "statement.html",
}


def _prepare_macos_libraries() -> None:
    if sys.platform != "darwin":
        return
    current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    parts = [p for p in current.split(":") if p]
    if "/opt/homebrew/lib" not in parts:
        parts.append("/opt/homebrew/lib")
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(parts)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/invoiceflow-matplotlib")


_prepare_macos_libraries()

from weasyprint import HTML  # noqa: E402  (must follow the dyld setup)


def jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(("html", "xml")),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["money"] = fmt_money
    env.filters["qty"] = fmt_plain
    env.filters["date_printed"] = lambda value: value.strftime("%d/%m/%Y")
    return env


def template_context(plan: DocumentPlan, seeds: Seeds) -> dict[str, object]:
    vendor = vendor_for(plan, seeds)
    totals = totals_for(plan)
    account_printed, _ = bank_account(plan, vendor)
    return {
        "doc": plan,
        "vendor": vendor,
        "totals": totals,
        "lines": plan.lines,
        "title": document_title(plan),
        "date_printed": printed_date(plan, plan.invoice_date),
        "due_printed": printed_date(plan, plan.due_date) if plan.due_date else None,
        "bank_printed": account_printed,
        "gst_rate": f"{plan.gst_rate_percent.normalize():f}%",
        "hidden_text": plan.hidden_text,
        "notes": plan.notes,
    }


def render_html(plan: DocumentPlan, seeds: Seeds) -> str:
    env = jinja_env()
    template = env.get_template(_TEMPLATE_FILE[plan.template])
    return template.render(**template_context(plan, seeds))


def write_pdf(plan: DocumentPlan, seeds: Seeds, path: Path) -> None:
    """Render the plan to a digital PDF with an embedded text layer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(plan, seeds)
    base_url = Path(__file__).resolve().parents[1]
    HTML(string=html, base_url=str(base_url)).write_pdf(str(path))


def render_page_png(pdf_path: Path, png_path: Path, dpi: int = 150) -> tuple[int, int]:
    """Rasterise page 1 of a PDF to a PNG and return the pixel size."""
    import pypdfium2

    document = pypdfium2.PdfDocument(str(pdf_path))
    try:
        page = document[0]
        image = page.render(scale=dpi / 72).to_pil()
    finally:
        document.close()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(png_path, format="PNG")
    return image.size


def damage_image(png_path: Path, seed: int) -> object:
    """Apply a light rotation and blur, then Augraphy paper noise, deterministically."""
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/invoiceflow-matplotlib")
    import numpy as np
    from augraphy import AugraphyPipeline, Jpeg, SubtleNoise
    from PIL import Image, ImageFilter

    pipeline = AugraphyPipeline(
        paper_phase=[SubtleNoise(subtle_range=8, p=1)],
        post_phase=[Jpeg(quality_range=(90, 96), p=1)],
        random_seed=seed,
    )
    image = Image.open(png_path).convert("RGB")
    # A PIL rotation keeps the A4 canvas intact; Augraphy's geometric rotator crops and
    # resamples the page, which makes the small scan metadata harder to OCR. Augraphy then
    # adds the paper noise and JPEG artefacts.
    angle = 0.6 + (seed % 5) * 0.1
    image = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor="white")
    image = image.filter(ImageFilter.GaussianBlur(radius=0.4))
    original_size = image.size
    # Augraphy writes a cache into the current directory. Run it in a throw-away
    # directory so a build never leaves ``augraphy_cache/`` in the repo (and never
    # reuses a cache from a previous run).
    from tempfile import TemporaryDirectory

    previous = Path.cwd()
    with TemporaryDirectory(prefix="invoiceflow-augraphy-") as scratch:
        os.chdir(scratch)
        try:
            result = pipeline(np.array(image))
        finally:
            os.chdir(previous)
    if isinstance(result, dict):
        result = result["output"]
    damaged = Image.fromarray(np.asarray(result).astype("uint8"))
    if damaged.size != original_size:
        damaged = damaged.resize(original_size, Image.Resampling.LANCZOS)
    return damaged


def save_jpeg(image: object, path: Path) -> tuple[int, int]:
    from PIL import Image

    assert isinstance(image, Image.Image)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=88, optimize=False, progressive=False)
    return image.size


def write_image_pdf(jpeg_bytes: bytes, width: int, height: int, path: Path) -> None:
    """Write a deterministic one-page image PDF with fixed metadata and no timestamps."""
    page_width = 595.276
    page_height = 841.89
    image_name = f"Im{sha256(jpeg_bytes).hexdigest()[:12]}"
    content = f"q {page_width:.3f} 0 0 {page_height:.3f} 0 0 cm /{image_name} Do Q\n".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width:.3f} {page_height:.3f}] "
            f"/Resources << /XObject << /{image_name} 4 0 R >> >> /Contents 5 0 R >>"
        ).encode(),
        (
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            f"/Length {len(jpeg_bytes)} >>"
        ).encode()
        + b"\nstream\n"
        + jpeg_bytes
        + b"\nendstream",
        f"<< /Length {len(content)} >>".encode() + b"\nstream\n" + content + b"endstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode())
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    document_id = sha256(jpeg_bytes).hexdigest()[:32]
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R "
            f"/ID [<{document_id}> <{document_id}>] >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(pdf))


def write_scan(
    plan: DocumentPlan, seeds: Seeds, *, seed: int, jpg_path: Path, pdf_path: Path
) -> int:
    """Render C1, rasterise it, damage it, then save the JPG and the one-page image PDF."""
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix="invoiceflow-scan-") as tmp:
        digital_pdf = Path(tmp) / "digital.pdf"
        png = Path(tmp) / "page-1.png"
        write_pdf(plan, seeds, digital_pdf)
        render_page_png(digital_pdf, png, dpi=150)
        damaged = damage_image(png, seed)
        width, height = save_jpeg(damaged, jpg_path)
        jpeg_bytes = jpg_path.read_bytes()
        write_image_pdf(jpeg_bytes, width, height, pdf_path)
    return width


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def pdf_bytes(plan: DocumentPlan, seeds: Seeds) -> bytes:
    """Render to bytes (used by determinism tests)."""
    return HTML(
        string=render_html(plan, seeds), base_url=str(Path(__file__).resolve().parents[1])
    ).write_pdf()
