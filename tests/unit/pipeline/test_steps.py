"""Step functions: intake (inbox -> bronze -> silver) and the export-once loop."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from invoiceflow.contracts import CodingLine, CodingSource, DocStatus, DocumentRecord
from invoiceflow.pipeline.steps import (
    Pipeline,
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
        raise NotImplementedError

    def prior_invoices(self, vendor_id):
        return ()

    def approved_not_exported(self):
        return tuple(
            doc_id
            for doc_id, status in self.statuses.items()
            if status is DocStatus.APPROVED and doc_id not in self.exported
        )

    def coding_lines(self, doc_id):
        return self.coding.get(doc_id, ())

    def record_export(self, batch, doc_ids) -> None:
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


def test_export_twice_leaves_second_batch_empty(tmp_path):
    repo = FakeRepo()
    store = LocalBlobStore(tmp_path)
    doc_id = uuid4()
    repo.documents[doc_id] = DocumentRecord(
        doc_id=doc_id, file_id=uuid4(), status=DocStatus.APPROVED
    )
    repo.statuses[doc_id] = DocStatus.APPROVED
    repo.coding[doc_id] = (
        CodingLine(
            line_no=1,
            gl_account="610200",
            cost_center="KG1100",
            tax_code="TX",
            net_amount=Decimal("1080.00"),
            tax_amount=Decimal("97.20"),
            coding_source=CodingSource.PO,
        ),
    )

    first = export_approved(repo=repo, store=store)
    second = export_approved(repo=repo, store=store)

    assert first.batch.row_count == 1
    assert first.doc_ids == (doc_id,)
    assert second.batch.row_count == 0
    assert second.doc_ids == ()
    assert repo.exported == {doc_id}
    assert store.read(first.batch.csv_path).startswith(b"doc_id,line_no")


def test_guess_mime():
    assert guess_mime("invoice.pdf") == "application/pdf"
    assert guess_mime("page-1.png") == "image/png"
    assert guess_mime("unknown.xyz") is None


def test_list_inbox_missing_dir_returns_empty(tmp_path):
    assert list_inbox(tmp_path / "nope") == ()
