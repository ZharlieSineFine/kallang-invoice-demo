"""The random audit of auto-passed invoices on screen (CR-012).

Shared by the Review page (the label, why it is there, and the person's result) and Demo
Step 8 (the monitoring panel). A picked invoice stays AUTO_PASSED and exports as usual; the
audit only measures how often auto-pass is wrong.
"""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from app import ui
from app.backend import Backend
from app.models import AuditSummary, DocumentBundle
from app.notice import Act
from invoiceflow.evaluate.audit_monitor import counts_line, rate_line

AUDIT_LABEL = "Random audit sample"
MONITOR_TITLE = "Monitoring auto-passed invoices"

REVIEW_NOTE = (
    "This invoice passed every check and was auto-passed. It was also picked at random for "
    "a person to check against the page. The result counts toward the auto-pass error rate "
    "on Demo step 8; it does not hold up the invoice."
)
_RESULTS = {
    "passed": "Audit passed: every field matched the page.",
    "error": "Audit found an error. It counts toward the auto-pass error rate.",
}


def monitor_text(percent: Decimal | None) -> str:
    share = f"A random {percent:g}%" if percent is not None else "A random share"
    return (
        "Auto-passed invoices reach SAP without a person, so reviewer corrections cannot "
        f"measure their accuracy. {share} of them is picked for a person to check, field by "
        "field, against the page. The share with an error is the auto-pass error rate. If it "
        "rises, finance can lower the value limit or send a vendor back to review."
    )


def monitor_lines(summary: AuditSummary) -> tuple[str, str]:
    """The counts and the rate sentence, worded as in the weekly audit_monitor report."""
    return counts_line(summary), rate_line(summary)


def render_audit_monitor(summary: AuditSummary) -> None:
    st.subheader(MONITOR_TITLE)
    st.markdown(monitor_text(summary.percent))
    counts, rate = monitor_lines(summary)
    st.markdown(f"**{counts}**")
    st.caption(rate)


def _record(backend: Backend, bundle: DocumentBundle, reviewer: str, found_error: bool) -> None:
    fields = tuple(st.session_state.get("audit_fields") or ())
    if found_error and not fields:
        st.error("Choose the fields that were wrong, then record the error.")
        return
    doc_id = bundle.document.doc_id
    act = Act("Recorded the audit of", "record the audit of", doc=bundle.document, by=reviewer)
    ui.run_action(
        backend.record_audit, doc_id, reviewer, found_error, fields, act=act, at=f"audit:{doc_id}"
    )


def render_audit(backend: Backend, bundle: DocumentBundle, reviewer: str) -> None:
    """The label, why the invoice carries it, and the person's audit result."""
    doc = bundle.document
    if not doc.is_audit_sample:
        return
    st.markdown(f":violet-badge[{AUDIT_LABEL}]")
    st.caption(REVIEW_NOTE)
    if doc.audit_result in _RESULTS:
        show = st.success if doc.audit_result == "passed" else st.warning
        show(_RESULTS[doc.audit_result])
        return
    st.multiselect(
        "Fields that were wrong (only if you found an error)",
        [field.name for field in bundle.fields],
        key="audit_fields",
    )
    passed, error = st.columns(2)
    if passed.button("Audit passed: every field matches the page", key="audit_passed"):
        _record(backend, bundle, reviewer, found_error=False)
    if error.button("Audit found an error", key="audit_error"):
        _record(backend, bundle, reviewer, found_error=True)
    ui.show_result(f"audit:{doc.doc_id}")
