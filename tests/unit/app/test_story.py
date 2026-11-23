"""AppTest coverage for the guided Demo page, the inbox grid, and the technical view."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from test_pages import _run, _run_main

from app.boxes import load_page_text, word_boxes
from app.inbox import inbox_card, load_type_labels
from app.models import BatchSummary, FindingRow
from app.pages import dashboard, queue, story, trace
from invoiceflow.contracts import DocStatus, DocType, Scope, Severity


def _with_batch(backend, tmp_path):
    doc = next(bundle.document for bundle in backend.bundles.values() if not bundle.findings)
    path = tmp_path / "B-001.csv"
    path.write_text(
        "InvoiceID,CompanyCode,VendorNo,GrossAmount,LineNo,GLAccount,NetAmount,LineText\n"
        "1,KG01,100014,1177.20,1,610200,1080.00,Equipment rental\n",
        encoding="utf-8",
    )
    batch = BatchSummary(
        batch_id="B-001",
        created_at=datetime(2026, 11, 4, 1, 0, tzinfo=UTC),
        csv_path=str(path),
        row_count=1,
        total=Decimal("1177.20"),
        layout="hypothetical",
        mapping_version="1",
        doc_ids=(doc.doc_id,),
        csv_sha256="a" * 64,
        manifest={
            "model": "gemma4:12b",
            "invoices": [{"invoice_id": 1, "doc_id": str(doc.doc_id)}],
        },
    )
    empty = replace(batch, batch_id="B-002", row_count=0, total=Decimal("0"), doc_ids=())
    backend.batches = lambda: (empty, batch)
    return backend


def _text(at) -> str:
    parts = [item.value for group in (at.markdown, at.caption, at.subheader) for item in group]
    return "\n".join(parts)


def _advance(at, times: int = 1):
    for _ in range(times):
        at.button(key="story_next").click()
        at.run(timeout=30)
        assert not at.exception, [str(exc) for exc in at.exception]
    return at


def test_demo_opens_on_the_inbox_with_the_flow_strip(fake_backend):
    at = _run(story, fake_backend)
    assert [title.value for title in at.title] == ["Demo"]
    text = _text(at)
    assert "What arrived?" in text
    assert 'data-stage="Intake" data-current="true"' in text
    assert at.button(key="story_back").disabled
    assert not at.button(key="story_next").disabled


@pytest.mark.parametrize(
    ("steps", "question", "stage"),
    [
        (1, "Can the system even read these?", "Read"),
        (2, "What did the AI copy?", "Extract"),
        (3, "How does the system turn printing into numbers?", "Extract"),
        (4, "What did the system catch?", "Check"),
        (5, "Who is in control?", "Review"),
        (6, "What does SAP receive?", "Export"),
    ],
)
def test_each_step_answers_one_question(fake_backend, tmp_path, steps, question, stage):
    at = _run(story, _with_batch(fake_backend, tmp_path))
    _advance(at, steps)
    text = _text(at)
    assert question in text
    assert f'data-stage="{stage}" data-current="true"' in text


def test_last_step_is_accuracy_labeled_synthetic(fake_backend, evaluation, tmp_path):
    fake_backend.evaluation = evaluation
    at = _run(story, _with_batch(fake_backend, tmp_path))
    _advance(at, 7)
    text = _text(at)
    assert "How good is it, honestly?" in text
    assert "SYNTHETIC" in text
    assert at.button(key="story_next").disabled


def test_back_returns_to_the_previous_step(fake_backend):
    at = _run(story, fake_backend)
    _advance(at, 2)
    at.button(key="story_back").click()
    at.run(timeout=30)
    assert "Can the system even read these?" in _text(at)


def test_story_starts_on_the_invoice_with_the_r02_finding(fake_backend, mismatch_bundle):
    at = _run(story, fake_backend)
    _advance(at, 1)
    assert at.session_state["selected_doc_id"] == mismatch_bundle.document.doc_id


def test_extract_step_reveals_one_field_at_a_time(fake_backend):
    at = _run(story, fake_backend)
    _advance(at, 2)
    assert "invoice_number" in at.code[0].value
    before = at.code[0].value.count("\n")
    at.button(key="story_reveal").click()
    at.run(timeout=30)
    assert at.code[0].value.count("\n") > before


def test_check_step_shows_finding_evidence_and_compliance(fake_backend):
    at = _run(story, fake_backend)
    _advance(at, 4)
    text = _text(at)
    assert "R02" in text
    # Evidence keys render with human labels ("lines sum", not "lines_sum").
    assert "lines sum" in text
    assert "IRAS" in text


def test_check_step_says_which_scenarios_are_not_loaded(fake_backend):
    at = _run(story, fake_backend)
    _advance(at, 4)
    assert "Not in the loaded data: R08, R09" in _text(at)


def test_hold_scenarios_appear_when_loaded(on_hold_backend):
    bundle = next(iter(on_hold_backend.bundles.values()))
    on_hold_backend.bundles[bundle.document.doc_id] = replace(
        bundle, document=replace(bundle.document, open_rules=("R08",))
    )
    at = _run(story, on_hold_backend)
    _advance(at, 4)
    assert "Singapore Police Force" in _text(at)


def test_review_step_sends_the_reviewer_to_the_review_page(fake_backend):
    at = _run_main(fake_backend)
    assert at.sidebar.radio(key="page").value == "Demo"
    _advance(at, 5)
    at.button(key="story_open_review").click()
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["page"] == "Review"


def test_review_step_lists_a_correction_and_the_cleared_finding(fake_backend, mismatch_bundle):
    fake_backend.correct(mismatch_bundle.document.doc_id, "subtotal", "1,080.00", "demo.reviewer")
    at = _run(story, fake_backend)
    at.session_state["selected_doc_id"] = mismatch_bundle.document.doc_id
    _advance(at, 5)
    assert any("subtotal" in frame.value.to_string() for frame in at.dataframe)


def test_export_step_traces_a_row_and_shows_the_empty_second_batch(fake_backend, tmp_path):
    at = _run(story, _with_batch(fake_backend, tmp_path))
    _advance(at, 6)
    frames = "\n".join(frame.value.to_string() for frame in at.dataframe)
    assert "610200" in frames
    assert "B-002" in frames
    assert "hypothetical" in _text(at).lower()
    at.selectbox(key="story_csv_column").set_value("LineText")
    at.run(timeout=30)
    assert not at.exception


def test_export_step_explains_when_nothing_was_exported(fake_backend):
    fake_backend.batches = lambda: ()
    at = _run(story, fake_backend)
    _advance(at, 6)
    assert any("No export batch" in item.value for item in at.info)


def test_missing_csv_file_is_a_warning_not_a_crash(fake_backend, tmp_path):
    backend = _with_batch(fake_backend, tmp_path)
    batch = backend.batches()[1]
    backend.batches = lambda: (replace(batch, csv_path=str(tmp_path / "gone.csv")),)
    at = _run(story, backend)
    _advance(at, 6)
    assert at.warning


def test_no_documents_is_explained(fake_backend):
    fake_backend.bundles.clear()
    at = _run(story, fake_backend)
    assert at.info


def test_technical_view_reveals_raw_artifacts(fake_backend):
    plain = _run(story, fake_backend)
    _advance(plain, 2)
    assert not any("gemma" in code.value.lower() for code in plain.code[1:])

    at = _run(story, fake_backend)
    at.session_state["technical_view"] = True
    at.run(timeout=30)
    _advance(at, 2)
    technical = "\n".join(code.value for code in at.code)
    assert "prompt_version" in technical
    assert "model_digest" in technical


def test_technical_toggle_lives_in_the_sidebar(fake_backend):
    at = _run_main(fake_backend)
    assert at.sidebar.toggle(key="technical_view").value is False


def test_queue_shows_the_strip_and_a_card_per_document(fake_backend):
    at = _run(queue, fake_backend)
    assert 'data-stage="Check"' in _text(at)
    keys = [button.key for button in at.button]
    for doc_id in fake_backend.bundles:
        assert f"inbox_open_{doc_id}" in keys


def test_inbox_card_click_opens_review(fake_backend, mismatch_bundle):
    at = _run_main(fake_backend)
    at.sidebar.radio(key="page").set_value("Queue").run(timeout=30)
    at.button(key=f"inbox_open_{mismatch_bundle.document.doc_id}").click()
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["page"] == "Review"
    assert at.session_state["selected_doc_id"] == mismatch_bundle.document.doc_id


def test_dashboard_shows_the_strip(fake_backend):
    assert 'data-stage="Export"' in _text(_run(dashboard, fake_backend))


def test_trace_page_offers_the_csv_drilldown_for_an_exported_document(
    fake_backend, tmp_path, clean_bundle
):
    backend = _with_batch(fake_backend, tmp_path)
    at = _run(trace, backend)
    at.session_state["selected_doc_id"] = clean_bundle.document.doc_id
    at.run(timeout=30)
    assert any("610200" in frame.value.to_string() for frame in at.dataframe)


def test_inbox_card_prefers_the_stored_type_then_manifest_then_printed_title(clean_bundle):
    doc = clean_bundle.document
    assert inbox_card(replace(doc, doc_type=DocType.CREDIT_NOTE), {}).type_label == "Credit note"
    untyped = replace(doc, doc_type=None)
    assert inbox_card(untyped, {doc.doc_id: "Type A"}).type_label == "Type A"
    assert inbox_card(untyped, {}).type_label == "Tax Invoice"
    assert inbox_card(replace(untyped, printed_title=None), {}).type_label == "Unclassified"


def test_inbox_card_outcome_tone_follows_status(clean_bundle):
    doc = clean_bundle.document
    assert inbox_card(replace(doc, status=DocStatus.AUTO_PASSED), {}).tone == "passed"
    assert inbox_card(replace(doc, status=DocStatus.NEEDS_REVIEW), {}).tone == "flagged"
    assert inbox_card(replace(doc, status=DocStatus.ON_HOLD), {}).tone == "held"


def test_type_labels_read_the_generator_manifest(tmp_path):
    from uuid import UUID

    doc_id = "e3b44d80-6038-5ce2-877d-d71b775fdcd1"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"documents": ['
        f'{{"doc_id": "{doc_id}", "doc_type": "TAX_INVOICE", "template": "A1"}},'
        '{"doc_id": "e3b44d80-6038-5ce2-877d-d71b775fdcd2", "doc_type": "STATEMENT",'
        ' "template": "SOA"}]}',
        encoding="utf-8",
    )
    labels = load_type_labels(manifest)
    assert labels[UUID(doc_id)] == "Type A"
    assert labels[UUID("e3b44d80-6038-5ce2-877d-d71b775fdcd2")] == "Statement"


def test_type_labels_tolerate_a_missing_manifest(tmp_path):
    assert load_type_labels(tmp_path / "none.json") == {}


def test_word_boxes_mark_hidden_text_red(clean_bundle):
    page = load_page_text(clean_bundle.pages[0].words_path)
    hidden = page.words[0].model_copy(update={"hidden": True})
    changed = page.model_copy(update={"words": (hidden, *page.words[1:])})
    boxes = word_boxes(changed)
    assert len(boxes) == len(page.words)
    assert boxes[0].status == "flagged"
    assert boxes[1].status == "passed"
    assert word_boxes(changed, hidden_only=True) == (boxes[0],)


def test_finding_rows_carry_rule_versions_for_the_technical_view():
    row = FindingRow(
        rule_id="R02",
        field="subtotal",
        severity=Severity.FLAG,
        scope=Scope.FIELD,
        message="Lines do not add up",
        rule_version="abc",
    )
    assert row.rule_version == "abc"


def test_inbox_sentence_accounts_for_every_document(fake_backend, clean_bundle, mismatch_bundle):
    fake_backend.bundles[clean_bundle.document.doc_id] = replace(
        clean_bundle, document=replace(clean_bundle.document, status=DocStatus.NOT_INVOICE)
    )
    at = _run(story, fake_backend)
    assert (
        "2 documents arrived and 1 was discarded (1 not an invoice). "
        "The other 1 is an invoice: 1 needs a person." in _text(at)
    )


def test_a_discarded_duplicate_counts_as_arrived(fake_backend, clean_bundle, mismatch_bundle):
    from app.models import DiscardedCopy

    fake_backend.copies = (
        DiscardedCopy("a (2).pdf", None, "a" * 64, "a" * 64, clean_bundle.document),
    )
    at = _run(story, fake_backend)
    assert (
        "3 documents arrived and 1 was discarded (1 copy of a file already in). "
        "The other 2 are invoices: 1 passed or approved, 1 needs a person." in _text(at)
    )
    assert 'data-stage="Intake"' in _text(at)
    assert "3 received, 1 discarded" in _text(at)


def test_the_sentence_matches_the_user_example():
    from app.counts import intake_counts
    from app.models import DocumentSummary
    from app.pages.story import _inbox_sentence

    counts = {
        DocStatus.AUTO_PASSED: 28,
        DocStatus.NEEDS_REVIEW: 11,
        DocStatus.ON_HOLD: 9,
        DocStatus.NOT_INVOICE: 1,
    }
    docs = [
        DocumentSummary(doc_id=uuid4(), status=status)
        for status, count in counts.items()
        for _ in range(count)
    ]
    assert _inbox_sentence(docs, intake_counts(docs, copies=1)) == (
        "50 documents arrived and 2 were discarded (1 copy of a file already in, "
        "1 not an invoice). The other 48 are invoices: 28 passed or approved, "
        "11 need a person, 9 on hold."
    )


def test_the_sentence_counts_invoices_still_being_read():
    from app.counts import intake_counts
    from app.models import DocumentSummary
    from app.pages.story import _inbox_sentence

    finished = [DocumentSummary(doc_id=uuid4(), status=DocStatus.AUTO_PASSED)]
    reading = [DocumentSummary(doc_id=uuid4(), status=DocStatus.RECEIVED)] * 2
    assert _inbox_sentence(finished, intake_counts(finished + reading, copies=0)) == (
        "3 documents arrived: 1 passed or approved, 2 still being read."
    )


def test_story_prefers_the_clearest_example_of_a_rule(clean_bundle, mismatch_bundle):
    noisy = replace(clean_bundle.document, open_rules=("R02", "R03", "R09"))
    clear = replace(mismatch_bundle.document, open_rules=("R02",))
    assert story._doc_with_rule((noisy, clear), "R02") is clear
    assert story._doc_with_rule((noisy, clear), "R08") is None


def test_export_sentence_uses_the_right_plural(fake_backend, tmp_path):
    at = _run(story, _with_batch(fake_backend, tmp_path))
    _advance(at, 6)
    assert "holds 1 row." in _text(at)
    assert "can be sent again from here" in _text(at)  # re-export allowed (2026-11-20)
    assert "1 other run found nothing new to export" in _text(at)


def test_accuracy_values_are_percentages(fake_backend, evaluation):
    fake_backend.evaluation = evaluation
    at = _run(story, fake_backend)
    _advance(at, 7)
    assert [metric.value for metric in at.metric if metric.label == "Accuracy"] == ["1.0%"]


# ---- every step follows the invoice picked in the dropdown --------------------------------


def _pick(at, doc_id):
    at.selectbox(key="story_document").set_value(doc_id).run(timeout=30)
    assert not at.exception, [str(exc) for exc in at.exception]
    return at


@pytest.mark.parametrize("step", [1, 2, 3, 4, 5])
def test_each_invoice_step_keeps_the_picked_invoice(fake_backend, clean_bundle, step):
    """Pick the clean invoice on Read, walk forward: no step may switch to another one."""
    at = _run(story, fake_backend)
    _advance(at, 1)
    clean_id = clean_bundle.document.doc_id
    _pick(at, clean_id)
    _advance(at, step - 1)
    assert at.session_state["selected_doc_id"] == clean_id
    assert at.selectbox(key="story_document").value == clean_id


def test_the_check_step_shows_the_picked_invoice(fake_backend, clean_bundle):
    at = _run(story, fake_backend)
    _advance(at, 1)
    _pick(at, clean_bundle.document.doc_id)
    _advance(at, 3)  # Step 5: "What did the system catch?"
    assert "What did the system catch?" in _text(at)
    assert any("No open findings" in item.value for item in at.success)


def test_an_example_button_jumps_only_when_clicked(fake_backend, clean_bundle, mismatch_bundle):
    at = _run(story, fake_backend)
    _advance(at, 1)
    _pick(at, clean_bundle.document.doc_id)
    _advance(at, 3)
    at.button(key="story_example_R02").click().run(timeout=30)
    assert at.session_state["selected_doc_id"] == mismatch_bundle.document.doc_id
    assert at.selectbox(key="story_document").value == mismatch_bundle.document.doc_id
    _advance(at, 1)  # and the next step keeps that invoice
    assert at.selectbox(key="story_document").value == mismatch_bundle.document.doc_id
