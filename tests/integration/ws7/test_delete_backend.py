"""The Queue's Delete against the fixture database: the backend deletes, logs and says so."""

from __future__ import annotations

import pytest

from app import repo
from app.backend import PostgresBackend
from invoiceflow.contracts import DocStatus

pytestmark = pytest.mark.db


@pytest.fixture()
def deleting(conn, loaded, tmp_path):
    # Files go from a scratch folder, never from the repo's data/.
    return PostgresBackend(conn, files_root=tmp_path, cache_dir=tmp_path / "llm_cache")


def test_delete_removes_the_document_and_names_it(deleting, docs):
    doc = docs["SAV-2026-0412"]
    outcome = deleting.delete_documents((doc.doc_id,), "integration.reviewer")
    assert outcome.deleted == ("SAV-2026-0412",)
    assert outcome.exported == 0
    assert outcome.message == "Deleted SAV-2026-0412."
    assert deleting.document(doc.doc_id) is None
    assert "SAV-2026-0413" in {d.invoice_number for d in deleting.list_documents()}


def test_deleting_an_exported_invoice_says_sap_still_has_it(conn, deleting, docs):
    doc = docs["SAV-2026-0412"]
    repo.set_status(conn, doc.doc_id, DocStatus.EXPORTED, "exported")
    outcome = deleting.delete_documents((doc.doc_id,), "integration.reviewer")
    assert outcome.exported == 1
    assert outcome.warn
    assert "SAP still has it" in outcome.message


def test_a_document_still_being_read_is_not_deleted(conn, deleting, docs):
    doc = docs["SAV-2026-0412"]
    repo.set_status(conn, doc.doc_id, DocStatus.RECEIVED, "reading")
    with pytest.raises(ValueError, match="still being read"):
        deleting.delete_documents((doc.doc_id,), "integration.reviewer")
    assert deleting.document(doc.doc_id) is not None


def test_deleting_what_is_already_gone_says_so(deleting, docs):
    doc = docs["SAV-2026-0412"]
    deleting.delete_documents((doc.doc_id,), "integration.reviewer")
    with pytest.raises(LookupError, match="already gone"):
        deleting.delete_documents((doc.doc_id,), "integration.reviewer")
