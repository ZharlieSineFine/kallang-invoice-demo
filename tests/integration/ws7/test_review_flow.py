"""WS7 done-when on the fixture database: correct, recheck, approve, recode, trace."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app import queries, repo
from app.backend import CodingUpdate
from app.boxes import load_page_text, page_boxes, text_in_bbox
from app.ui import resolve_path
from invoiceflow.contracts import DocStatus, Finding, NormalizedLineItem, Scope, Severity

pytestmark = pytest.mark.db


def _mismatch(docs):
    return docs["SAV-2026-0413"]


def _hold_on_bank_account(conn, doc_id):
    hold = Finding(
        rule_id="R08",
        rule_version="test",
        severity=Severity.HOLD,
        scope=Scope.DOCUMENT,
        field="bank_account",
        message="The bank account differs from the vendor master.",
    )
    run_id = queries.latest_run_id(conn, doc_id) or "integration-hold"
    repo.save_findings(conn, doc_id, run_id, (hold,))
    repo.set_status(conn, doc_id, DocStatus.ON_HOLD, "bank account differs")


def test_a_correction_never_clears_a_hold(conn, backend, docs):
    doc = _mismatch(docs)
    _hold_on_bank_account(conn, doc.doc_id)

    fixed = backend.correct(doc.doc_id, "subtotal", "1,080.00", "integration.reviewer")
    assert fixed.status is DocStatus.ON_HOLD
    assert {finding.rule_id for finding in fixed.findings} >= {"R08"}
    assert "R02" not in {finding.rule_id for finding in fixed.findings}

    typed_over = backend.correct(doc.doc_id, "bank_account", "000-1", "integration.reviewer")
    assert typed_over.status is DocStatus.ON_HOLD

    with pytest.raises(ValueError, match="release the hold"):
        backend.approve(doc.doc_id, "integration.reviewer", "looks fine")

    released = backend.release_hold(doc.doc_id, "integration.reviewer", "Called the vendor.")
    assert released.status is DocStatus.NEEDS_REVIEW
    assert "R08" not in {finding.rule_id for finding in released.findings}
    approved = backend.approve(doc.doc_id, "integration.reviewer", "checked")
    assert approved.status is DocStatus.APPROVED


def test_released_hold_on_a_clean_invoice_still_waits_for_a_person(conn, backend, docs):
    doc = docs["SAV-2026-0412"]
    _hold_on_bank_account(conn, doc.doc_id)
    outcome = backend.release_hold(doc.doc_id, "integration.reviewer", "Called the vendor.")
    assert outcome.status is DocStatus.NEEDS_REVIEW
    assert backend.document(doc.doc_id).document.status is DocStatus.NEEDS_REVIEW


def test_correct_subtotal_clears_r02_and_approve_sets_approved(conn, backend, docs):
    doc = _mismatch(docs)
    before = backend.document(doc.doc_id)
    assert [finding.rule_id for finding in before.findings] == ["R02"]

    outcome = backend.correct(doc.doc_id, "subtotal", "1,080.00", "integration.reviewer")
    assert "R02" not in {finding.rule_id for finding in outcome.findings}
    assert outcome.status is DocStatus.NEEDS_REVIEW  # subtotal changed, total still printed

    after = backend.document(doc.doc_id)
    assert after.field("subtotal").value_norm == "1080.00"
    assert after.field("subtotal").source.value == "REVIEWER"
    assert "R02" not in {finding.rule_id for finding in after.findings}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT value_raw, value_norm, source, is_current
            FROM fields WHERE doc_id = %s AND name = 'subtotal'
            ORDER BY row_id
            """,
            (doc.doc_id,),
        )
        versions = cur.fetchall()
    assert len(versions) == 2
    assert versions[0] == ("1,090.00", "1090.00", "MODEL", False)
    assert versions[1] == ("1,080.00", "1080.00", "REVIEWER", True)

    approved = backend.approve(doc.doc_id, "integration.reviewer", "checked")
    assert approved.status is DocStatus.APPROVED
    final = backend.document(doc.doc_id)
    assert final.document.status is DocStatus.APPROVED
    assert [review.action.value for review in final.reviews] == ["CORRECT", "APPROVE"]
    assert any(event.type == "recheck.completed" for event in final.events)

    with conn.cursor() as cur:
        cur.execute("SELECT status FROM documents WHERE doc_id = %s", (doc.doc_id,))
        assert cur.fetchone()[0] == "APPROVED"


