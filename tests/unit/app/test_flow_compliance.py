"""The pipeline flow strip and the compliance cards: pure logic, no Streamlit session."""

from __future__ import annotations

from dataclasses import replace

from app.compliance import CARDS, card_for, card_html
from app.flow import STAGES, StageTone, batch_outcomes, flow_strip_html
from app.models import DocumentSummary
from invoiceflow.contracts import DocStatus, Severity


def _doc(index: int, status: DocStatus, severity: Severity | None = None) -> DocumentSummary:
    from uuid import NAMESPACE_URL, uuid5

    return DocumentSummary(
        doc_id=uuid5(NAMESPACE_URL, str(index)),
        status=status,
        highest_severity=severity,
        extraction_valid=True,
    )


def _tones(docs) -> dict[str, StageTone]:
    return {outcome.name: outcome.tone for outcome in batch_outcomes(docs)}


def test_every_stage_is_reported_in_pipeline_order():
    assert [outcome.name for outcome in batch_outcomes(())] == list(STAGES)
    assert STAGES == ("Intake", "Read", "Extract", "Check", "Review", "Export")


def test_an_empty_system_is_idle_not_green():
    assert set(_tones(()).values()) == {StageTone.IDLE}


def test_clean_documents_are_green_through_the_checks():
    tones = _tones([_doc(1, DocStatus.AUTO_PASSED), _doc(2, DocStatus.AUTO_PASSED)])
    assert tones["Intake"] is StageTone.PASSED
    assert tones["Read"] is StageTone.PASSED
    assert tones["Extract"] is StageTone.PASSED
    assert tones["Check"] is StageTone.PASSED
    assert tones["Review"] is StageTone.PASSED


def test_a_flag_turns_check_and_review_amber():
    tones = _tones([_doc(1, DocStatus.NEEDS_REVIEW, Severity.FLAG)])
    assert tones["Check"] is StageTone.FLAGGED
    assert tones["Review"] is StageTone.FLAGGED


def test_a_hold_beats_a_flag_and_turns_check_red():
    docs = [
        _doc(1, DocStatus.NEEDS_REVIEW, Severity.FLAG),
        _doc(2, DocStatus.ON_HOLD, Severity.HOLD),
    ]
    outcomes = {outcome.name: outcome for outcome in batch_outcomes(docs)}
    assert outcomes["Check"].tone is StageTone.HELD
    assert outcomes["Check"].summary == "1 held, 1 flagged"
    assert outcomes["Review"].summary == "2 waiting"


def test_unreadable_documents_turn_read_amber():
    assert _tones([_doc(1, DocStatus.MANUAL_ENTRY, Severity.MANUAL)])["Read"] is StageTone.FLAGGED


def test_invalid_model_output_turns_extract_amber():
    doc = replace(_doc(1, DocStatus.MANUAL_ENTRY), extraction_valid=False)
    assert _tones([doc])["Extract"] is StageTone.FLAGGED


def test_export_is_green_only_once_something_was_exported():
    assert _tones([_doc(1, DocStatus.APPROVED)])["Export"] is StageTone.IDLE
    assert _tones([_doc(1, DocStatus.EXPORTED)])["Export"] is StageTone.PASSED


def test_strip_marks_the_current_stage_and_escapes_text():
    html = flow_strip_html(batch_outcomes([_doc(1, DocStatus.AUTO_PASSED)]), current="Check")
    assert html.count('data-current="true"') == 1
    assert 'data-stage="Check" data-current="true"' in html
    for stage in STAGES:
        assert stage in html


def test_strip_sets_explicit_text_colors_for_dark_theme():
    assert "color:#" in flow_strip_html(batch_outcomes(()))


def test_all_twelve_rules_have_a_card():
    assert sorted(CARDS) == [f"R{number:02d}" for number in range(1, 13)]
    assert card_for("R99") is None


def test_every_external_citation_has_a_link_and_internal_controls_do_not_claim_one():
    for card in CARDS.values():
        assert card.requirement.strip()
        assert card.source.strip()
        if card.kind == "Internal control":
            assert card.url is None
        else:
            assert card.url is None or card.url.startswith("https://")


def test_key_citations_name_the_right_authority():
    assert "IRAS" in card_for("R03").source
    assert "S$1,000" in card_for("R03").requirement
    assert "Singapore Police Force" in card_for("R08").source
    assert "OWASP LLM01:2025" in card_for("R09").source


def test_iras_is_not_cited_for_readability_because_its_page_does_not_say_so():
    assert "IRAS" not in card_for("R07").source


def test_card_html_escapes_and_keeps_dollars_out_of_markdown_math():
    html = card_html(card_for("R03"))
    assert "S$1,000" in html
    assert 'href="https://www.iras.gov.sg' in html
    assert "color:#" in html


def test_not_invoices_are_counted_apart_at_check():
    # A statement or a résumé is not a problem to fix: it is counted on its own, not flagged.
    docs = [
        _doc(1, DocStatus.NEEDS_REVIEW, Severity.FLAG),
        _doc(2, DocStatus.NOT_INVOICE, Severity.FLAG),
        _doc(3, DocStatus.NOT_INVOICE),
    ]
    outcomes = {outcome.name: outcome for outcome in batch_outcomes(docs)}
    assert outcomes["Check"].summary == "1 flagged, 2 not invoices"
    assert outcomes["Check"].tone is StageTone.FLAGGED


def test_one_not_invoice_among_clean_invoices():
    docs = [_doc(1, DocStatus.AUTO_PASSED), _doc(2, DocStatus.NOT_INVOICE, Severity.FLAG)]
    outcomes = {outcome.name: outcome for outcome in batch_outcomes(docs)}
    assert outcomes["Check"].summary == "1 not an invoice"
    assert outcomes["Check"].tone is StageTone.PASSED
