"""The confirmation after an action names what was done, to which invoice, and what happens
next (user's request, 2026-11-20). Green means it worked, amber that it worked but more is
needed, red only that it failed; a tag shows the invoice's new status."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.backend import ExportOutcome
from app.models import DeleteOutcome, DocumentSummary, ReviewOutcome
from app.notice import Act, Tone, delete_notice, done_notice, export_notice, failed_notice
from app.notice_view import card_html, popup_html
from invoiceflow.contracts import DocStatus

VTR = DocumentSummary(
    doc_id=uuid4(),
    status=DocStatus.NEEDS_REVIEW,
    invoice_number="VTR-2026-9604",
    vendor_name="VenueTech Rigging Pte. Ltd.",
    total=Decimal("1057.30"),
)
REJECT = Act("Rejected", "reject", doc=VTR, by="demo.reviewer", next_step="It will not be paid.")


def _outcome(status: DocStatus, **kwargs) -> ReviewOutcome:
    return ReviewOutcome(doc_id=VTR.doc_id, status=status, message="Rejected", **kwargs)


def test_a_reject_names_the_invoice_its_vendor_and_total_and_is_green():
    notice = done_notice(REJECT, _outcome(DocStatus.REJECTED))
    assert notice.tone is Tone.SUCCESS  # it worked, even though the news is bad
    assert notice.headline == "Rejected VTR-2026-9604"
    assert notice.subject == "VenueTech Rigging Pte. Ltd. · S$1,057.30"
    assert notice.detail == "It will not be paid."
    assert notice.status is DocStatus.REJECTED
    assert notice.recorded.startswith("Recorded under demo.reviewer at ")
    assert notice.recorded.endswith(" SGT.")


def test_a_reject_with_open_findings_is_still_green():
    findings_left = _outcome(DocStatus.REJECTED, findings=("R09",))
    assert done_notice(REJECT, findings_left).tone is Tone.SUCCESS


def test_a_correction_that_leaves_a_check_open_is_amber_and_says_which():
    act = Act("Corrected subtotal on", "save the correction to", doc=VTR, by="demo.reviewer")
    outcome = _outcome(
        DocStatus.NEEDS_REVIEW, checks="Checks rerun: NEEDS_REVIEW (R03)", findings=("R03",)
    )
    notice = done_notice(act, outcome)
    assert notice.tone is Tone.WARNING
    assert notice.headline == "Corrected subtotal on VTR-2026-9604"
    assert notice.detail == "Checks rerun: NEEDS_REVIEW (R03)"


def test_a_correction_that_clears_every_check_is_green():
    # Only the usual approval is left, so nothing more is needed than for any invoice.
    act = Act("Corrected subtotal on", "save the correction to", doc=VTR, change="1 → 2.")
    outcome = _outcome(DocStatus.NEEDS_REVIEW, checks="Checks rerun: nothing open.")
    notice = done_notice(act, outcome)
    assert notice.tone is Tone.SUCCESS
    assert notice.detail == "1 → 2. Checks rerun: nothing open."


def test_an_audit_says_what_was_recorded():
    act = Act("Recorded the audit of", "record the audit of", doc=VTR)
    assert done_notice(act, "Audit recorded.").detail == "Audit recorded."


def test_nothing_saved_is_said_plainly():
    act = Act("Corrected subtotal on", "save the correction to", doc=VTR)
    outcome = ReviewOutcome(
        VTR.doc_id, DocStatus.NEEDS_REVIEW, "subtotal already has that value", changed=False
    )
    notice = done_notice(act, outcome)
    assert notice.tone is Tone.INFO
    assert notice.headline == "Nothing changed on VTR-2026-9604"
    assert notice.detail == "subtotal already has that value"


def test_a_failed_action_says_it_was_not_done_and_why():
    act = Act("Approved", "approve", doc=VTR)
    notice = failed_notice(act, ValueError("release the hold, with a comment, before approving"))
    assert notice.tone is Tone.ERROR
    assert notice.headline == "Could not approve VTR-2026-9604"
    assert notice.detail == "Release the hold, with a comment, before approving."
    assert notice.status is None


def test_an_export_says_how_many_went_to_sap():
    notice = export_notice(ExportOutcome(batch_id="B-7", invoices=3, row_count=5))
    assert notice.tone is Tone.SUCCESS
    assert notice.headline == "Exported 3 invoices to SAP"
    assert notice.subject == "Batch B-7 · 5 CSV rows"
    empty = export_notice(ExportOutcome(batch_id="B-8", invoices=0, row_count=0))
    assert empty.tone is Tone.INFO
    assert empty.headline == "Nothing new to export"


def test_invoices_held_back_from_an_export_make_it_amber():
    outcome = ExportOutcome(batch_id="B-9", invoices=2, row_count=2, problems=("X-1: no vendor",))
    notice = export_notice(outcome)
    assert notice.tone is Tone.WARNING
    assert "X-1: no vendor" in notice.detail


def test_a_delete_of_an_exported_invoice_is_amber_and_says_sap_still_has_it():
    notice = delete_notice(DeleteOutcome(("VTR-2026-9604",), exported=1), (VTR,), by="me")
    assert notice.tone is Tone.WARNING
    assert notice.headline == "Deleted VTR-2026-9604"
    assert notice.subject == "VenueTech Rigging Pte. Ltd. · S$1,057.30"
    assert "SAP still has it" in notice.detail
    several = delete_notice(DeleteOutcome(("A-1", "B-2")), (), by="me")
    assert several.tone is Tone.SUCCESS
    assert several.headline == "Deleted 2 documents"
    assert several.subject == "A-1, B-2"


def test_the_card_is_colored_escaped_and_tagged_with_the_new_status():
    notice = done_notice(REJECT, _outcome(DocStatus.REJECTED))
    html = card_html(notice)
    assert 'data-notice="card"' in html
    assert 'data-tone="success"' in html
    assert "Rejected VTR-2026-9604" in html
    assert "VenueTech Rigging Pte. Ltd. · S$1,057.30" in html
    assert 'data-status="REJECTED"' in html
    unsafe = done_notice(Act("Rejected", "reject", doc=VTR, next_step="<b>x</b>"), _outcome(None))
    assert "<b>x</b>" not in card_html(unsafe)


def test_the_pop_up_floats_in_the_corner_and_fades():
    html = popup_html(done_notice(REJECT, _outcome(DocStatus.REJECTED)))
    assert 'data-notice="popup"' in html
    assert "position:fixed" in html
    assert "animation:" in html
    assert "Rejected VTR-2026-9604" in html
