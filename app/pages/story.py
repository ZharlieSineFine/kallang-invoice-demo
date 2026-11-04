"""The guided demo: one screen, one question, and the real artifact as the answer.

Every number comes from the database or the evaluation report. The page only reads; the
correction in step 5 happens on the Review page so the audience sees the real screen.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from html import escape
from uuid import UUID

import pandas as pd
import streamlit as st

from app import ui
from app.backend import Backend
from app.boxes import BoxSpec, draw_boxes, page_boxes, word_boxes
from app.compliance import card_for, card_html
from app.csv_trace import render_csv_trace
from app.flow import render_flow_strip
from app.inbox import render_grid
from app.models import DocumentBundle, DocumentSummary
from invoiceflow.contracts import DocStatus

_STEP_KEY = "story_step"
_REVEAL_ORDER = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "subtotal",
    "gst_amount",
    "total",
)
_SCENARIOS = (
    ("R02", "The total does not add up"),
    ("R08", "The bank account changed"),
    ("R09", "Hidden instructions"),
)


@dataclass(frozen=True)
class Context:
    backend: Backend
    docs: tuple[DocumentSummary, ...]


@dataclass(frozen=True)
class Step:
    stage: str | None
    question: str
    render: Callable[[Context], str]


def _json(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _doc_with_rule(docs, rule_id: str) -> DocumentSummary | None:
    """The clearest example: the document with this finding and the fewest others."""
    matches = [doc for doc in docs if rule_id in doc.open_rules]
    return min(matches, key=lambda doc: len(doc.open_rules), default=None)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _current_bundle(ctx: Context) -> DocumentBundle | None:
    ids = [doc.doc_id for doc in ctx.docs]
    if st.session_state.get("selected_doc_id") not in ids:
        star = _doc_with_rule(ctx.docs, "R02") or ctx.docs[0]
        st.session_state["selected_doc_id"] = star.doc_id
    doc_id = ui.document_picker(ctx.docs, key="story_document", label="Invoice")
    return ctx.backend.document(doc_id) if doc_id is not None else None


def _page_view(bundle: DocumentBundle, key: str):
    numbers = [page.page_no for page in bundle.pages]
    if not numbers:
        return None, None
    page_no = st.selectbox("Page", numbers, key=key) if len(numbers) > 1 else numbers[0]
    return ui.page_words(bundle, page_no)


def _show_image(page, boxes: tuple[BoxSpec, ...], *, line_width: int = 3) -> None:
    image = ui.load_image(page.image_path) if page is not None else None
    if image is None:
        st.warning("No page image is stored for this document.")
        return
    st.image(draw_boxes(image, boxes, line_width=line_width), width="stretch")


def _extraction_payload(bundle: DocumentBundle) -> dict:
    ext = bundle.extraction
    if ext is None:
        return {"extraction": None}
    return {
        "model": ext.model,
        "model_digest": ext.model_digest,
        "prompt_version": ext.prompt_version,
        "schema_version": ext.schema_version,
        "mode": ext.mode.value,
        "valid": ext.valid,
        "prompt_tokens": ext.prompt_tokens,
        "completion_tokens": ext.completion_tokens,
        "latency_ms": ext.latency_ms,
        "raw_output": ext.raw_output,
    }


def _inbox(ctx: Context) -> str:
    render_grid(ctx.docs)
    return _inbox_sentence(ctx.docs)


def _inbox_sentence(docs) -> str:
    groups = (
        ("passed or approved", {DocStatus.AUTO_PASSED, DocStatus.APPROVED, DocStatus.EXPORTED}),
        ("need a person", {DocStatus.NEEDS_REVIEW, DocStatus.MANUAL_ENTRY}),
        ("on hold", {DocStatus.ON_HOLD}),
        ("not invoices", {DocStatus.NOT_INVOICE}),
        ("rejected", {DocStatus.REJECTED}),
    )
    counts = ((label, sum(doc.status in statuses for doc in docs)) for label, statuses in groups)
    parts = ", ".join(f"{count} {label}" for label, count in counts if count)
    return f"{_plural(len(docs), 'document')} arrived: {parts}."


def _read(ctx: Context) -> str:
    bundle = _current_bundle(ctx)
    if bundle is None:
        return "That document is no longer in the database."
    left, right = st.columns([3, 2])
    with left:
        page, words = _page_view(bundle, "story_read_page")
        _show_image(page, word_boxes(words) if words is not None else (), line_width=1)
    if words is None:
        return "The words for this page are not stored."
    hidden = sum(word.hidden for word in words.words)
    conf = words.ocr_mean_conf
    with right:
        st.metric("Words found", len(words.words))
        st.metric("How", "PDF text layer" if conf is None else "Text recognition")
        if conf is not None:
            st.metric("Mean recognition confidence", f"{conf:.0f}%")
        st.metric("Invisible to a person", hidden)
        if ui.technical_view():
            st.code(_json([word.model_dump() for word in words.words[:15]]), language="json")
    extra = f" {hidden} are invisible to a person and shown in red." if hidden else ""
    return f"The system found {len(words.words)} words on this page.{extra}"


def _reveal_order(bundle: DocumentBundle) -> list[str]:
    names = [field.name for field in bundle.fields]
    first = [name for name in _REVEAL_ORDER if name in names]
    return first + [name for name in names if name not in first]


def _reveal(key: str, count: int) -> None:
    st.session_state[key] = count


def _extract(ctx: Context) -> str:
    bundle = _current_bundle(ctx)
    if bundle is None:
        return "That document is no longer in the database."
    order = _reveal_order(bundle)
    key = f"story_revealed_{bundle.document.doc_id}"
    count = min(st.session_state.get(key, 1), len(order))
    shown = order[:count]
    left, right = st.columns([3, 2])
    with right:
        st.code(_json({name: bundle.field(name).value_raw for name in shown}), language="json")
        one, two = st.columns(2)
        one.button(
            "Show next field",
            key="story_reveal",
            disabled=count >= len(order),
            on_click=_reveal,
            args=(key, count + 1),
            width="stretch",
        )
        two.button(
            "Show all",
            key="story_reveal_all",
            disabled=count >= len(order),
            on_click=_reveal,
            args=(key, len(order)),
            width="stretch",
        )
        if ui.technical_view():
            st.code(_json(_extraction_payload(bundle)), language="json")
    with left:
        page, words = _page_view(bundle, "story_extract_page")
        current = shown[-1] if shown else None
        boxes = ()
        if words is not None:
            every = page_boxes(words, bundle.fields, (), bundle.findings, selected=current)
            boxes = tuple(box for box in every if box.field in shown)
        _show_image(page, boxes)
    return f"The model returned {len(order)} fields, copied as printed. Showing {count}."


def _understand(ctx: Context) -> str:
    bundle = _current_bundle(ctx)
    if bundle is None:
        return "That document is no longer in the database."
    left, right = st.columns([3, 2])
    with left:
        page, words = _page_view(bundle, "story_understand_page")
        boxes = (
            page_boxes(words, bundle.fields, bundle.line_items, bundle.findings) if words else ()
        )
        _show_image(page, boxes)
        st.caption("Green: found on the page. Amber: fuzzy match or low confidence. Red: flagged.")
    with right:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "field": field.name,
                        "printed": field.value_raw,
                        "standardized": field.value_norm,
                        "match": field.match_type.value,
                    }
                    for field in bundle.fields
                ]
            ),
            hide_index=True,
            width="stretch",
            height=560,
        )
    found = sum(field.bbox is not None for field in bundle.fields)
    return f"{found} of {len(bundle.fields)} values were located on the page."


def _scenario_doc(ctx: Context) -> DocumentSummary | None:
    loaded = [(rule, label) for rule, label in _SCENARIOS if _doc_with_rule(ctx.docs, rule)]
    missing = [rule for rule, _ in _SCENARIOS if not _doc_with_rule(ctx.docs, rule)]
    if missing:
        st.caption(f"Not in the loaded data: {', '.join(missing)}")
    if not loaded:
        return None
    labels = {rule: f"{rule}: {label}" for rule, label in loaded}
    rule = st.radio(
        "Scenario",
        list(labels),
        format_func=labels.get,
        horizontal=True,
        key="story_scenario",
    )
    doc = _doc_with_rule(ctx.docs, rule)
    st.session_state["selected_doc_id"] = doc.doc_id
    return doc


def _check_cards(bundle: DocumentBundle) -> None:
    if not bundle.findings:
        st.success("No open findings on this invoice.")
    for finding in bundle.findings:
        st.markdown(ui.finding_card_html(finding), unsafe_allow_html=True)
    for rule_id in dict.fromkeys(finding.rule_id for finding in bundle.findings):
        card = card_for(rule_id)
        if card is not None:
            st.markdown(card_html(card), unsafe_allow_html=True)
    if ui.technical_view():
        st.code(_json([asdict(finding) for finding in bundle.findings]), language="json")


def _check(ctx: Context) -> str:
    doc = _scenario_doc(ctx)
    bundle = ctx.backend.document(doc.doc_id) if doc is not None else _current_bundle(ctx)
    if bundle is None:
        return "That document is no longer in the database."
    left, right = st.columns([3, 2])
    with left:
        page, words = _page_view(bundle, "story_check_page")
        boxes = ()
        if words is not None:
            fields = page_boxes(words, bundle.fields, bundle.line_items, bundle.findings)
            flagged = tuple(box for box in fields if box.status == "flagged")
            boxes = flagged + word_boxes(words, hidden_only=True)
        _show_image(page, boxes)
    with right:
        _check_cards(bundle)
    count = len(bundle.findings)
    noun = "finding" if count == 1 else "findings"
    return f"{count} open {noun} on this invoice. Red boxes mark the evidence."


def _open_review(doc_id: UUID) -> None:
    st.session_state["selected_doc_id"] = doc_id
    st.session_state["page"] = "Review"


def _review(ctx: Context) -> str:
    bundle = _current_bundle(ctx)
    if bundle is None:
        return "That document is no longer in the database."
    doc = bundle.document
    st.button(
        "Open in Review",
        key="story_open_review",
        type="primary",
        on_click=_open_review,
        args=(doc.doc_id,),
    )
    st.caption("Correct or approve on the Review page, then come back to Demo for the record.")
    trace = ctx.backend.trace(doc.doc_id)
    open_rules = {finding.rule_id for finding in bundle.findings}
    history = trace.finding_history if trace is not None else ()
    cleared = sorted({finding.rule_id for finding in history} - open_rules)
    cols = st.columns(3)
    cols[0].metric("Status", doc.status.value)
    cols[1].metric("Open findings", len(bundle.findings))
    cols[2].metric("Cleared findings", len(cleared))
    if bundle.reviews:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "when": review.created_at.isoformat(timespec="seconds"),
                        "reviewer": review.reviewer,
                        "action": review.action.value,
                        "field": review.field or "—",
                        "old": review.old_value or "—",
                        "new": review.new_value or "—",
                    }
                    for review in bundle.reviews
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No reviewer has acted on this invoice yet.")
    if ui.technical_view() and trace is not None:
        st.code(_json([asdict(item) for item in history]), language="json")
    who = f"{len(bundle.reviews)} recorded action{'' if len(bundle.reviews) == 1 else 's'}"
    return f"Nothing moves on without a person: this invoice has {who}."


def _export(ctx: Context) -> str:
    batches = ctx.backend.batches()
    filled = next((batch for batch in batches if batch.row_count > 0), None)
    if filled is None:
        st.info("No export batch yet. Approve an invoice and run the export.")
        return "Nothing has been exported yet."
    st.markdown(":violet-badge[Hypothetical SAP layout]")
    render_csv_trace(
        ctx.backend,
        filled,
        key="story_csv",
        preferred_doc=st.session_state.get("selected_doc_id"),
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "batch": batch.batch_id,
                    "created": batch.created_at.isoformat(timespec="seconds"),
                    "rows": batch.row_count,
                    "total": float(batch.total),
                }
                for batch in batches
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    empty = sum(batch.row_count == 0 for batch in batches)
    note = f" {_plural(empty, 'other run')} found nothing new to export." if empty else ""
    rows = _plural(filled.row_count, "row")
    return f"Batch {filled.batch_id} holds {rows}, and each invoice exports once.{note}"


def _percent(value) -> str | None:
    return None if value is None else f"{value:.1f}%"


def _accuracy(ctx: Context) -> str:
    data = ctx.backend.dashboard()
    evaluation = data.latest_evaluation
    if evaluation is None:
        st.info("No evaluation report yet.")
        return "Accuracy has not been measured yet."
    if evaluation.synthetic:
        st.markdown(":violet-badge[SYNTHETIC EVALUATION]")
    raw = evaluation.raw
    samples = raw.get("samples", evaluation.document_count)
    checks = raw.get("checks") or {}
    coding = raw.get("coding") or {}
    values = (
        ("Documents measured", samples),
        ("Accuracy", _percent(raw.get("accuracy"))),
        ("Check precision", _percent(checks.get("precision"))),
        ("Check recall", _percent(checks.get("recall"))),
        ("Coding accuracy", _percent(coding.get("overall"))),
    )
    cols = st.columns(len(values))
    for col, (label, value) in zip(cols, values, strict=True):
        col.metric(label, "n/a" if value is None else value)
    if data.corrections_by_field:
        st.dataframe(
            pd.DataFrame(
                [{"field": row.key, "corrections": row.count} for row in data.corrections_by_field]
            ),
            hide_index=True,
            width="stretch",
        )
    if ui.technical_view():
        st.code(_json(raw), language="json")
    label = "synthetic" if evaluation.synthetic else "real"
    return f"Measured on {samples} {label} documents, set “{evaluation.set_name}”."


STEPS = (
    Step("Intake", "What arrived?", _inbox),
    Step("Read", "Can the system even read these?", _read),
    Step("Extract", "What did the AI copy?", _extract),
    Step("Extract", "How does the system turn printing into numbers?", _understand),
    Step("Check", "What did the system catch?", _check),
    Step("Review", "Who is in control?", _review),
    Step("Export", "What does SAP receive?", _export),
    Step(None, "How good is it, honestly?", _accuracy),
)


def _go_to(index: int) -> None:
    st.session_state[_STEP_KEY] = index


def _navigation(index: int) -> None:
    back, position, forward = st.columns([1, 6, 1])
    back.button(
        "Back",
        key="story_back",
        disabled=index == 0,
        on_click=_go_to,
        args=(index - 1,),
        width="stretch",
    )
    position.progress((index + 1) / len(STEPS), text=f"Step {index + 1} of {len(STEPS)}")
    forward.button(
        "Next",
        key="story_next",
        type="primary",
        disabled=index == len(STEPS) - 1,
        on_click=_go_to,
        args=(index + 1,),
        width="stretch",
    )


def _stage_card(question: str, outcome: str) -> str:
    return (
        '<div style="background:#f4f6fb;border-radius:8px;padding:0.7rem 1rem;'
        'margin-bottom:0.8rem;color:#1f2328;">'
        f'<div style="font-size:1.25rem;font-weight:700;color:#1f2328;">{escape(question)}</div>'
        f'<div style="color:#3c4148;">{escape(outcome)}</div></div>'
    )


def render(backend: Backend | None = None) -> None:
    backend = backend or ui.get_backend()
    st.title("Demo")
    docs = backend.list_documents()
    if not docs:
        st.info("No documents yet. Load the demo data, or upload an invoice.")
        return
    index = min(st.session_state.get(_STEP_KEY, 0), len(STEPS) - 1)
    step = STEPS[index]
    render_flow_strip(docs, step.stage)
    _navigation(index)
    heading = st.empty()
    outcome = step.render(Context(backend=backend, docs=docs))
    heading.markdown(_stage_card(step.question, outcome), unsafe_allow_html=True)
