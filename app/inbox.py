"""The inbox grid: a thumbnail card per document, colored by what happened to it."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from uuid import UUID

import streamlit as st
from PIL import Image

from app import ui
from app.models import DocumentSummary
from invoiceflow.contracts import DocStatus, DocType
from invoiceflow.parse.images import render_pdf_page
from invoiceflow.settings import data_dir

_THUMBNAIL_WIDTH = 360
_PDF_THUMBNAIL_DPI = 72  # enough for a 360 px card; page images replace it once read
_PROCESSING = "Processing…"
_TONES = {
    DocStatus.AUTO_PASSED: "passed",
    DocStatus.APPROVED: "passed",
    DocStatus.EXPORTED: "passed",
    DocStatus.NEEDS_REVIEW: "flagged",
    DocStatus.MANUAL_ENTRY: "flagged",
    DocStatus.ON_HOLD: "held",
}
_TONE_COLORS = {
    "passed": ("#e8f5e9", "#1b5e20"),
    "flagged": ("#fff4e0", "#8a5200"),
    "held": ("#fdecec", "#b71c1c"),
    "processing": ("#e3f2fd", "#0d47a1"),
    "other": ("#f1f3f5", "#5a6068"),
}
_TYPE_NAMES = {
    DocType.TAX_INVOICE: "Tax invoice",
    DocType.SIMPLIFIED_TAX_INVOICE: "Simplified tax invoice",
    DocType.INVOICE: "Invoice",
    DocType.CREDIT_NOTE: "Credit note",
    DocType.DEBIT_NOTE: "Debit note",
    DocType.STATEMENT: "Statement",
    DocType.QUOTATION: "Quotation",
    DocType.DELIVERY_ORDER: "Delivery order",
    DocType.OTHER: "Other document",
}
_TEMPLATE_NAMES = {"CN": "Credit note", "SOA": "Statement"}


@dataclass(frozen=True)
class InboxCard:
    doc_id: UUID
    image_path: str | None
    type_label: str
    vendor: str
    amount: str
    tone: str
    outcome: str
    rules: tuple[str, ...] = ()


def _template_label(template: str) -> str:
    return _TEMPLATE_NAMES.get(template) or f"Type {template[:1]}"


def load_type_labels(path: Path | None = None) -> dict[UUID, str]:
    """Generator template per document. Anything uploaded later is simply not in here."""
    manifest = path or data_dir() / "generated" / "manifest.json"
    try:
        documents = json.loads(manifest.read_text(encoding="utf-8"))["documents"]
    except (OSError, ValueError, KeyError):
        return {}
    return {UUID(doc["doc_id"]): _template_label(doc["template"]) for doc in documents}


def _processing_card(doc: DocumentSummary, labels: dict[UUID, str]) -> InboxCard:
    """The model is still reading it: show the uploaded file, not an outcome."""
    return InboxCard(
        doc_id=doc.doc_id,
        image_path=doc.file_path,
        type_label=labels.get(doc.doc_id) or "Reading the page",
        vendor=doc.file_name or "Uploaded file",
        amount=ui.money_metric(None),
        tone="processing",
        outcome=_PROCESSING,
    )


def inbox_card(doc: DocumentSummary, labels: dict[UUID, str]) -> InboxCard:
    if doc.is_processing:
        return _processing_card(doc, labels)
    if doc.doc_type is not None:
        type_label = _TYPE_NAMES[doc.doc_type]
    else:
        type_label = labels.get(doc.doc_id) or doc.printed_title or "Unclassified"
    return InboxCard(
        doc_id=doc.doc_id,
        image_path=doc.first_page_image,
        type_label=type_label,
        vendor=doc.vendor_name or doc.supplier_name or "Unknown vendor",
        amount=ui.money_metric(doc.total),
        tone=_TONES.get(doc.status, "other"),
        outcome=doc.status.value.replace("_", " ").capitalize(),
        rules=doc.open_rules,
    )


@st.cache_data(show_spinner=False)
def _thumbnail_bytes(path: str, modified: float) -> bytes:
    del modified  # part of the cache key only
    with Path(path).open("rb") as handle:
        is_pdf = handle.read(5) == b"%PDF-"
    # An upload still being read has no page image yet; its stored file has no extension.
    image = render_pdf_page(Path(path), dpi=_PDF_THUMBNAIL_DPI) if is_pdf else Image.open(path)
    with image:
        small = image.convert("RGB")
        small.thumbnail((_THUMBNAIL_WIDTH, _THUMBNAIL_WIDTH * 2))
        buffer = BytesIO()
        small.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _thumbnail(path: str | None) -> bytes | None:
    resolved = ui.resolve_path(path)
    if resolved is None or not resolved.is_file():
        return None
    return _thumbnail_bytes(str(resolved), resolved.stat().st_mtime)


def _card_html(card: InboxCard) -> str:
    background, color = _TONE_COLORS[card.tone]
    rules = f" · {escape(', '.join(card.rules))}" if card.rules else ""
    return (
        f'<div style="background:{background};color:{color};border-radius:6px;'
        f'padding:0.2rem 0.5rem;font-size:0.8rem;font-weight:600;">'
        f"{escape(card.outcome)}{rules}</div>"
        f'<div style="font-size:0.75rem;margin-top:0.3rem;opacity:0.75;">'
        f"{escape(card.type_label)}</div>"
        f'<div style="font-weight:600;font-size:0.85rem;">{escape(card.vendor)}</div>'
        f'<div style="font-size:0.9rem;">{escape(card.amount)}</div>'
    )


def _open_document(doc_id: UUID) -> None:
    """Runs before widgets are instantiated, so it may legally flip the page key."""
    st.session_state["selected_doc_id"] = doc_id
    st.session_state["page"] = "Review"


def render_grid(docs: Sequence[DocumentSummary], *, columns: int = 5) -> None:
    labels = load_type_labels()
    cards = [inbox_card(doc, labels) for doc in docs]
    grid = st.columns(columns)
    for index, card in enumerate(cards):
        with grid[index % columns].container(border=True):
            image = _thumbnail(card.image_path)
            if image is not None:
                st.image(image, width="stretch")
            st.markdown(_card_html(card), unsafe_allow_html=True)
            if card.tone == "processing":
                continue  # nothing to open until it has an outcome
            # The Queue grid runs in an auto-refreshing fragment; a click there reruns only
            # the fragment, so rerun the whole app to switch pages.
            if st.button(
                "Open",
                key=f"inbox_open_{card.doc_id}",
                on_click=_open_document,
                args=(card.doc_id,),
                width="stretch",
            ):
                st.rerun()
