"""Dashboard: throughput, quality, corrections, holds, and the latest evaluation."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app import ui
from app.backend import Backend
from app.flow import render_flow_strip


def _findings_frame(data) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"check": row.rule_id, "severity": row.severity.value, "findings": row.count}
            for row in data.findings_by_check
        ]
    )


def _counts_frame(rows) -> pd.DataFrame:
    return pd.DataFrame([{"name": row.key, "count": row.count} for row in rows])


def render(backend: Backend | None = None) -> None:
    backend = backend or ui.get_backend()
    st.title("Dashboard")
    ui.show_flash()
    data = backend.dashboard()
    render_flow_strip(backend.list_documents())

    cols = st.columns(4)
    cols[0].metric("Documents processed", data.total_documents)
    cols[1].metric("Auto-pass rate", f"{data.auto_pass_rate:.1f}%")
    cols[2].metric("Holds", data.hold_count)
    cols[3].metric(
        "Seconds per invoice",
        "n/a" if data.avg_seconds_per_invoice is None else f"{data.avg_seconds_per_invoice:.2f}",
    )

    second = st.columns(3)
    second[0].metric("Needs review", data.needs_review)
    second[1].metric("Approved", data.approved)
    second[2].metric("Total value", f"S${data.total_value:,.2f}")

    st.markdown("### Findings by check")
    findings = _findings_frame(data)
    if findings.empty:
        st.success("No open findings across the latest runs.")
    else:
        st.dataframe(findings, hide_index=True, width="stretch")
        if not findings.empty:
            st.bar_chart(findings.set_index("check")["findings"])

    left, right = st.columns(2)
    with left:
        st.markdown("### Corrections by field")
        fields = _counts_frame(data.corrections_by_field)
        if fields.empty:
            st.caption("No field corrections yet.")
        else:
            st.dataframe(fields, hide_index=True, width="stretch")
    with right:
        st.markdown("### Corrections by vendor")
        vendors = _counts_frame(data.corrections_by_vendor)
        if vendors.empty:
            st.caption("No vendor corrections yet.")
        else:
            st.dataframe(vendors, hide_index=True, width="stretch")

    st.markdown("### Holds and status")
    st.dataframe(
        pd.DataFrame(
            [
                {"status": "AUTO_PASSED", "documents": data.auto_passed},
                {"status": "NEEDS_REVIEW", "documents": data.needs_review},
                {"status": "ON_HOLD", "documents": data.on_hold},
                {"status": "APPROVED", "documents": data.approved},
                {"status": "REJECTED", "documents": data.rejected},
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    st.markdown("### Latest evaluation")
    evaluation = data.latest_evaluation
    if evaluation is None:
        st.info("No evaluation report yet. Run `make eval` (WS8); the demo runs on synthetic data.")
        return
    if evaluation.synthetic:
        st.markdown(":violet-badge[SYNTHETIC EVALUATION]")
    generated = evaluation.generated_at or "no timestamp"
    st.caption(f"`{evaluation.path}` · set `{evaluation.set_name}` · {generated}")
    metric_cols = st.columns(min(4, max(1, len(evaluation.metrics))))
    for index, (name, value) in enumerate(evaluation.metrics.items()):
        metric_cols[index % len(metric_cols)].metric(name, f"{value:.3f}")
    with st.expander("Raw evaluation payload"):
        st.code(json.dumps(evaluation.raw, indent=2, sort_keys=True), language="json")
