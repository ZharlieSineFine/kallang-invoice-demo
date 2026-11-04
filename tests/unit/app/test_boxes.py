"""Box geometry and the three-page alignment check.

Two pages are the golden fixtures; the third is a synthetic page built in the test, so the
overlay is exercised against text that did not come from the golden PDFs.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PIL import Image

from app.boxes import (
    FLAGGED,
    FUZZY,
    PASSED,
    crop_region,
    draw_boxes,
    field_status,
    find_text_box,
    load_page_text,
    page_boxes,
    scale_bbox,
    text_in_bbox,
    words_in_bbox,
)
from app.models import FieldRow, FindingRow, LineItemRow
from invoiceflow.contracts import (
    BBox,
    Confidence,
    MatchType,
    PageText,
    Scope,
    Severity,
    TextSource,
    Word,
)


def _word(text: str, x0: float, y0: float, x1: float, y1: float) -> Word:
    return Word(text=text, bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1))


def _finding(field: str, rule_id: str = "R02") -> FindingRow:
    return FindingRow(
        rule_id=rule_id,
        field=field,
        severity=Severity.FLAG,
        scope=Scope.FIELD,
        message="m",
    )


def _synthetic_page() -> tuple[PageText, FieldRow, FindingRow]:
    total = _word("1,234.00", 0.60, 0.40, 0.80, 0.48)
    page = PageText(
        page_no=1,
        width_pt=400,
        height_pt=200,
        source=TextSource.PDF_TEXT,
        words=(_word("Total", 0.40, 0.40, 0.55, 0.48), total),
    )
    field = FieldRow(
        name="total",
        value_raw="1,234.00",
        value_norm="1234.00",
        page_no=1,
        bbox=total.bbox,
        match_type=MatchType.EXACT,
        match_score=100,
        confidence=Confidence.HIGH,
    )
    return page, field, _finding("total")


def test_field_status_colours():
    flagged = _finding("subtotal")
    assert field_status("subtotal", (flagged,)) == "flagged"
    assert field_status("total", (flagged,), match_type=MatchType.FUZZY) == "fuzzy"
    assert field_status("total", (), confidence=Confidence.MEDIUM) == "fuzzy"
    assert field_status("total", (), match_type=MatchType.NONE) == "fuzzy"
    assert field_status("total", ()) == "passed"


def test_scale_and_crop_stay_inside_the_page():
    box = BBox(x0=0.10, y0=0.20, x1=0.30, y1=0.40)
    assert scale_bbox(box, 1000, 500) == (100, 100, 300, 200)
    assert scale_bbox(BBox(x0=0, y0=0, x1=1, y1=1), 100, 100, padding=0.5) == (0, 0, 100, 100)
    left, upper, right, lower = crop_region(box, 1000, 500, margin=0.02)
    assert 0 <= left < right <= 1000
    assert 0 <= upper < lower <= 500
    assert left < 100 and upper < 100 and right > 300 and lower > 200


def test_find_text_box_exact_fuzzy_and_missing():
    page, field, _ = _synthetic_page()
    match = find_text_box(page, "1,234.00")
    assert match.match_type is MatchType.EXACT and match.bbox == field.bbox
    fuzzy = find_text_box(page, "1,234.000")
    assert fuzzy.match_type is MatchType.FUZZY and fuzzy.score >= 90
    assert find_text_box(page, "not on the page").bbox is None
    assert find_text_box(page, None).match_type is MatchType.NONE


def test_draw_boxes_returns_a_new_image():
    page, field, finding = _synthetic_page()
    image = Image.new("RGB", (400, 200), "white")
    boxes = page_boxes(page, (field,), (), (finding,), selected="total")
    assert len(boxes) == 1 and boxes[0].status == "flagged" and boxes[0].selected
    drawn = draw_boxes(image, boxes, selected="total")
    assert drawn is not image
    assert image.getpixel((0, 0)) == (255, 255, 255)
    x0, y0, _, _ = scale_bbox(field.bbox, 400, 200)
    assert drawn.getpixel((x0, y0))[:3] != (255, 255, 255)


def test_page_boxes_align_on_three_sample_pages(golden, clean_bundle, mismatch_bundle):
    """The done-when check: boxes line up with the words on three pages."""
    samples = [(clean_bundle, "SAV-2026-0412"), (mismatch_bundle, "SAV-2026-0413")]
    for bundle, invoice_number in samples:
        page = load_page_text(Path(bundle.pages[0].words_path))
        boxes = page_boxes(
            page, bundle.fields, bundle.line_items, bundle.findings, selected="subtotal"
        )
        assert {box.field for box in boxes} >= {"subtotal", "total", "line_items[0].amount"}
        for box in boxes:
            printed = text_in_bbox(page, box.bbox)
            assert printed, f"{invoice_number}: empty box for {box.field}"
            assert words_in_bbox(page, box.bbox)
        subtotal = next(box for box in boxes if box.field == "subtotal")
        assert text_in_bbox(page, subtotal.bbox) == (
            "1,080.00" if invoice_number.endswith("412") else "1,090.00"
        )
        assert subtotal.selected

    synthetic_page, field, finding = _synthetic_page()
    synthetic_boxes = page_boxes(synthetic_page, (field,), (), (finding,), selected="total")
    assert len(synthetic_boxes) == 1
    assert text_in_bbox(synthetic_page, synthetic_boxes[0].bbox) == "1,234.00"
    assert synthetic_boxes[0].status == "flagged"
    assert synthetic_boxes[0].selected


def test_example_colors_are_the_traffic_lights():
    assert PASSED == "#2e7d32"
    assert FUZZY == "#f9a825"
    assert FLAGGED == "#c62828"


def test_mismatch_subtotal_is_red_and_clean_is_green(clean_bundle, mismatch_bundle):
    clean_page = load_page_text(Path(clean_bundle.pages[0].words_path))
    clean = page_boxes(
        clean_page, clean_bundle.fields, clean_bundle.line_items, clean_bundle.findings
    )
    assert next(box for box in clean if box.field == "subtotal").status == "passed"

    bad_page = load_page_text(Path(mismatch_bundle.pages[0].words_path))
    bad = page_boxes(
        bad_page, mismatch_bundle.fields, mismatch_bundle.line_items, mismatch_bundle.findings
    )
    assert next(box for box in bad if box.field == "subtotal").status == "flagged"


def test_line_item_boxes_cover_description_and_amount(clean_bundle):
    page = load_page_text(Path(clean_bundle.pages[0].words_path))
    boxes = page_boxes(
        page,
        clean_bundle.fields,
        (
            LineItemRow(
                line_no=1,
                description="LED wall panel rental",
                amount=Decimal("540.00"),
            ),
        ),
        (),
    )
    fields = {box.field for box in boxes}
    assert {"line_items[0].description", "line_items[0].amount"} <= fields


def test_load_page_text_reads_the_contract_json(golden):
    page = load_page_text(Path(golden.fixtures[0].directory) / "page-1.words.json")
    assert page.page_no == 1 and page.visible_words
