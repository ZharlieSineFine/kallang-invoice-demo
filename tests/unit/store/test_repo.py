"""Unit tests for ``Repo`` against a scripted fake connection (no Postgres needed).

The real SQL is exercised by ``tests/integration/ws6/``; these tests pin the code paths and
prove every statement is parameterized (values are passed as ``%s`` params, never inlined).
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from invoiceflow.contracts import (
    BBox,
    BronzeFile,
    CodingLine,
    CodingSource,
    Confidence,
    DocStatus,
    DocType,
    DocumentRecord,
    ExportBatch,
    ExtractionResult,
    FieldValue,
    FileKind,
    Finding,
    InvoiceExtraction,
    LLMMode,
    MatchType,
    NormalizedLineItem,
    PageText,
    ParsedDocument,
    Review,
    ReviewAction,
    Scope,
    Severity,
    TextSource,
    ValueSource,
    Word,
)
from invoiceflow.store.repo import Repo

DOC_ID = UUID("93fe9312-fe79-50bb-b5e7-d18e83dfaff2")
FILE_ID = UUID("9c3e3184-0bf8-50ab-8c49-3689d2b51dd4")
SHA = "8e994f46d45f647001d79a07f22cea21aa2b23dea5189cff9fd392a71f68d3bc"
NOW = datetime(2026, 11, 4, 8, 0, tzinfo=UTC)


def _word(text: str) -> Word:
    return Word(text=text, bbox=BBox(x0=0.0, y0=0.0, x1=0.1, y1=0.1))


def _page() -> PageText:
    return PageText(
        page_no=1,
        width_pt=595.0,
        height_pt=842.0,
        source=TextSource.PDF_TEXT,
        words=(_word("SAV-2026-0412"),),
    )


def _parsed() -> ParsedDocument:
    return ParsedDocument(doc_id=DOC_ID, file_id=FILE_ID, file_kind=FileKind.PDF, pages=(_page(),))


def _extraction() -> ExtractionResult:
    return ExtractionResult(
        extraction_id=uuid4(),
        doc_id=DOC_ID,
        model="golden-recorded",
        prompt_version="extract-v1",
        schema_version="extraction-v1",
        params={},
        mode=LLMMode.REPLAY,
        raw_output="{}",
        extraction=InvoiceExtraction(invoice_number="SAV-2026-0412"),
        valid=True,
        created_at=NOW,
    )


def _field() -> FieldValue:
    return FieldValue(
        name="invoice_number",
        value_raw="SAV-2026-0412",
        value_norm="SAV-2026-0412",
        page_no=1,
        bbox=BBox(x0=0.0, y0=0.0, x1=0.2, y1=0.02),
        match_type=MatchType.EXACT,
        match_score=100.0,
        confidence=Confidence.HIGH,
        source=ValueSource.MODEL,
    )


def _finding() -> Finding:
    return Finding(
        rule_id="R02",
        rule_version="v1",
        severity=Severity.FLAG,
        scope=Scope.FIELD,
        field="subtotal",
        message="lines do not match",
        evidence={"a": "b"},
    )


def _bronze() -> BronzeFile:
    return BronzeFile(
        file_id=FILE_ID,
        sha256=SHA,
        original_name="invoice.pdf",
        source="folder",
        received_at=NOW,
        size_bytes=10,
        mime_type="application/pdf",
        path="bronze/aa/sha",
    )


def test_register_file_inserts_when_new(make_connection):
    conn = make_connection(results={"RETURNING file_id": (FILE_ID,)})
    assert Repo(conn).register_file(_bronze()) is True
    sql, params = conn.statements[0]
    assert "INSERT INTO bronze_files" in sql and "ON CONFLICT (sha256) DO NOTHING" in sql
    assert params[1] == SHA and params[2] == "invoice.pdf"


def test_register_file_reports_existing(make_connection):
    conn = make_connection(results={"RETURNING file_id": None})
    assert Repo(conn).register_file(_bronze()) is False


def test_create_and_get_document(make_connection):
    conn = make_connection()
    Repo(conn).create_document(
        DocumentRecord(doc_id=DOC_ID, file_id=FILE_ID, status=DocStatus.RECEIVED)
    )
    sql, params = conn.statements[0]
    assert "INSERT INTO documents" in sql
    assert params[0] == DOC_ID and params[2] is None and params[3] == "RECEIVED"

    row = (DOC_ID, FILE_ID, "TAX_INVOICE", "RECEIVED", None, "V001")
    record = Repo(make_connection(results={"WHERE doc_id = %s": row})).get_document(DOC_ID)
    assert record.doc_id == DOC_ID and record.status is DocStatus.RECEIVED
    assert record.doc_type is DocType.TAX_INVOICE and record.vendor_id == "V001"


def test_get_document_missing_returns_none(make_connection):
    assert Repo(make_connection(results={"WHERE doc_id = %s": None})).get_document(DOC_ID) is None


def test_set_status_and_list_documents(make_connection):
    conn = make_connection()
    Repo(conn).set_status(DOC_ID, DocStatus.APPROVED, "ok")
    sql, params = conn.statements[0]
    assert "UPDATE documents SET status" in sql and params == ("APPROVED", "ok", DOC_ID)

    rows = [(DOC_ID, FILE_ID, "TAX_INVOICE", "APPROVED", None, "V001")]
    listed = Repo(make_connection(results={"status = ANY": rows})).list_documents(
        (DocStatus.APPROVED,)
    )
    assert [r.status for r in listed] == [DocStatus.APPROVED]


def test_save_parsed_writes_one_page(make_connection):
    conn = make_connection()
    Repo(conn).save_parsed(_parsed())
    sql, params = conn.statements[0]
    assert "INSERT INTO pages" in sql
    assert params[0] == DOC_ID and params[1] == 1 and params[2] == "PDF_TEXT"
    assert params[6] == f"silver/{DOC_ID}/page-1.words.json"


def test_save_extraction_serializes_parsed_json(make_connection):
    conn = make_connection()
    Repo(conn).save_extraction(_extraction())
    sql, params = conn.statements[0]
    assert "INSERT INTO extractions" in sql
    assert params[5] == "extraction-v1" and params[10] is True


def test_save_fields_marks_previous_not_current(make_connection):
    conn = make_connection()
    item = NormalizedLineItem(line_no=1, description="rental", amount=Decimal("1080.00"))
    Repo(conn).save_fields(DOC_ID, (_field(),), (item,))
    sqls = [s for s, _ in conn.statements]
    assert any("UPDATE fields SET is_current" in s for s in sqls)
    assert any("UPDATE line_items SET is_current" in s for s in sqls)
    insert_fields = next(s for s in sqls if "INSERT INTO fields" in s)
    assert insert_fields.count("%s") == 13


def test_save_coding_and_findings(make_connection):
    conn = make_connection()
    line = CodingLine(
        line_no=1,
        gl_account="610200",
        cost_center="KG1100",
        tax_code="TX",
        net_amount=Decimal("1080.00"),
        tax_amount=Decimal("97.20"),
        description="rental",
        source_line_nos=(1, 2),
        coding_source=CodingSource.PO,
    )
    Repo(conn).save_coding(DOC_ID, (line,))
    sql, params = conn.statements[-1]
    assert "INSERT INTO coding_lines" in sql and params[9] == "PO"

    Repo(conn).save_findings(DOC_ID, "run-1", (_finding(),))
    sql, params = conn.statements[-1]
    assert "INSERT INTO findings" in sql and params[1] == "run-1" and params[3] == "R02"


def test_add_review(make_connection):
    conn = make_connection()
    review = Review(doc_id=DOC_ID, reviewer="finance", action=ReviewAction.APPROVE, created_at=NOW)
    Repo(conn).add_review(review)
    sql, params = conn.statements[0]
    assert "INSERT INTO reviews" in sql and params[2] == "APPROVE"


def test_load_master_builds_master_data(make_connection):
    results = {
        "FROM vendors": (
            "V001",
            "100014",
            "Stagecraft AV Rentals Pte. Ltd.",
            "209900123K",
            "209900123K",
            "18 Fictional Lane",
            "DBS Bank",
            "0001234567",
            "SGD",
            "SG",
            False,
            "610200",
            "KG2100",
            "TX",
            True,
        ),
        "FROM purchase_orders": (
            "4500012345",
            "V001",
            "SGD",
            "5000.00",
            "5000.00",
            "610200",
            "KG1100",
        ),
        "FROM gl_accounts": ("610200", "Equipment rental", True),
        "FROM cost_centers": ("KG1100", "National Stadium", True),
        "FROM tax_codes": ("TX", "9", "Standard-rated"),
        "FROM venue_cost_centers": ("National Stadium", "KG1100"),
    }
    master = Repo(make_connection(results=results)).load_master()
    assert master.company.company_code == "KG01"
    assert master.vendor("V001").sap_vendor_no == "100014"
    assert master.purchase_order("4500012345").cost_center == "KG1100"
    assert master.coding.has_gl("610200")
    assert master.coding.tax_rate("TX") == Decimal("9")
    assert master.coding.cost_center_for_venue("National Stadium") == "KG1100"


def test_prior_invoices_parses_values(make_connection):
    row = (DOC_ID, "V001", "SAV-2026-0412", "1177.20", "2026-04-12", SHA)
    priors = Repo(
        make_connection(results={"FROM documents d JOIN bronze_files": [row]})
    ).prior_invoices("V001")
    assert len(priors) == 1
    prior = priors[0]
    assert prior.invoice_number == "SAV-2026-0412"
    assert prior.total == Decimal("1177.20")
    assert prior.invoice_date == date(2026, 4, 12)
    assert prior.file_sha256 == SHA


def test_approved_not_exported_and_record_export(make_connection):
    conn = make_connection(results={"LEFT JOIN export_rows": [(DOC_ID,)], "count(*)": (2,)})
    repo = Repo(conn)
    assert repo.approved_not_exported() == (DOC_ID,)

    batch = ExportBatch(
        batch_id="export-1",
        created_at=NOW,
        csv_path="gold/export-1/export-1.csv",
        csv_sha256=SHA,
        row_count=2,
        total=Decimal("1177.20"),
        layout="hypothetical",
        mapping_version="1",
    )
    repo.record_export(batch, (DOC_ID,))
    sqls = [s for s, _ in conn.statements]
    assert any("INSERT INTO export_batches" in s for s in sqls)
    assert any("INSERT INTO export_rows" in s for s in sqls)
    assert any("UPDATE documents SET status" in s for s in sqls)


def test_coding_lines_reads_current_rows(make_connection):
    row = (1, "610200", "KG1100", "TX", "1080.00", "97.20", "rental", [1, 2], "PO")
    lines = Repo(make_connection(results={"FROM coding_lines WHERE doc_id": [row]})).coding_lines(
        DOC_ID
    )
    assert lines[0].line_no == 1 and lines[0].coding_source is CodingSource.PO
    assert lines[0].source_line_nos == (1, 2)


def test_log_event(make_connection):
    conn = make_connection()
    Repo(conn).log_event("pipeline", "intake.received", DOC_ID, {"k": "v"})
    sql, params = conn.statements[0]
    assert "INSERT INTO events" in sql and params[1] == DOC_ID
