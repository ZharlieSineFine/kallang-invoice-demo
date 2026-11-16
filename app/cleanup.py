"""Values the system changed on its own, shown first and highlighted for the reviewer.

The pipeline logs a ``normalize.cleaned`` event at intake. This rebuilds the same list from
the stored printed and normalized values, with the same function, so the two always agree.
Dates and amounts change form by design (28/10/2026 -> 2026-10-28) and are not listed.
The HTML sets its own text colors so it reads the same in both Streamlit themes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from html import escape

import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler

from app.models import FieldRow
from invoiceflow.normalize.text import reference_cleanup

_LABELS = {"invoice_number": "Invoice number"}
_REASONS = {
    "invoice_number": (
        "OCR added spaces around a hyphen or slash. Duplicate checks compare letters and "
        "digits only, so neither form can hide a repeat."
    ),
}
_HIGHLIGHT = "background-color: #fff4e0; color: #5c3700; font-weight: 600"
_BOX = (
    "background:#fff4e0;color:#3d2a00;border:2px solid #e8a33d;border-left:8px solid #e8a33d;"
    "border-radius:8px;padding:0.75rem 0.9rem;margin-bottom:0.75rem;"
)
_VALUE = (
    "font-family:monospace;font-size:1rem;background:#ffffff;color:#1f2328;"
    "border:1px solid #e0c48f;border-radius:4px;padding:0.05rem 0.35rem;"
)


@dataclass(frozen=True)
class Cleanup:
    field: str
    label: str
    printed: str
    stored: str
    reason: str


def cleanups(fields: Iterable[FieldRow]) -> tuple[Cleanup, ...]:
    found = []
    for field in fields:
        if field.name not in _LABELS:
            continue
        change = reference_cleanup(field.value_raw)
        if change is None or change[1] != field.value_norm:
            continue
        printed, stored = change
        found.append(
            Cleanup(field.name, _LABELS[field.name], printed, stored, _REASONS[field.name])
        )
    return tuple(found)


def _item_html(change: Cleanup) -> str:
    return (
        '<div style="margin-top:0.6rem;">'
        f'<div style="font-weight:700;">{escape(change.label)}</div>'
        '<div style="margin-top:0.2rem;">Read on the invoice: '
        f'<span style="{_VALUE}">{escape(change.printed)}</span></div>'
        '<div style="margin-top:0.2rem;">Stored as: '
        f'<span style="{_VALUE}">{escape(change.stored)}</span></div>'
        f'<div style="margin-top:0.25rem;font-size:0.9rem;">Why: {escape(change.reason)}</div>'
        "</div>"
    )


def cleanup_box_html(changes: tuple[Cleanup, ...]) -> str:
    if not changes:
        return ""
    count = len(changes)
    noun = "value" if count == 1 else "values"
    return (
        f'<div data-cleanups="{count}" style="{_BOX}">'
        '<div style="font-weight:800;font-size:1.05rem;">⚠️ Changed automatically by the '
        f"system: {count} {noun}</div>"
        '<div style="font-size:0.9rem;margin-top:0.15rem;">Made by the system, not by a person. '
        "Compare with the invoice image before approving.</div>"
        + "".join(_item_html(change) for change in changes)
        + "</div>"
    )


def show_cleanups(fields: Iterable[FieldRow]) -> set[str]:
    """Render the box (nothing when no value changed). Returns the changed field names, for
    ``highlight_cleaned``."""
    changes = cleanups(fields)
    if changes:
        st.markdown(cleanup_box_html(changes), unsafe_allow_html=True)
    return {change.field for change in changes}


def highlight_cleaned(frame: pd.DataFrame, names: set[str]) -> Styler:
    """The values table with each changed row in the box's color."""

    def style(row: pd.Series) -> list[str]:
        return [_HIGHLIGHT if row["field"] in names else "" for _ in row]

    return frame.style.apply(style, axis=1)