def test_edit_line_items_is_versioned_and_reruns_checks(conn, backend, docs):
    doc = _mismatch(docs)
    bundle = backend.document(doc.doc_id)
    items = tuple(
        NormalizedLineItem(
            line_no=item.line_no,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
            days=item.days,
            unit_price=item.unit_price,
            amount=Decimal("90.00") if item.line_no == 4 else item.amount,
        )
        for item in bundle.line_items
    )
    outcome = backend.edit_line_items(doc.doc_id, items, "integration.reviewer")
    # 540 + 300 + 160 + 90 == the printed 1,090 subtotal, so R02 clears.
    assert outcome.findings == ()
    # A person changed the invoice, so it waits for their approval instead of passing itself.
    assert outcome.status is DocStatus.NEEDS_REVIEW
    assert "Approve" in outcome.message
    assert queries.export_status(conn)["approved_not_exported"] == 1  # only the clean twin

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT line_no, amount, source, is_current FROM line_items
            WHERE doc_id = %s ORDER BY row_id
            """,
            (doc.doc_id,),
        )
        rows = cur.fetchall()
    current = [row for row in rows if row[3]]
    assert len(current) == 4
    assert all(row[2] == "REVIEWER" for row in current)
    assert next(row[1] for row in current if row[0] == 4) == Decimal("90.00")
    assert len(rows) == 8, "the four model rows stay as history"


def test_recode_accepts_only_seed_values(conn, backend, docs):
    doc = _mismatch(docs)
    outcome = backend.recode(
        doc.doc_id,
        [CodingUpdate(line_no=1, gl_account="610100", cost_center="KG1200", tax_code="ZP")],
        "integration.reviewer",
    )
    assert outcome.status in {DocStatus.NEEDS_REVIEW, DocStatus.AUTO_PASSED}
    bundle = backend.document(doc.doc_id)
    line = bundle.coding_lines[0]
    assert (line.gl_account, line.cost_center, line.tax_code) == ("610100", "KG1200", "ZP")
    assert line.coding_source.value == "REVIEWER"

    with pytest.raises(ValueError, match="active GL account"):
        backend.recode(
            doc.doc_id,
            [CodingUpdate(line_no=1, gl_account="999999", cost_center="KG1200", tax_code="ZP")],
            "integration.reviewer",
        )
    with pytest.raises(ValueError, match="tax code"):
        backend.recode(
            doc.doc_id,
            [CodingUpdate(line_no=1, gl_account="610100", cost_center="KG1200", tax_code="ZZ")],
            "integration.reviewer",
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT gl_account, cost_center, tax_code, coding_source, is_current
            FROM coding_lines WHERE doc_id = %s ORDER BY row_id
            """,
            (doc.doc_id,),
        )
        rows = cur.fetchall()
    assert rows[-1] == ("610100", "KG1200", "ZP", "REVIEWER", True)
    assert rows[0][4] is False


def test_release_hold_requires_a_comment(conn, backend, docs):
    doc = docs["SAV-2026-0412"]
    repo.set_status(conn, doc.doc_id, DocStatus.ON_HOLD, "integration hold")
    with pytest.raises(ValueError, match="needs a comment"):
        backend.release_hold(doc.doc_id, "integration.reviewer", "   ")
    outcome = backend.release_hold(doc.doc_id, "integration.reviewer", "Checked with finance.")
    assert outcome.status is not DocStatus.ON_HOLD
    bundle = backend.document(doc.doc_id)
    assert [review.action.value for review in bundle.reviews] == ["RELEASE_HOLD"]
    assert bundle.reviews[0].comment == "Checked with finance."


