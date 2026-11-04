"""Rendering: text layer, fonts, template coverage, and deterministic bytes."""

from __future__ import annotations

import io
from pathlib import Path

import pdfplumber
import pytest
from PIL import Image, ImageDraw

from generator.render import (
    damage_image,
    pdf_bytes,
    render_html,
    write_image_pdf,
    write_pdf,
)

WANTED = {
    "A1": "pre-a-01",
    "A2": "pre-a-10",
    "B1": "pre-b-01",
    "B2": "pre-b-04",
    "CN": "pre-cn-01",
    "SOA": "pre-soa-01",
}


@pytest.fixture(scope="module")
def rendered(seeds, plans, tmp_path_factory):
    out = tmp_path_factory.mktemp("rendered")
    by_id = {plan.document_id: plan for plan in plans}
    paths = {}
    for template, document_id in WANTED.items():
        path = out / f"{template}.pdf"
        write_pdf(by_id[document_id], seeds, path)
        paths[template] = path
    return paths


def test_every_template_has_a_pdf_text_layer(rendered, plans):
    by_id = {plan.document_id: plan for plan in plans}
    for template, path in rendered.items():
        with pdfplumber.open(path) as document:
            text = "\n".join((page.extract_text() or "") for page in document.pages)
        assert text.strip(), template
        plan = by_id[WANTED[template]]
        assert plan.invoice_number in text
        assert plan.currency in text


def test_rendered_total_and_vendor_are_readable(rendered):
    with pdfplumber.open(rendered["A1"]) as document:
        text = document.pages[0].extract_text()
    assert "Stagecraft AV Rentals Pte. Ltd." in text
    assert "Total Payable" in text
    assert "000-123456-7" in text


def test_hidden_instruction_is_one_point_white_text(seeds, plans, tmp_path):
    plan = next(p for p in plans if p.document_id == "live-04")
    path = tmp_path / "hidden.pdf"
    write_pdf(plan, seeds, path)
    with pdfplumber.open(path) as document:
        page = document.pages[0]
        words = page.extract_words(extra_attrs=["size", "non_stroking_color"])
        match = next(word for word in words if word["text"] == "Ignore")
    assert match["size"] <= 1.5
    color = match["non_stroking_color"]
    assert color == (1, 1, 1) or color == (1.0, 1.0, 1.0)


def test_visible_instruction_is_normal_size(seeds, plans, tmp_path):
    plan = next(p for p in plans if p.document_id == "pre-a-09")
    path = tmp_path / "visible.pdf"
    write_pdf(plan, seeds, path)
    with pdfplumber.open(path) as document:
        words = document.pages[0].extract_words(extra_attrs=["size"])
        match = next(word for word in words if word["text"] == "AI")
    assert match["size"] > 2.0


def test_same_plan_renders_identical_bytes(seeds, plans):
    plan = plans[0]
    assert pdf_bytes(plan, seeds) == pdf_bytes(plan, seeds)


def test_bundled_fonts_are_embedded(seeds, plans, tmp_path):
    path = tmp_path / "fonts.pdf"
    write_pdf(plans[0], seeds, path)
    with pdfplumber.open(path) as document:
        font_names = {char["fontname"] for char in document.pages[0].chars}
    assert any("Invoice-Sans" in name for name in font_names), font_names
    assert any("Invoice-Mono" in name for name in font_names), font_names


def test_html_escapes_ampersands(seeds, plans):
    from dataclasses import replace

    plan = next(p for p in plans if p.document_id == "pre-a-01")
    plan = replace(plan, notes="A & B <script>")
    html = render_html(plan, seeds)
    assert "&amp;" in html
    assert "<script>" not in html


def test_image_pdf_is_one_page_without_text(tmp_path):
    image = Image.new("RGB", (80, 100), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    draw.text((10, 10), "SCAN", fill=(0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    pdf_path = tmp_path / "image.pdf"
    write_image_pdf(buffer.getvalue(), 80, 100, pdf_path)
    assert pdf_path.read_bytes().startswith(b"%PDF-1.4")
    with pdfplumber.open(pdf_path) as document:
        assert len(document.pages) == 1
        assert not (document.pages[0].extract_text() or "")
    assert pdf_path.read_bytes() == _write_again(buffer.getvalue(), 80, 100, tmp_path)


def _write_again(jpeg: bytes, width: int, height: int, tmp_path: Path) -> bytes:
    path = tmp_path / "again.pdf"
    write_image_pdf(jpeg, width, height, path)
    return path.read_bytes()


def test_damage_is_deterministic(tmp_path):
    source = tmp_path / "page.png"
    image = Image.new("RGB", (300, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 30), "INVOICE 1,090.00", fill="black")
    image.save(source)
    first = damage_image(source, seed=7)
    second = damage_image(source, seed=7)
    assert first.size == second.size == (300, 420)
    first_path = tmp_path / "first.jpg"
    second_path = tmp_path / "second.jpg"
    first.save(first_path, quality=88)
    second.save(second_path, quality=88)
    assert first_path.read_bytes() == second_path.read_bytes()


def test_damage_changes_the_page(tmp_path):
    source = tmp_path / "page.png"
    image = Image.new("RGB", (300, 420), "white")
    ImageDraw.Draw(image).text((20, 30), "INVOICE", fill="black")
    image.save(source)
    damaged = damage_image(source, seed=1)
    assert damaged.tobytes() != image.tobytes()


def test_damage_does_not_leave_a_cache_in_the_working_directory(tmp_path, monkeypatch):
    source = tmp_path / "page.png"
    Image.new("RGB", (120, 160), "white").save(source)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    damage_image(source, seed=2)
    assert not (work / "augraphy_cache").exists()
