"""Trace: one document's extraction, checks, reviews, and events."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app import ui
from app.backend import Backend


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def render(backend: Backend | None = None) -> None:
    backend = backend or ui.get_backend()
    st.title("Trace")
    ui.show_flash()
    docs = backend.list_documents()
    if not docs:
        st.info("No documents to trace.")
        return
    doc_id = ui.document_picker(docs, key="trace_document")
    if doc_id is None:
        return
    trace = backend.trace(doc_id)
    if trace is None:
        st.error("That document disappeared.")
        return
    bundle = trace.bundle
    doc = bundle.document
    st.subheader(f"{doc.invoice_number or 'no invoice number'} · {doc.status.value}")

    cols = st.columns(4)
    cols[0].metric("Findings", len(bundle.findings))
    cols[1].metric("Runs", len(trace.runs))
    cols[2].metric("Reviews", len(bundle.reviews))
    cols[3].metric("Events", len(bundle.events))

    if bundle.extraction:
        ext = bundle.extraction
        st.markdown("### Extraction")
        st.dataframe(
            _frame(
                [
                    {
                        "model": ext.model,
                        "mode": ext.mode.value,
                        "valid": ext.valid,
                        "schema": ext.schema_version,
                        "prompt": ext.prompt_version,
                        "latency_ms": ext.latency_ms,
                        "created_at": ext.created_at.isoformat(timespec="seconds"),
                    }
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        if ext.replay:
            st.markdown(":violet-badge[Replayed response]")

    st.markdown("### Runs")
    st.write(", ".join(f"`{run}`" for run in trace.runs) or "No runs recorded.")

    st.markdown("### Findings (all runs)")
    if trace.finding_history:
        st.dataframe(
            _frame(
                [
                    {
                        "run": finding.run_id or "—",
                        "rule": finding.rule_id,
                        "severity": finding.severity.value,
                        "field": finding.field or "—",
                        "message": finding.message,
                    }
                    for finding in trace.finding_history
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No findings were ever recorded for this document.")

    st.markdown("### Review actions")
    if bundle.reviews:
        st.dataframe(
            _frame(
                [
                    {
                        "when": review.created_at.isoformat(timespec="seconds"),
                        "reviewer": review.reviewer,
                        "action": review.action.value,
                        "field": review.field or "—",
                        "old": review.old_value or "—",
                        "new": review.new_value or "—",
                        "comment": review.comment or "—",
                    }
                    for review in bundle.reviews
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No reviewer actions yet.")

    st.markdown("### Events")
    if bundle.events:
        st.dataframe(
            _frame(
                [
                    {
                        "when": event.ts.isoformat(timespec="seconds"),
                        "actor": event.actor,
                        "type": event.type,
                        "payload": json.dumps(event.payload, sort_keys=True),
                    }
                    for event in bundle.events
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No events for this document.")
