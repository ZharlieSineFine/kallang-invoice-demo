"""Review page: findings that lead to their field, the fix panel, and the invoice decision.

A finding card's "Fix this field" button selects its field, so the image shows its box and
the panel below offers the two ways to deal with it, each explained in a line:

- Save correction: the system misread the value; store the reviewer's value and rerun checks.
- Correct as printed: the value is right; clear the flag (never a hold) and record who did it.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from uuid import UUID

import streamlit as st

from app import ui
from app.backend import Backend, subtotal_hint
from app.fields import line_field, printed_value, with_line_value
from app.formatting import format_money
from app.hidden_text import render_hidden_text
from app.models import DocumentBundle, FindingRow
from app.notice import Act, failed_notice
from invoiceflow.contracts import DocStatus, Severity

FIELD_KEY = "review_field"
_NEEDS_ACTION = (Severity.MANUAL, Severity.HOLD, Severity.FLAG)
_VALUE = (
    "font-family:monospace;font-size:1.05rem;background:#f6f8fa;color:#1f2328;"
    "border:1px solid #d0d7de;border-radius:4px;padding:0.1rem 0.4rem;"
)


def default_field(bundle: DocumentBundle, options: Sequence[str]) -> str | None:
    """The field the page opens on: the first one a finding asks a person to look at."""
    for severity in _NEEDS_ACTION:
        for finding in bundle.findings:
            if finding.severity is severity and finding.field in options:
                return finding.field
    return options[0] if options else None


def _select(field: str) -> None:
    """Runs before widgets are built, so the field picker follows on this rerun."""
    st.session_state[FIELD_KEY] = field


def render_findings(bundle: DocumentBundle, options: Sequence[str], selected: str | None) -> None:
    st.subheader("Open findings")
    if not bundle.findings:
        doc = bundle.document
        if doc.status is DocStatus.NEEDS_REVIEW and doc.status_reason:
            st.info(doc.status_reason)  # e.g. the auto-pass value limit (CR-012)
        else:
            st.success("No open findings.")
        return
    for index, finding in enumerate(bundle.findings):
        st.markdown(ui.finding_card_html(finding), unsafe_allow_html=True)
        render_hidden_text(bundle, finding)
        if finding.field in options:
            current = finding.field == selected
            st.button(
                "Fixing this field ↓" if current else "Fix this field",
                key=f"fix_{index}",
                on_click=_select,
                args=(finding.field,),
                disabled=current,
            )
        elif finding.field is None:
            st.caption("This applies to the whole invoice: decide below.")
        elif finding.field.startswith("coding_lines"):
            st.caption("Fix this in the Coding table further down the page.")
        else:
            st.caption(
                "This value comes from the vendor master, not the invoice: check the vendor "
                "record, then decide below."
            )


def _save_correction(
    backend: Backend,
    bundle: DocumentBundle,
    field: str,
    change: tuple[str, str],
    reviewer: str,
) -> None:
    doc_id = bundle.document.doc_id
    at = fix_place(doc_id)
    before, value = change
    act = Act(
        f"Corrected {field} on",
        f"save the correction to {field} on",
        doc=bundle.document,
        by=reviewer,
        change=f"{field}: {before or '—'} → {value}.",
    )
    line = line_field(field)
    if line is None:
        ui.run_action(backend.correct, doc_id, field, value, reviewer, act=act, at=at)
        return
    try:
        items = with_line_value(bundle.line_items, line, value)
    except ValueError as exc:
        ui.flash(failed_notice(act, exc), at=at)
        st.rerun()
        return
    ui.run_action(backend.edit_line_items, doc_id, items, reviewer, act=act, at=at)


_APPROVED_NEXT = "It goes into the next SAP export for payment."
_REJECTED_NEXT = "The invoice is closed: it is never exported or paid."


def fix_place(doc_id: UUID) -> str:
    """Where the fix panel's results show: under Save correction and Correct as printed."""
    return f"fix:{doc_id}"


def _rules(findings: Sequence[FindingRow]) -> str:
    return ", ".join(dict.fromkeys(finding.rule_id for finding in findings))


