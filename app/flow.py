"""The pipeline flow strip: Intake -> Read -> Extract -> Check -> Review -> Export.

Each stage is colored by what the documents in the database actually did, so the strip is
evidence, not decoration. The HTML sets its own text colors to read in both Streamlit themes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from html import escape

import streamlit as st

from app.counts import IntakeCounts, intake_counts, is_invoice
from app.models import DocumentSummary
from invoiceflow.contracts import DocStatus, Severity

STAGES = ("Intake", "Read", "Extract", "Check", "Review", "Export")


class StageTone(StrEnum):
    PASSED = "passed"
    FLAGGED = "flagged"
    HELD = "held"
    IDLE = "idle"


@dataclass(frozen=True)
class StageOutcome:
    name: str
    tone: StageTone
    summary: str


_COLORS = {
    StageTone.PASSED: ("#e8f5e9", "#1b5e20"),
    StageTone.FLAGGED: ("#fff4e0", "#8a5200"),
    StageTone.HELD: ("#fdecec", "#b71c1c"),
    StageTone.IDLE: ("#f1f3f5", "#5a6068"),
}
_WAITING = {DocStatus.NEEDS_REVIEW, DocStatus.ON_HOLD, DocStatus.MANUAL_ENTRY}
_READY = {DocStatus.APPROVED, DocStatus.AUTO_PASSED}


def _count(docs: Sequence[DocumentSummary], *statuses: DocStatus) -> int:
    return sum(doc.status in statuses for doc in docs)


def _read(docs: Sequence[DocumentSummary], in_progress: int) -> StageOutcome:
    manual = _count(docs, DocStatus.MANUAL_ENTRY)
    if manual:
        return StageOutcome("Read", StageTone.FLAGGED, f"{manual} for manual entry")
    reading = f", {in_progress} in progress" if in_progress else ""
    return StageOutcome("Read", StageTone.PASSED, f"{len(docs)} read{reading}")


def _extract(docs: Sequence[DocumentSummary]) -> StageOutcome:
    invalid = sum(doc.extraction_valid is False for doc in docs)
    if invalid:
        return StageOutcome("Extract", StageTone.FLAGGED, f"{invalid} invalid output")
    return StageOutcome("Extract", StageTone.PASSED, f"{len(docs)} extracted")


def _check(docs: Sequence[DocumentSummary]) -> StageOutcome:
    # A non-invoice (a statement, a résumé) is set aside, not a problem to fix.
    others = [doc for doc in docs if not is_invoice(doc)]
    invoices = [doc for doc in docs if is_invoice(doc)]
    held = sum(doc.highest_severity is Severity.HOLD for doc in invoices)
    flagged = sum(doc.highest_severity in {Severity.FLAG, Severity.MANUAL} for doc in invoices)
    parts = [f"{held} held"] * bool(held) + [f"{flagged} flagged"] * bool(flagged)
    if others:
        parts.append("1 not an invoice" if len(others) == 1 else f"{len(others)} not invoices")
    summary = ", ".join(parts) or "all clear"
    if held:
        return StageOutcome("Check", StageTone.HELD, summary)
    if flagged:
        return StageOutcome("Check", StageTone.FLAGGED, summary)
    return StageOutcome("Check", StageTone.PASSED, summary)


def _review(docs: Sequence[DocumentSummary]) -> StageOutcome:
    waiting = _count(docs, *_WAITING)
    if waiting:
        return StageOutcome("Review", StageTone.FLAGGED, f"{waiting} waiting")
    return StageOutcome("Review", StageTone.PASSED, "none waiting")


def _export(docs: Sequence[DocumentSummary]) -> StageOutcome:
    exported = _count(docs, DocStatus.EXPORTED)
    ready = _count(docs, *_READY)
    if exported:
        return StageOutcome("Export", StageTone.PASSED, f"{exported} exported, {ready} ready")
    return StageOutcome("Export", StageTone.IDLE, f"{ready} ready")


def _intake(counts: IntakeCounts) -> StageOutcome:
    """Discarded matches the Queue's Discarded list: the copies plus the non-invoices."""
    discarded = counts.discarded
    summary = f"{counts.received} received" + (f", {discarded} discarded" if discarded else "")
    return StageOutcome("Intake", StageTone.PASSED, summary)


def batch_outcomes(docs: Sequence[DocumentSummary], copies: int = 0) -> tuple[StageOutcome, ...]:
    """``copies``: byte-identical copies intake discarded, which were never stored."""
    if not docs:
        return tuple(StageOutcome(name, StageTone.IDLE, "no documents") for name in STAGES)
    # A document the model is still reading has been received, but has no outcome yet.
    done = [doc for doc in docs if not doc.is_processing]
    return (
        _intake(intake_counts(docs, copies)),
        _read(done, len(docs) - len(done)),
        _extract(done),
        _check(done),
        _review(done),
        _export(done),
    )


def _stage_html(outcome: StageOutcome, is_current: bool) -> str:
    background, color = _COLORS[outcome.tone]
    border = "3px solid #1565c0" if is_current else f"1px solid {color}55"
    marker = ' data-current="true"' if is_current else ""
    return (
        f'<div data-stage="{escape(outcome.name)}"{marker} style="flex:1;min-width:0;'
        f"background:{background};color:{color};border:{border};border-radius:8px;"
        f'padding:0.45rem 0.6rem;text-align:center;">'
        f'<div style="font-weight:700;">{escape(outcome.name)}</div>'
        f'<div style="font-size:0.8rem;">{escape(outcome.summary)}</div></div>'
    )


def flow_strip_html(outcomes: Sequence[StageOutcome], current: str | None = None) -> str:
    arrow = '<div style="align-self:center;color:#8a9099;">&#8250;</div>'
    stages = arrow.join(_stage_html(item, item.name == current) for item in outcomes)
    return f'<div style="display:flex;gap:0.35rem;margin:0.4rem 0 0.8rem;">{stages}</div>'


def render_flow_strip(
    docs: Sequence[DocumentSummary], current: str | None = None, *, copies: int = 0
) -> None:
    outcomes = batch_outcomes(docs, copies)
    st.markdown(flow_strip_html(outcomes, current), unsafe_allow_html=True)
