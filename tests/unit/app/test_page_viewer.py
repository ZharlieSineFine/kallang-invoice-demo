"""Scanned pages are readable on Review (user's report and choice, 2026-11-20).

The stored scans are 150 DPI and readable at 2x; Review showed them at about half size, and
its zoom showed the field at its own pixel size. Now the zoom is enlarged with a contrast
boost, and "View page large" opens the whole page full-width with a size slider. Only what
is shown changes: the stored page image is never altered.
"""

from __future__ import annotations

from PIL import Image, ImageChops
from test_pages import _run, _set_doc

from app.page_viewer import ZOOM_SCALE, for_reading, zoom_image
from app.pages import review
from invoiceflow.contracts import BBox


def _page() -> Image.Image:
    page = Image.new("RGB", (1240, 1754), (246, 246, 244))
    word = Image.new("RGB", (100, 20), (110, 110, 110))  # a grey "word" to read
    page.paste(word, (600, 800))
    return page


def test_reading_copy_is_larger_and_darker_and_the_original_is_untouched():
    page = _page()
    before = page.copy()
    reading = for_reading(page, scale=2)
    assert reading.size == (2480, 3508)
    assert reading.getpixel((1300, 1620))[0] < 110  # the grey word is darker
    assert not ImageChops.difference(page, before).getbbox()


def test_the_zoom_enlarges_the_field():
    box = BBox(x0=600 / 1240, y0=800 / 1754, x1=700 / 1240, y1=820 / 1754)
    zoom = zoom_image(_page(), box)
    assert ZOOM_SCALE >= 2
    assert zoom.width >= 100 * ZOOM_SCALE  # wider than the field at its stored size


def test_a_very_wide_zoom_is_capped():
    box = BBox(x0=0.0, y0=0.4, x1=1.0, y1=0.45)
    assert zoom_image(_page(), box).width <= 1800


def _review(fake_backend, bundle):
    at = _set_doc(_run(review, fake_backend), bundle.document.doc_id)
    return at.run(timeout=30)


def test_the_zoom_says_it_is_enlarged_for_reading(fake_backend, mismatch_bundle):
    at = _review(fake_backend, mismatch_bundle)
    at.get_by_key("review_field").set_value("subtotal").run(timeout=30)
    assert any(
        "Zoom: subtotal" in item.value and "contrast boosted for reading" in item.value
        for item in at.caption
    )


def test_view_page_large_opens_the_page_full_width_with_a_size_slider(
    fake_backend, mismatch_bundle
):
    at = _review(fake_backend, mismatch_bundle)
    at.button(key="review_page_large").click().run(timeout=30)
    slider = at.slider(key="review_page_large_size")
    assert slider.value == 150
    large = [m.value for m in at.markdown if 'data-page="large"' in m.value]
    assert len(large) == 1 and "width:150%" in large[0]
    assert "data:image/jpeg;base64," in large[0]

    slider.set_value(250).run(timeout=30)
    large = [m.value for m in at.markdown if 'data-page="large"' in m.value]
    assert "width:250%" in large[0]