def render_fix_panel(
    backend: Backend, bundle: DocumentBundle, field: str | None, reviewer: str
) -> None:
    if field is None:
        return
    try:
        printed = printed_value(bundle, field)
    except ValueError:
        return
    on_field = [finding for finding in bundle.findings if finding.field == field]
    flags = [finding for finding in on_field if finding.severity is Severity.FLAG]
    holds = [finding for finding in on_field if finding.severity is Severity.HOLD]

    st.subheader(f"Fixing: {field}")
    if flags:
        st.caption(f"Flagged by {_rules(flags)}.")
    elif not holds:
        st.caption("No open flag on this field. You can still correct it or mark it checked.")
    if holds:
        st.warning(
            f"This field is part of a hold ({_rules(holds)}). Correcting or accepting the value "
            "does not release the hold: use Release the hold below, with a reason."
        )
    st.markdown(
        f'Read on the invoice: <span style="{_VALUE}">{escape(printed) or "—"}</span>',
        unsafe_allow_html=True,
    )
    value = st.text_input(
        "Correct value", value=printed, key=f"fix_value_{bundle.document.doc_id}_{field}"
    )
    if field == "subtotal":
        hint = subtotal_hint(bundle)
        if hint is not None:
            st.caption(f"Line items add up to {format_money(hint)}.")

    save, save_note = st.columns([1, 2])
    if save.button("Save correction", key="btn_correct", type="primary", width="stretch"):
        _save_correction(backend, bundle, field, (printed, value), reviewer)
    save_note.caption("The system misread it. Use my value and rerun the checks.")

    accept, accept_note = st.columns([1, 2])
    if accept.button("Correct as printed", key="btn_confirm", width="stretch"):
        ui.run_action(
            backend.confirm,
            bundle.document.doc_id,
            field,
            reviewer,
            act=Act(
                f"Accepted {field} as printed on",
                f"accept {field} as printed on",
                doc=bundle.document,
                by=reviewer,
            ),
            at=fix_place(bundle.document.doc_id),
        )
    accept_note.caption(
        "I checked the invoice image and this value is right; this clears the flag. "
        "Your name is recorded."
        if flags
        else "I checked the invoice image and this value is right. Your name is recorded."
    )
    ui.show_result(fix_place(bundle.document.doc_id))


def render_decision(backend: Backend, bundle: DocumentBundle, reviewer: str) -> None:
    doc_id: UUID = bundle.document.doc_id
    st.subheader("Decision on the whole invoice")
    approve, reject = st.columns(2)
    comment = st.session_state.get("approve_comment")
    at = f"decision:{doc_id}"
    doc = bundle.document
    if approve.button("Approve", key="btn_approve", type="primary", width="stretch"):
        act = Act("Approved", "approve", doc=doc, by=reviewer, next_step=_APPROVED_NEXT)
        ui.run_action(backend.approve, doc_id, reviewer, comment, act=act, at=at)
    approve.caption("Pay it: the invoice goes into the next SAP export.")
    if reject.button("Reject", key="btn_reject", width="stretch"):
        act = Act("Rejected", "reject", doc=doc, by=reviewer, next_step=_REJECTED_NEXT)
        ui.run_action(backend.reject, doc_id, reviewer, comment, act=act, at=at)
    reject.caption("Don't pay it: the invoice is closed and never exported.")
    ui.show_result(at)
    st.text_area(
        "Comment (optional, saved with Approve or Reject)",
        key="approve_comment",
        placeholder="e.g. Checked against the purchase order.",
    )

    if bundle.document.status is not DocStatus.ON_HOLD:
        return
    st.markdown("**Release the hold**")
    st.caption(
        "Only after you have dealt with the reason for the hold, such as calling the vendor "
        "to confirm a bank account. Then approve or reject."
    )
    comment = st.text_area(
        "Reason for releasing (required)",
        key="hold_comment",
        placeholder="Why can this hold be released?",
    )
    if st.button("Release hold", key="btn_release"):
        act = Act("Released the hold on", "release the hold on", doc=doc, by=reviewer)
        ui.run_action(
            backend.release_hold, doc_id, reviewer, comment, act=act, at=f"release:{doc_id}"
        )
    ui.show_result(f"release:{doc_id}")
