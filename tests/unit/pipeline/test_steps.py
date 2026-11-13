"""Step functions: intake (inbox -> bronze -> silver) and the export-once loop."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from invoiceflow.contracts import (
    CodingLine,
    CodingSource,
    DocStatus,
    DocumentRecord,
    NormalizedInvoice,
)
from invoiceflow.pipeline.golden import load_golden
from invoiceflow.pipeline.steps import (
    Pipeline,
    build_pipeline,
    export_approved,
    guess_mime,
    intake_document,
    intake_inbox,
    list_inbox,
)
from invoiceflow.pipeline.stubs import golden_deps
from invoiceflow.settings import load_config
from invoiceflow.storage import LocalBlobStore

TODAY = date(2026, 11, 4)


class FakeRepo:
    """In-memory stand-in for the Repository, enough for the step functions."""

    def __init__(self):
        self.shas: set[str] = set()
        self.documents: dict[UUID, DocumentRecord] = {}
        self.statuses: dict[UUID, DocStatus] = {}
        self.coding: dict[UUID, tuple[CodingLine, ...]] = {}
        self.exported: set[UUID] = set()
        self.batches: list[tuple] = []
        self.events: list[tuple] = []
        self.saved: dict[str, list] = {"parsed": [], "extraction": [], "fields": [], "findings": []}
        self._master = False
        self.prior_requests: list = []
        self.manifests: list = []
        self.meta: dict[UUID, tuple] = {}
        self.invoices: dict[UUID, NormalizedInvoice] = {}

    def register_file(self, file) -> bool:
        if file.sha256 in self.shas:
            return False
        self.shas.add(file.sha256)
        return True

    def create_document(self, record: DocumentRecord) -> None:
        self.documents[record.doc_id] = record
        self.statuses[record.doc_id] = record.status

    def get_document(self, doc_id):
        return self.documents.get(doc_id)

    def set_status(self, doc_id, status, reason) -> None:
        self.statuses[doc_id] = status

    def list_documents(self, statuses):
        return tuple(d for d in self.documents.values() if self.statuses.get(d.doc_id) in statuses)

    def save_parsed(self, document) -> None:
        self.saved["parsed"].append(document)

    def save_extraction(self, result) -> None:
        self.saved["extraction"].append(result)

    def save_fields(self, doc_id, fields, line_items) -> None:
        self.saved["fields"].append((doc_id, fields, line_items))

    def save_coding(self, doc_id, lines) -> None:
        self.coding[doc_id] = lines

    def save_findings(self, doc_id, run_id, findings) -> None:
        self.saved["findings"].append((doc_id, run_id, findings))

    def add_review(self, review) -> None:
        pass

    def master_loaded(self) -> bool:
        return self._master

    def save_master(self, master) -> None:
        self._master = True

    def load_master(self):
        return load_golden().master

    def prior_invoices(self, vendor_id):
        self.prior_requests.append(vendor_id)
        return ()

    def set_document_meta(self, doc_id, doc_type, vendor_id) -> None:
        self.meta[doc_id] = (doc_type, vendor_id)

    def stored_invoice(self, doc_id):
        return self.invoices.get(doc_id)

    def approved_not_exported(self):
        return tuple(
            doc_id
            for doc_id, status in self.statuses.items()
            if status in {DocStatus.APPROVED, DocStatus.AUTO_PASSED} and doc_id not in self.exported
        )

    def coding_lines(self, doc_id):
        return self.coding.get(doc_id, ())

    def record_export(self, batch, doc_ids, manifest=None) -> None:
        self.manifests.append(manifest)
        for doc_id in doc_ids:
            if doc_id in self.exported:
                raise ValueError(f"{doc_id} already exported")
            self.exported.add(doc_id)
            self.statuses[doc_id] = DocStatus.EXPORTED
        self.batches.append((batch, doc_ids))

    def log_event(self, actor, event_type, doc_id, payload) -> None:
        self.events.append((actor, event_type, doc_id, payload))


def _pipeline(golden) -> Pipeline:
    rules = load_config("rules")
    return Pipeline(
        deps=golden_deps(golden, auto_approve_clean=bool(rules["routing"]["auto_approve_clean"])),
        master=golden.master,
        rules_config=rules,
    )


def test_intake_runs_clean_fixture_to_silver(golden, clean, tmp_path):
    repo = FakeRepo()
    store = LocalBlobStore(tmp_path)
    result = intake_document(
        clean.pdf_path,
        repo=repo,
        store=store,
        pipeline=_pipeline(golden),
        today=TODAY,
        run_id="test-run",
    )

    assert result.skipped is False
    assert result.status is DocStatus.AUTO_PASSED
    assert result.sha256 == clean.sha256
    assert repo.statuses[result.doc_id] is DocStatus.AUTO_PASSED
    assert repo.saved["parsed"] and repo.saved["extraction"]
    assert repo.saved["fields"]
    assert repo.saved["findings"][0][2] == ()  # the clean fixture has no findings
    assert result.doc_id in repo.coding
    # Bronze + silver blobs exist on disk.
    assert store.read(f"bronze/{result.sha256[:2]}/{result.sha256}").startswith(b"%PDF")
    assert store.read(f"silver/{result.doc_id}/extraction.json").startswith(b"{")


def test_same_file_is_skipped_the_second_time(golden, clean, tmp_path):
    repo = FakeRepo()
    store = LocalBlobStore(tmp_path)
    kwargs = dict(repo=repo, store=store, pipeline=_pipeline(golden), today=TODAY, run_id="r")
    first = intake_document(clean.pdf_path, **kwargs)
    second = intake_document(clean.pdf_path, **kwargs)

    assert first.skipped is False
    assert second.skipped is True
    assert second.reason == "sha256 already ingested"


def test_intake_inbox_moves_processed_files(golden, clean, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target = inbox / "invoice.pdf"
    target.write_bytes(clean.pdf_path.read_bytes())

    repo = FakeRepo()
    store = LocalBlobStore(tmp_path / "data")
    results = intake_inbox(
        repo=repo, store=store, pipeline=_pipeline(golden), today=TODAY, run_id="r", inbox=inbox
    )

    assert len(results) == 1 and results[0].status is DocStatus.AUTO_PASSED
    assert list_inbox(inbox) == ()
    assert (tmp_path / "processed" / "invoice.pdf").is_file()


def _approved_doc(repo, *, net="1080.00", tax="97.20", total="1177.20", vendor_id="V001"):
    doc_id = uuid4()
    repo.documents[doc_id] = DocumentRecord(
        doc_id=doc_id, file_id=uuid4(), status=DocStatus.APPROVED, vendor_id=vendor_id
    )
    repo.statuses[doc_id] = DocStatus.APPROVED
    repo.invoices[doc_id] = NormalizedInvoice(
        invoice_number=f"INV-{doc_id.hex[:6]}",
        invoice_date=date(2026, 10, 15),
        currency="SGD",
        total=Decimal(total),
    )
    repo.coding[doc_id] = (
        CodingLine(
            line_no=1,
            gl_account="610200",
            cost_center="KG1100",
            tax_code="TX",
            net_amount=Decimal(net),
            tax_amount=Decimal(tax),
            coding_source=CodingSource.PO,
        ),
    )
    return doc_id


def test_export_twice_leaves_second_batch_empty(tmp_path):
    repo = FakeRepo()
    store = LocalBlobStore(tmp_path)
    doc_id = _approved_doc(repo)

    first = export_approved(repo=repo, store=store)
    second = export_approved(repo=repo, store=store)

    assert first.batch.row_count == 1
    assert first.doc_ids == (doc_id,)
    assert second.batch.row_count == 0
    assert second.doc_ids == ()
    assert repo.exported == {doc_id}


def test_export_writes_the_sap_layout_from_the_mapping(tmp_path):
    repo = FakeRepo()
    store = LocalBlobStore(tmp_path)
    doc_id = _approved_doc(repo)

    summary = export_approved(repo=repo, store=store)

    text = store.read(summary.batch.csv_path).decode("utf-8")
    header = text.splitlines()[0]
    assert header.startswith('"DocKey","CompanyCode","VendorNo"')
    assert '"GrossAmount"' in header
    assert str(doc_id) in text
    assert '"100014"' in text  # the vendor's SAP number from the master


def test_export_records_the_manifest_with_versions(tmp_path):
    repo = FakeRepo()
    store = LocalBlobStore(tmp_path)
    _approved_doc(repo)

    summary = export_approved(repo=repo, store=store)

    manifest = repo.manifests[0]
    assert manifest["csv_sha256"] == summary.batch.csv_sha256
    assert manifest["model"]
    assert store.read(f"gold/{summary.batch.batch_id}/{summary.batch.batch_id}.manifest.json")


def test_export_holds_back_only_the_document_that_fails_a_batch_check(tmp_path):
    repo = FakeRepo()
    store = LocalBlobStore(tmp_path)
    good = _approved_doc(repo)
    bad = _approved_doc(repo, total="1188.10")

    summary = export_approved(repo=repo, store=store)

    assert summary.doc_ids == (good,)
    assert any("expected gross" in problem for problem in summary.problems)
    assert repo.statuses[bad] is DocStatus.APPROVED


def test_export_holds_back_a_document_with_no_vendor(tmp_path):
    repo = FakeRepo()
    store = LocalBlobStore(tmp_path)
    _approved_doc(repo, vendor_id=None)

    summary = export_approved(repo=repo, store=store)

    assert summary.doc_ids == ()
    assert any("vendor" in problem for problem in summary.problems)


def test_intake_saves_type_and_vendor_and_passes_prior_invoices(golden, tmp_path):
    fixture = golden.fixtures[0]
    repo = FakeRepo()
    result = intake_document(
        fixture.pdf_path,
        repo=repo,
        store=LocalBlobStore(tmp_path),
        pipeline=_pipeline(golden),
        today=TODAY,
        run_id="r",
    )
    assert repo.prior_requests == [None]
    doc_type, vendor_id = repo.meta[result.doc_id]
    assert vendor_id == "V001"
    assert doc_type is not None
    assert result.process is not None


def test_a_byte_identical_file_is_logged_when_skipped(golden, tmp_path):
    fixture = golden.fixtures[0]
    repo = FakeRepo()
    kwargs = {
        "repo": repo,
        "store": LocalBlobStore(tmp_path),
        "pipeline": _pipeline(golden),
        "today": TODAY,
        "run_id": "r",
    }
    intake_document(fixture.pdf_path, **kwargs)
    second = intake_document(fixture.pdf_path, **kwargs)
    assert second.skipped
    assert any(event[1] == "intake.duplicate_file" for event in repo.events)


def test_build_pipeline_prefers_the_generated_master(tmp_path, monkeypatch, golden):
    monkeypatch.setenv("INVOICEFLOW_DATA", str(tmp_path))
    assert len(build_pipeline().master.vendors) == len(golden.master.vendors)

    generated = golden.master.model_copy(
        update={"vendors": (*golden.master.vendors, golden.master.vendors[0])}
    )
    target = tmp_path / "generated" / "master.json"
    target.parent.mkdir()
    target.write_text(generated.model_dump_json(), encoding="utf-8")
    assert len(build_pipeline().master.vendors) == len(golden.master.vendors) + 1


def test_guess_mime():
    assert guess_mime("invoice.pdf") == "application/pdf"
    assert guess_mime("page-1.png") == "image/png"
    assert guess_mime("unknown.xyz") is None


def test_list_inbox_missing_dir_returns_empty(tmp_path):
    assert list_inbox(tmp_path / "nope") == ()
