"""Shared Streamlit helpers: backend construction, flash messages, action errors."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import streamlit as st

from app.backend import PostgresBackend
from invoiceflow.settings import repo_root


def get_backend() -> PostgresBackend:
    return PostgresBackend()


def flash(message: str, kind: str = "success") -> None:
    st.session_state["_ws7_flash"] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("_ws7_flash", None)
    if not item:
        return
    kind, message = item
    getattr(st, kind, st.info)(message)


def run_action[T](action: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
    """Run a review write, flash the outcome, and rerun so every panel refreshes."""
    try:
        outcome = action(*args, **kwargs)
    except (ValueError, LookupError) as exc:
        flash(str(exc), "error")
        st.rerun()
        return None
    message = getattr(outcome, "message", "Saved")
    status = getattr(outcome, "status", None)
    kind = "warning" if getattr(outcome, "blocked", False) else "success"
    if status is not None and getattr(status, "value", "") in {"NEEDS_REVIEW", "ON_HOLD"}:
        kind = "warning"
    flash(message, kind)
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
    # The Queue page (or another page) can point us at a document after this widget was
    # first rendered; a keyed selectbox keeps its old value, so move it before the widget.
    if wanted in ids and st.session_state.get(key) not in (None, wanted):
        st.session_state[key] = wanted
    index = ids.index(wanted) if wanted in ids else 0
    chosen = st.selectbox(
        label,
        ids,
        index=index,
        format_func=lambda doc_id: by_id[doc_id].label,
        key=key,
    )
    st.session_state["selected_doc_id"] = chosen
    return chosen


def resolve_path(path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return repo_root() / candidate


def money_metric(value) -> str:
    return "—" if value is None else f"{value:,.2f}"
