"""Integration: the Repository's SQL against the real dev Postgres (marked ``db``)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from invoiceflow.contracts import (
    BronzeFile,
    CodingLine,
    CodingSource,
    Confidence,
    DocStatus,
    DocumentRecord,
    ExportBatch,
    ExtractionResult,
    FieldValue,
    Finding,
    InvoiceExtraction,
    LLMMode,
    MatchType,
    Scope,
    Severity,
    ValueSource,
)
from invoiceflow.pipeline.golden import load_golden
from invoiceflow.store.repo import Repo

NOW = datetime(2026, 11, 4, 8, 0, tzinfo=UTC)


def _bronze() -> BronzeFile:
    return BronzeFile(
        file_id=uuid4(),
        sha256=uuid4().hex + uuid4().hex,  # 64 hex chars, unique so tests don't collide
        original_name="invoice.pdf",
        source="folder",
        received_at=NOW,
        size_bytes=10,
        mime_type="application/pdf",
        path="bronze/aa/sha",
    )


def _register_and_document(
    repo: Repo, status: DocStatus, vendor_id: str | None = None
) -> tuple[object, BronzeFile]:
    bronze = _bronze()
    assert repo.register_file(bronze) is True
    doc_id = uuid4()
    repo.create_document(
        DocumentRecord(doc_id=doc_id, file_id=bronze.file_id, status=status, vendor_id=vendor_id)
    )
    return doc_id, bronze


def test_schema_has_the_ap_tables(migrated):
    with migrated.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cur.fetchall()}
    assert {"bronze_files", "documents", "pages", "extractions", "fields", "export_rows"} <= tables


def test_register_and_document_roundtrip(migrated):
    repo = Repo(migrated)
    bronze = _bronze()
    assert repo.register_file(bronze) is True
    assert repo.register_file(bronze) is False  # same sha256 is a no-op

    doc_id = uuid4()
    repo.create_document(
        DocumentRecord(doc_id=doc_id, file_id=bronze.file_id, status=DocStatus.RECEIVED)
    )
    assert repo.get_document(doc_id).status is DocStatus.RECEIVED

    repo.set_status(doc_id, DocStatus.APPROVED, "ok")
    assert repo.get_document(doc_id).status is DocStatus.APPROVED
    assert [d.doc_id for d in repo.list_documents((DocStatus.APPROVED,))] == [doc_id]


def test_save_silver_and_read_coding(migrated):
    repo = Repo(migrated)
    repo.save_master(load_golden().master)
    doc_id, _ = _register_and_document(repo, DocStatus.RECEIVED)
    field = FieldValue(
        name="total",
        value_raw="1177.20",
        value_norm="1177.20",
        match_type=MatchType.EXACT,
        match_score=100.0,
        confidence=Confidence.HIGH,
        source=ValueSource.MODEL,
    )
    repo.save_fields(doc_id, (field,), ())

    line = CodingLine(
        line_no=1,
        gl_account="610200",
        cost_center="KG1100",
        tax_code="TX",
        net_amount=Decimal("1080.00"),
        tax_amount=Decimal("97.20"),
        source_line_nos=(1, 2),
        coding_source=CodingSource.PO,
    )
    repo.save_coding(doc_id, (line,))
    assert repo.coding_lines(doc_id) == (line,)

    finding = Finding(
        rule_id="R02",
        rule_version="v1",
        severity=Severity.FLAG,
        scope=Scope.FIELD,
        field="subtotal",
        message="mismatch",
    )
    repo.save_findings(doc_id, "run-1", (finding,))
    with migrated.cursor() as cur:
        cur.execute("SELECT rule_id, field FROM findings WHERE doc_id = %s", (doc_id,))
        assert cur.fetchone() == ("R02", "subtotal")


def test_master_roundtrip(migrated):
    repo = Repo(migrated)
    golden = load_golden()
    repo.save_master(golden.master)
    loaded = repo.load_master()
    assert loaded.vendor("V001").sap_vendor_no == "100014"
    assert loaded.purchase_order("4500012345").cost_center == "KG1100"
    assert loaded.coding.has_gl("610200")
    assert loaded.coding.cost_center_for_venue("SIS") == "KG1200"


def test_export_once_is_enforced(migrated):
    repo = Repo(migrated)
    repo.save_master(load_golden().master)
    doc_id, _ = _register_and_document(repo, DocStatus.APPROVED)
    repo.save_coding(
        doc_id,
        (
            CodingLine(
                line_no=1,
                gl_account="610200",
                cost_center="KG1100",
                tax_code="TX",
                net_amount=Decimal("1080.00"),
                tax_amount=Decimal("97.20"),
                coding_source=CodingSource.PO,
            ),
        ),
    )

    batch = ExportBatch(
        batch_id="export-1",
        created_at=NOW,
        csv_path="gold/export-1/export-1.csv",
        csv_sha256=uuid4().hex + uuid4().hex,
        row_count=1,
        total=Decimal("1177.20"),
        layout="hypothetical",
        mapping_version="1",
    )
    repo.record_export(batch, (doc_id,))
    assert repo.approved_not_exported() == ()

    # Sent again in a later batch (2026-11-20): allowed, and both sends are kept.
    repo.record_export(batch.model_copy(update={"batch_id": "export-2"}), (doc_id,))
    assert set(repo.previously_exported()) == {doc_id}
    with migrated.cursor() as cur:
        cur.execute("SELECT count(*) FROM export_rows WHERE doc_id = %s", (doc_id,))
        assert cur.fetchone()[0] == 2


def test_prior_invoices_returns_file_sha(migrated):
    repo = Repo(migrated)
    repo.save_master(load_golden().master)
    doc_id, bronze = _register_and_document(repo, DocStatus.APPROVED, vendor_id="V001")
    field = FieldValue(
        name="invoice_number",
        value_raw="SAV-2026-0412",
        value_norm="SAV-2026-0412",
        match_type=MatchType.EXACT,
        confidence=Confidence.HIGH,
        source=ValueSource.MODEL,
    )
    repo.save_fields(doc_id, (field,), ())

    priors = repo.prior_invoices("V001")
    assert len(priors) == 1
    assert priors[0].file_sha256 == bronze.sha256
    assert priors[0].invoice_number == "SAV-2026-0412"


def test_extraction_roundtrip(migrated):
    repo = Repo(migrated)
    doc_id, _ = _register_and_document(repo, DocStatus.EXTRACTED)
    result = ExtractionResult(
        extraction_id=uuid4(),
        doc_id=doc_id,
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
    repo.save_extraction(result)
    with migrated.cursor() as cur:
        cur.execute("SELECT model, valid FROM extractions WHERE doc_id = %s", (doc_id,))
        assert cur.fetchone() == ("golden-recorded", True)


def test_an_unfinished_document_is_found_by_its_file_hash(migrated):
    repo = Repo(migrated)
    doc_id, bronze = _register_and_document(repo, DocStatus.RECEIVED)
    assert repo.unfinished_document(bronze.sha256) == (doc_id, bronze.file_id)
    repo.set_status(doc_id, DocStatus.AUTO_PASSED, None)
    assert repo.unfinished_document(bronze.sha256) is None
    assert repo.unfinished_document("0" * 64) is None


def test_discard_removes_a_received_document_and_frees_its_file_hash(migrated):
    repo = Repo(migrated)
    doc_id, bronze = _register_and_document(repo, DocStatus.RECEIVED)
    repo.discard_document(doc_id, bronze.file_id)
    assert repo.get_document(doc_id) is None
    assert repo.register_file(bronze) is True


def test_discard_never_removes_a_finished_document(migrated):
    repo = Repo(migrated)
    doc_id, bronze = _register_and_document(repo, DocStatus.NEEDS_REVIEW)
    repo.discard_document(doc_id, bronze.file_id)
    assert repo.get_document(doc_id) is not None
    assert repo.register_file(bronze) is False
