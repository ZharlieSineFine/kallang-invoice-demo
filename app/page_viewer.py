"""Make scanned pages readable on Review (user's report and choice, 2026-11-20).

The stored scans are 150 DPI and readable when shown 2x larger; Review showed the page at
about half size, and its zoom showed the field at its own pixel size. Two things fix that:

- the zoom under the page is enlarged ``ZOOM_SCALE`` times, with a contrast boost
- "View page large" opens the whole page full-width in a pop-up, with a size slider

The contrast boost and sharpening are for the screen only. The stored page image, the one
the model and the checks read, is never changed.
"""

from __future__ import annotations

import base64
import io

import streamlit as st
from PIL import Image, ImageFilter, ImageOps

from app.boxes import crop_region
from invoiceflow.contracts import BBox

ZOOM_SCALE = 2.5
_MAX_ZOOM_WIDTH = 1800  # px; a zoom across the whole page would otherwise be huge
_LARGE_SCALE = 2  # the large view is drawn at twice the stored size, then sized by the slider
_SIZES = (100, 300, 25, 150)  # slider: min, max, step, start (percent of the pop-up width)
_JPEG_QUALITY = 88
_OPEN = "page_viewer_open"  # (button key, page) of the pop-up that is open
_GAMMA = 1.5  # above 1 darkens mid-greys (faded print) and leaves white paper white
_DARKEN = [round(255 * (value / 255) ** _GAMMA) for value in range(256)]


def for_reading(image: Image.Image, *, scale: float) -> Image.Image:
    """A larger copy with darker text and sharper edges. The original is left as it is."""
    size = (round(image.width * scale), round(image.height * scale))
    larger = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    # Paper to white (ignoring the brightest specks), then darken grey ink with a fixed
    # curve. No clipping at the dark end: on a page with little text, the text itself would
    # be clipped away and nothing would change.
    whiter = ImageOps.autocontrast(larger, cutoff=(0, 0.5))
    darker = whiter.point(_DARKEN * 3)
    return darker.filter(ImageFilter.UnsharpMask(radius=1.5, percent=110, threshold=6))


def zoom_image(image: Image.Image, bbox: BBox) -> Image.Image:
    """The field and a little around it, enlarged for reading."""
    crop = image.crop(crop_region(bbox, image.width, image.height))
    scale = min(ZOOM_SCALE, _MAX_ZOOM_WIDTH / max(1, crop.width))
    return for_reading(crop, scale=scale)


def _jpeg_data_uri(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def large_page_html(image: Image.Image, percent: int) -> str:
    """The page in a scrolling frame, ``percent`` of the frame's width."""
    return (
        '<div data-page="large" style="overflow:auto;max-height:76vh;border:1px solid #d0d4da;'
        'border-radius:6px;background:#ffffff;">'
        f'<img src="{_jpeg_data_uri(image)}" alt="The page, enlarged" '
        f'style="width:{percent}%;max-width:none;display:block;"></div>'
    )


def _open(key: str, page: tuple) -> None:
    st.session_state[_OPEN] = (key, page)


def _close() -> None:
    st.session_state.pop(_OPEN, None)


def large_view_button(key: str, page: tuple) -> None:
    """``page`` names what is shown, e.g. (doc_id, page_no); the pop-up opens for that page."""
    st.button("View page large", key=key, on_click=_open, args=(key, page))


def render_large_view(image: Image.Image, *, key: str, page: tuple, title: str) -> None:
    """Open the pop-up when its button was pressed for this page. Call it on every run."""
    if st.session_state.get(_OPEN) != (key, page):
        return
    _large_dialog(image, key, title)


@st.dialog("The page, large", width="large", on_dismiss=_close)
def _large_dialog(image: Image.Image, key: str, title: str) -> None:
    low, high, step, start = _SIZES
    st.markdown(f"**{title}**")
    percent = st.slider(
        "Size (% of this window)", low, high, start, step, key=f"{key}_size", format="%d%%"
    )
    st.caption("Contrast boosted for reading. The stored image is unchanged.")
    st.markdown(
        large_page_html(for_reading(image, scale=_LARGE_SCALE), percent),
        unsafe_allow_html=True,
    )
    if st.button("Close", key=f"{key}_close", on_click=_close):
        st.rerun()