def test_trace_and_dashboard_read_current_runs(conn, backend, docs):
    before = backend.dashboard()
    assert before.total_documents == 2
    assert before.auto_pass_rate == 50.0
    assert before.findings_by_check[0].rule_id == "R02"
    assert before.corrections_by_field == ()

    backend.correct(_mismatch(docs).doc_id, "subtotal", "1,080.00", "integration.reviewer")
    after = backend.dashboard()
    assert {row.rule_id for row in after.findings_by_check} == {"R03"}
    assert after.corrections_by_field[0].key == "subtotal"
    assert after.corrections_by_vendor[0].key == "Stagecraft AV Rentals Pte. Ltd."

    trace = backend.trace(_mismatch(docs).doc_id)
    assert trace is not None
    assert "fixtures" in trace.runs
    assert any(run.startswith("review-") for run in trace.runs)
    assert trace.finding_history
    assert trace.bundle.events


def test_queries_match_the_pages(conn, backend, docs):
    doc = _mismatch(docs)
    bundle = backend.document(doc.doc_id)
    assert queries.latest_run_id(conn, doc.doc_id) == "fixtures"
    assert queries.fields(conn, doc.doc_id) == bundle.fields
    assert queries.line_items(conn, doc.doc_id) == bundle.line_items
    assert queries.coding_lines(conn, doc.doc_id) == bundle.coding_lines
    assert queries.pages(conn, doc.doc_id) == bundle.pages
    assert queries.extraction(conn, doc.doc_id) == bundle.extraction
    assert queries.master_data(conn).vendor("V001") is not None
    assert backend.batches() == ()
    assert backend.export_status() == {"exported": 0, "approved_not_exported": 1}


def test_boxes_line_up_with_stored_words(backend, docs):
    for invoice_number, doc in docs.items():
        bundle = backend.document(doc.doc_id)
        page = load_page_text(resolve_path(bundle.pages[0].words_path))
        boxes = page_boxes(
            page, bundle.fields, bundle.line_items, bundle.findings, selected="subtotal"
        )
        assert boxes
        for box in boxes:
            assert text_in_bbox(page, box.bbox), f"{invoice_number}: empty {box.field}"
        subtotal = next(box for box in boxes if box.field == "subtotal")
        assert text_in_bbox(page, subtotal.bbox) == (
            "1,080.00" if invoice_number.endswith("412") else "1,090.00"
        )


def test_review_errors_are_clear(conn, backend, docs):
    from uuid import uuid4

    unknown = uuid4()
    assert backend.document(unknown) is None
    with pytest.raises(LookupError):
        backend.confirm(unknown, "subtotal", "integration.reviewer")

    doc = _mismatch(docs)
    with pytest.raises(ValueError, match="not a header field"):
        backend.confirm(doc.doc_id, "nope", "integration.reviewer")
    with pytest.raises(ValueError, match="not a header field"):
        backend.correct(doc.doc_id, "nope", "1.00", "integration.reviewer")
    with pytest.raises(ValueError, match="cannot be empty"):
        backend.correct(doc.doc_id, "subtotal", "  ", "integration.reviewer")
    same = backend.correct(doc.doc_id, "subtotal", "1,090.00", "integration.reviewer")
    assert "already has that value" in same.message

    with pytest.raises(ValueError, match="at least one line item"):
        backend.edit_line_items(doc.doc_id, (), "integration.reviewer")
    duplicate = (
        NormalizedLineItem(line_no=1, amount=Decimal("1.00")),
        NormalizedLineItem(line_no=1, amount=Decimal("2.00")),
    )
    with pytest.raises(ValueError, match="unique"):
        backend.edit_line_items(doc.doc_id, duplicate, "integration.reviewer")

    with pytest.raises(ValueError, match="at least one coding line"):
        backend.recode(doc.doc_id, [], "integration.reviewer")
    with pytest.raises(ValueError, match="does not exist"):
        backend.recode(
            doc.doc_id,
            [CodingUpdate(9, "610100", "KG1100", "TX")],
            "integration.reviewer",
        )
    with pytest.raises(ValueError, match="active cost center"):
        backend.recode(
            doc.doc_id,
            [CodingUpdate(1, "610100", "NOPE", "TX")],
            "integration.reviewer",
        )

    repo.set_status(conn, doc.doc_id, DocStatus.EXPORTED, "exported")
    with pytest.raises(ValueError, match="cannot reject"):
        backend.reject(doc.doc_id, "integration.reviewer")
    repo.set_status(conn, doc.doc_id, DocStatus.REJECTED, "rejected")
    with pytest.raises(ValueError, match="cannot approve"):
        backend.approve(doc.doc_id, "integration.reviewer")


