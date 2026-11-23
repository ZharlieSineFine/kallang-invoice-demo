"""Shared Streamlit helpers: backend construction, flash messages, action errors."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Any
from uuid import UUID

import streamlit as st
from PIL import Image

from app.backend import PostgresBackend
from app.boxes import load_page_text
from app.models import DocumentBundle, FindingRow, PageRow
from app.notice import Act, Notice, done_notice, failed_notice
from app.notice_view import card_html, popup_html
from invoiceflow.contracts import PageText
from invoiceflow.settings import data_dir, repo_root


def get_backend() -> PostgresBackend:
    return PostgresBackend()


# An action's result shows twice, so nobody scrolls back up to read it (2026-11-20): as a
# colored pop-up in the corner, once, and as a colored card next to the buttons that were
# pressed (``at``), until the next action. A result with no ``at`` shows at the top of the
# page instead, once. ``app.notice`` decides the words and color; ``app.notice_view`` draws.
_POPUP_KEY = "_ws7_toast"
_RESULT_KEY = "_ws7_result"


def flash(notice: Notice, *, at: str | None = None) -> None:
    st.session_state[_POPUP_KEY] = notice
    st.session_state[_RESULT_KEY] = (notice, at)


def show_flash() -> None:
    """Call it at the top of a page: the pop-up, and a result that has no place of its own."""
    popup = st.session_state.pop(_POPUP_KEY, None)
    if popup is not None:
        st.markdown(popup_html(popup), unsafe_allow_html=True)
    result = st.session_state.get(_RESULT_KEY)
    if result and result[1] is None:
        del st.session_state[_RESULT_KEY]
        st.markdown(card_html(result[0]), unsafe_allow_html=True)


def show_result(at: str) -> None:
    """Call it right under the buttons that pass ``at`` to ``run_action`` or ``flash``."""
    result = st.session_state.get(_RESULT_KEY)
    if result and result[1] == at:
        st.markdown(card_html(result[0]), unsafe_allow_html=True)


def run_action[T](
    action: Callable[..., T], *args: Any, act: Act, at: str | None = None
) -> T | None:
    """Run a write, flash what it did (next to ``at``), and rerun so every panel refreshes."""
    try:
        outcome = action(*args)
    except (ValueError, LookupError) as exc:
        flash(failed_notice(act, exc), at=at)
        st.rerun()
        return None
    flash(done_notice(act, outcome), at=at)
    st.rerun()
    return outcome


def reviewer_name() -> str:
    return (
        st.text_input(
            "Reviewer",
            value=st.session_state.get("reviewer_name", "demo.reviewer"),
            key="reviewer_name",
            help="Recorded on every review action and event.",
        ).strip()
        or "demo.reviewer"
    )


def document_picker(docs, *, key: str, label: str = "Document") -> UUID | None:
    if not docs:
        return None
    by_id = {doc.doc_id: doc for doc in docs}
    ids = list(by_id)
    wanted = st.session_state.get("selected_doc_id")
    shown = f"{key}__shown"  # what this picker last showed
    current = st.session_state.get(key)
    if wanted in ids and wanted != st.session_state.get(shown):
        # Another page or button chose a document since this picker last ran (the Queue's
        # Open, a step button): follow it. Without this check the user's own pick, which
        # arrives in st.session_state[key], would be overwritten by the previous choice.
        current = wanted
    elif current not in ids:
        current = wanted if wanted in ids else ids[0]
    st.session_state[key] = current  # set before the widget exists, so no index is passed
    chosen = st.selectbox(
        label,
        ids,
        format_func=lambda doc_id: by_id[doc_id].label,
        key=key,
    )
    st.session_state["selected_doc_id"] = chosen
    st.session_state[shown] = chosen
    return chosen


def resolve_path(path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    # The pipeline stores silver and gold paths relative to data/, fixtures relative to the repo.
    for base in (repo_root(), data_dir()):
        if (base / candidate).exists():
            return base / candidate
    return repo_root() / candidate


def load_image(path: str | None) -> Image.Image | None:
    resolved = resolve_path(path)
    if resolved is None or not resolved.is_file():
        return None
    return Image.open(resolved)


def page_words(bundle: DocumentBundle, page_no: int) -> tuple[PageRow | None, PageText | None]:
    page = next((p for p in bundle.pages if p.page_no == page_no), None)
    if page is None or not page.words_path:
        return page, None
    try:
        return page, load_page_text(resolve_path(page.words_path) or page.words_path)
    except (OSError, ValueError):
        return page, None


def technical_view() -> bool:
    return bool(st.session_state.get("technical_view", False))


_EVIDENCE_LABELS = {
    "po_number": "PO",
    "po_amount": "PO total",
    "po_invoiced": "already invoiced",
    "po_open_amount": "PO open",
    "po_vendor_id": "PO vendor",
    "po_vendor_name": "PO vendor",
    "invoice_vendor_id": "invoice vendor",
    "invoice_vendor_name": "invoice vendor",
    "vendor_id": "vendor",
    "vendor_name": "vendor",
    "prior_invoice_number": "earlier invoice",
    "prior_invoice_date": "earlier invoice date",
    "window_days": "window",
    "invoice_number": "invoice number",
    "invoice_total": "invoice total",
    "invoice_bank_account": "bank on invoice",
    "vendor_bank_account": "bank in vendor master",
    "lines_sum": "lines sum",
    "subtotal": "subtotal",
    "pages": "pages",
    "count": "count",
    "phrases": "phrases",
    "canary": "canary",
}

_MASTER_SOURCES = (
    ("po_amount", "purchase-order master data (from SAP; synthetic seeds in this demo)"),
    ("po_open_amount", "purchase-order master data (from SAP; synthetic seeds in this demo)"),
    ("vendor_bank_account", "vendor master data (from SAP; synthetic seeds in this demo)"),
)


def _evidence_line(finding: FindingRow) -> str:
    return " · ".join(
        f"{_EVIDENCE_LABELS.get(key, key)}={value}" for key, value in finding.evidence.items()
    )


def finding_card_html(finding: FindingRow) -> str:
    """Raw HTML on purpose: Streamlit's markdown parser turns $...$ into LaTeX math, which
    mangles money amounts. Text colors are explicit so the card reads in both themes."""
    field_name = finding.field or "document"
    severity = finding.severity.value
    accent = "#3b82f6" if severity == "INFO" else "#d94f4f"
    background = "#eef5ff" if severity == "INFO" else "#fdecec"
    card = (
        f'<div style="background:{background};border-left:4px solid {accent};'
        f'padding:0.6rem 0.9rem;border-radius:6px;margin-bottom:0.6rem;color:#1f2328;">'
        f'<span style="font-weight:600;color:{accent};">{escape(finding.rule_id)}</span>'
        f'<span style="color:#5a6068;"> · {escape(severity)} · {escape(field_name)}</span>'
        f'<div style="margin-top:0.3rem;">{escape(finding.message)}</div>'
    )
    if finding.evidence:
        card += (
            f'<div style="margin-top:0.3rem;font-size:0.85rem;color:#5a6068;">'
            f"{escape(_evidence_line(finding))}</div>"
        )
        source = next((label for key, label in _MASTER_SOURCES if key in finding.evidence), None)
        if source is not None:
            card += (
                f'<div style="margin-top:0.15rem;font-size:0.8rem;color:#5a6068;">'
                f"📚 Source: {escape(source)}</div>"
            )
    return card + "</div>"


def money_metric(value) -> str:
    return "—" if value is None else f"{value:,.2f}"
