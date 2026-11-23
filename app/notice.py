"""What the confirmation after an action says (user's request, 2026-11-20).

Reject used to say only "Rejected". A notice now names what was done and to which invoice,
with its vendor and total, says what happens next, and records who did it and when.

The color says whether the action worked, not whether the news is good (the user's choice):
green when it worked, even for a reject; amber when it worked but more is needed, such as a
correction that leaves a check open; red only when it was not done. The invoice's new
status is shown as a tag. ``app.notice_view`` draws it as a card and a pop-up.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.formatting import format_money, format_time
from app.models import DeleteOutcome, DocumentSummary, ReviewOutcome
from invoiceflow.contracts import DocStatus, Severity

_WAITING = frozenset({DocStatus.NEEDS_REVIEW, DocStatus.ON_HOLD, DocStatus.MANUAL_ENTRY})
_DELETED_NOTE = (
    "Its stored file and recorded model answer are gone too. The history keeps a record "
    "of the delete."
)


class Tone(StrEnum):
    SUCCESS = "success"  # it worked
    WARNING = "warning"  # it worked, but more is needed
    ERROR = "error"  # it was not done
    INFO = "info"  # nothing changed


@dataclass(frozen=True)
class Notice:
    tone: Tone
    headline: str  # "Rejected VTR-2026-9604"
    subject: str = ""  # "VenueTech Rigging Pte. Ltd. · S$1,057.30"
    detail: str = ""  # what happens next, or what the checks found
    status: DocStatus | None = None  # the invoice's new status, shown as a tag
    recorded: str = ""  # "Recorded under demo.reviewer at 2026-11-20 11:58:03 SGT."


@dataclass(frozen=True)
class Act:
    """How a button's action is described, success or failure."""

    done: str  # "Rejected": the headline reads "Rejected VTR-2026-9604"
    tried: str  # "reject": a failure reads "Could not reject VTR-2026-9604"
    doc: DocumentSummary | None = None  # the invoice it was done to
    by: str | None = None  # the reviewer, as recorded
    next_step: str = ""  # used when the backend's result adds nothing, as for Approve
    change: str = ""  # what was changed, e.g. "subtotal: 1,180.00 → 1,080.00."
    describe: Callable[[Any], Notice] | None = None  # for a result that is not one invoice's


def doc_label(doc: DocumentSummary) -> str:
    return doc.invoice_number or doc.file_name or "this document"


def subject_line(doc: DocumentSummary | None) -> str:
    if doc is None:
        return ""
    vendor = doc.vendor_name or doc.supplier_name
    total = format_money(doc.total) if doc.total is not None else None
    return " · ".join(part for part in (vendor, total) if part)


def recorded_line(by: str | None) -> str:
    return f"Recorded under {by} at {format_time(datetime.now(UTC))}." if by else ""


def _target(text: str, doc: DocumentSummary | None) -> str:
    return f"{text} {doc_label(doc)}" if doc is not None else text


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else f"{text}."


def done_notice(act: Act, outcome: Any) -> Notice:
    if act.describe is not None:
        return act.describe(outcome)
    status = getattr(outcome, "status", None)
    subject = subject_line(act.doc)
    if getattr(outcome, "changed", True) is False:
        message = getattr(outcome, "message", "")
        return Notice(Tone.INFO, _target("Nothing changed on", act.doc), subject, message, status)
    return Notice(
        tone=Tone.WARNING if _more_needed(outcome) else Tone.SUCCESS,
        headline=_target(act.done, act.doc),
        subject=subject,
        detail=" ".join(part for part in (act.change, _detail(act, outcome)) if part),
        status=status,
        recorded=recorded_line(act.by),
    )


def _more_needed(outcome: Any) -> bool:
    """Still waiting for a person with a check open. A rejected invoice keeps its findings,
    but nothing more is needed, so it stays green."""
    if getattr(outcome, "warn", False):
        return True
    findings = getattr(outcome, "findings", ())
    still_open = [f for f in findings if getattr(f, "severity", None) is not Severity.INFO]
    return getattr(outcome, "status", None) in _WAITING and bool(still_open)


def _detail(act: Act, outcome: Any) -> str:
    if act.next_step:
        return act.next_step
    if isinstance(outcome, ReviewOutcome):
        return outcome.checks
    if isinstance(outcome, str):
        return outcome
    return getattr(outcome, "message", "")


def failed_notice(act: Act, exc: Exception) -> Notice:
    return Notice(
        Tone.ERROR,
        _target(f"Could not {act.tried}", act.doc),
        subject_line(act.doc),
        _sentence(str(exc)),
    )


def export_notice(outcome: Any) -> Notice:
    """One run of the SAP export: an ``app.backend.ExportOutcome``."""
    if outcome.invoices == 0:
        return Notice(Tone.INFO, "Nothing new to export", detail=outcome.message)
    noun = "invoice" if outcome.invoices == 1 else "invoices"
    held = "; ".join(outcome.problems)
    resent = getattr(outcome, "resent_note", "")
    detail = " ".join(part for part in (resent, f"Held back: {held}." if held else "") if part)
    return Notice(
        tone=Tone.WARNING if held else Tone.SUCCESS,
        headline=f"Exported {outcome.invoices} {noun} to SAP",
        subject=f"Batch {outcome.batch_id} · {outcome.row_count} CSV rows",
        detail=detail or "Every send is kept in the batch history.",
    )


def delete_notice(
    outcome: DeleteOutcome, docs: Sequence[DocumentSummary], *, by: str | None
) -> Notice:
    if len(outcome.deleted) == 1:
        headline = f"Deleted {outcome.deleted[0]}"
        subject = subject_line(docs[0]) if len(docs) == 1 else ""
    else:
        headline = f"Deleted {len(outcome.deleted)} documents"
        subject = ", ".join(outcome.deleted)
    return Notice(
        tone=Tone.WARNING if outcome.warn else Tone.SUCCESS,
        headline=headline,
        subject=subject,
        detail=outcome.sap_note or _DELETED_NOTE,
        recorded=recorded_line(by),
    )