def test_release_hold_that_still_has_a_hold_goes_back_to_review(conn, backend, docs):
    from invoiceflow.settings import load_config

    doc = _mismatch(docs)
    config = load_config("rules")
    config["severities"] = {**config["severities"], "R02": "HOLD"}
    strict = type(backend)(conn, rules_config=config)
    repo.set_status(conn, doc.doc_id, DocStatus.ON_HOLD, "strict hold")
    outcome = strict.release_hold(doc.doc_id, "integration.reviewer", "Finance reviewed it.")
    assert outcome.status is DocStatus.NEEDS_REVIEW
    assert "still needs review" in outcome.message


def test_batches_and_master_reads(conn, backend, docs):
    master = backend.master()
    assert master.vendor("V001").name == "Stagecraft AV Rentals Pte. Ltd."
    assert backend.batches() == ()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO export_batches (batch_id, csv_path, csv_sha256, row_count, total,
                layout, mapping_version)
            VALUES ('B-INT', 'data/gold/B-INT.csv', %s, 1, 1177.20, 'hypothetical', 'sap-v1')
            """,
            ("0" * 64,),
        )
        cur.execute(
            """
            INSERT INTO export_rows (batch_id, doc_id, first_row_no, row_count)
            VALUES ('B-INT', %s, 1, 1)
            """,
            (docs["SAV-2026-0412"].doc_id,),
        )
    batches = backend.batches()
    assert len(batches) == 1
    assert batches[0].batch_id == "B-INT"
    assert batches[0].doc_ids == (docs["SAV-2026-0412"].doc_id,)
    assert backend.export_status()["exported"] == 1


def test_correct_as_printed_clears_the_flag_and_later_rechecks_respect_it(conn, backend, docs):
    doc = _mismatch(docs)
    outcome = backend.confirm(doc.doc_id, "subtotal", "integration.reviewer")
    assert not [f for f in outcome.findings if f.field == "subtotal"]
    assert outcome.status is DocStatus.NEEDS_REVIEW  # a person still approves it
    assert "subtotal" in outcome.message

    # Another correction reruns the checks; R02 on the accepted subtotal must not come back.
    later = backend.correct(doc.doc_id, "total", "1,188.20", "integration.reviewer")
    assert not [f for f in later.findings if f.field == "subtotal"]
    reviews = [review.action.value for review in backend.document(doc.doc_id).reviews]
    assert reviews == ["CONFIRM", "CORRECT"]


def test_correct_as_printed_never_clears_a_hold(conn, backend, docs):
    doc = _mismatch(docs)
    _hold_on_bank_account(conn, doc.doc_id)
    outcome = backend.confirm(doc.doc_id, "bank_account", "integration.reviewer")
    assert outcome.status is DocStatus.ON_HOLD
    assert "R08" in {finding.rule_id for finding in outcome.findings}


def test_a_line_item_value_can_be_accepted_as_printed(conn, backend, docs):
    doc = _mismatch(docs)
    outcome = backend.confirm(doc.doc_id, "line_items[0].amount", "integration.reviewer")
    assert outcome.doc_id == doc.doc_id
    review = backend.document(doc.doc_id).reviews[-1]
    assert (review.action.value, review.field) == ("CONFIRM", "line_items[0].amount")


def test_a_value_the_model_did_not_read_can_be_typed_in(conn, backend, docs):
    """e.g. R03 "GST registration number is missing": the reviewer reads it off the image."""
    from invoiceflow.contracts import HEADER_FIELDS

    doc = _mismatch(docs)
    stored = {field.name for field in backend.document(doc.doc_id).fields}
    missing = next(
        name for name in ("supplier_gst_reg_no", "po_number", *HEADER_FIELDS) if name not in stored
    )
    backend.correct(doc.doc_id, missing, "M2-1234567-8", "integration.reviewer")
    row = backend.document(doc.doc_id).field(missing)
    assert row is not None and row.value_raw == "M2-1234567-8"
    assert row.source.value == "REVIEWER"


def test_the_app_runs_the_sap_export_once(backend, monkeypatch, tmp_path):
    monkeypatch.setenv("INVOICEFLOW_DATA", str(tmp_path))
    ready = backend.export_status()["approved_not_exported"]
    assert ready >= 1

    first = backend.run_export()
    assert first.invoices == ready
    assert first.row_count >= ready
    batch = next(item for item in backend.batches() if item.batch_id == first.batch_id)
    assert resolve_path(batch.csv_path).is_file()
    assert backend.export_status()["approved_not_exported"] == 0

    second = backend.run_export()
    assert second.invoices == 0
    assert "Nothing new" in second.message


def _with_line_four(bundle, amount: str):
    return tuple(
        NormalizedLineItem(
            line_no=item.line_no,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
            days=item.days,
            unit_price=item.unit_price,
            amount=Decimal(amount) if item.line_no == 4 else item.amount,
        )
        for item in bundle.line_items
    )


def test_coding_follows_a_corrected_line_amount(backend, docs):
    doc = _mismatch(docs)
    before = backend.document(doc.doc_id)
    assert sum(line.net_amount for line in before.coding_lines) == Decimal("1080.00")

    backend.edit_line_items(doc.doc_id, _with_line_four(before, "90.00"), "integration.reviewer")
    after = backend.document(doc.doc_id)
    assert sum(line.net_amount for line in after.coding_lines) == Decimal("1090.00")
    assert any(event.type == "coding.recomputed" for event in after.events)


def test_coding_tax_follows_a_corrected_gst_amount(backend, docs):
    doc = _mismatch(docs)
    backend.correct(doc.doc_id, "gst_amount", "98.10", "integration.reviewer")
    after = backend.document(doc.doc_id)
    assert sum(line.tax_amount for line in after.coding_lines) == Decimal("98.10")


def test_a_reviewers_coding_survives_a_later_correction(backend, docs):
    doc = _mismatch(docs)
    backend.recode(
        doc.doc_id,
        [CodingUpdate(line_no=1, gl_account="610100", cost_center="KG1200", tax_code="TX")],
        "integration.reviewer",
    )
    bundle = backend.document(doc.doc_id)
    backend.edit_line_items(doc.doc_id, _with_line_four(bundle, "90.00"), "integration.reviewer")
    line = backend.document(doc.doc_id).coding_lines[0]
    assert (line.gl_account, line.cost_center) == ("610100", "KG1200")
    assert line.coding_source.value == "REVIEWER"
    assert line.net_amount == Decimal("1090.00")


def test_a_correction_that_leaves_the_amounts_alone_saves_no_new_coding(conn, backend, docs):
    doc = _mismatch(docs)

    def versions():
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM coding_lines WHERE doc_id = %s", (doc.doc_id,))
            return cur.fetchone()[0]

    before = versions()
    backend.correct(doc.doc_id, "subtotal", "1,080.00", "integration.reviewer")
    assert versions() == before


def test_a_discarded_duplicate_counts_only_while_its_original_is_stored(conn, backend):
    assert backend.discarded_duplicates() == 0
    with conn.cursor() as cur:
        cur.execute("SELECT sha256 FROM bronze_files LIMIT 1")
        stored = cur.fetchone()[0].strip()
    for sha in (stored, "f" * 64):  # a copy of a stored file, and of one erased since
        payload = {"sha256": sha, "name": "copy (2).pdf"}
        repo.log_event(conn, "pipeline", "intake.duplicate_file", None, payload)
    assert backend.discarded_duplicates() == 1


def test_a_discarded_copy_is_shown_beside_the_original_it_matched(conn, backend):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trim(b.sha256), d.doc_id FROM bronze_files b"
            " JOIN documents d ON d.file_id = b.file_id LIMIT 1"
        )
        stored, doc_id = cur.fetchone()
    payload = {"sha256": stored, "name": "copy (2).pdf"}
    repo.log_event(conn, "pipeline", "intake.duplicate_file", None, payload)
    (copy,) = backend.discarded_copies()
    assert copy.name == "copy (2).pdf"
    assert copy.arrived_at is not None
    assert copy.sha256 == copy.kept_sha256 == stored  # padding trimmed, so the two compare
    assert copy.is_identical
    assert copy.original.doc_id == doc_id
