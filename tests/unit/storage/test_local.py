"""LocalBlobStore: content addressing, write-once bronze, scoped silver/gold paths."""

import hashlib
from uuid import uuid4

from invoiceflow.storage import LocalBlobStore, gold_rel_path, silver_rel_path, words_rel_path


def test_bronze_is_content_addressed(tmp_path):
    store = LocalBlobStore(tmp_path)
    data = b"%PDF-1.7 synthetic invoice"
    sha = hashlib.sha256(data).hexdigest()

    digest, rel = store.put_bronze(data, "invoice.pdf")

    assert digest == sha
    assert rel == f"bronze/{sha[:2]}/{sha}"
    assert (tmp_path / rel).read_bytes() == data
    assert store.read(rel) == data


def test_same_bytes_same_path_no_overwrite(tmp_path):
    store = LocalBlobStore(tmp_path)
    data = b"same content"

    first = store.put_bronze(data, "a.pdf")
    second = store.put_bronze(data, "b.pdf")

    assert first == second
    # The path exists once; calling again does not raise or duplicate.
    assert store.read(first[1]) == data


def test_bronze_never_overwrites_existing_file(tmp_path):
    store = LocalBlobStore(tmp_path)
    data = b"original bytes"
    _digest, rel = store.put_bronze(data, "invoice.pdf")
    target = tmp_path / rel

    original_mtime = target.stat().st_mtime_ns
    store.put_bronze(data, "again.pdf")
    assert target.stat().st_mtime_ns == original_mtime


def test_silver_and_gold_paths(tmp_path):
    store = LocalBlobStore(tmp_path)
    doc_id = uuid4()

    words = store.put_silver(doc_id, "page-1.words.json", b'{"words": []}')
    extraction = store.put_silver(doc_id, "extraction.json", b'{"valid": true}')
    csv = store.put_gold("export-1", "export-1.csv", b"a,b\n1,2\n")

    assert store.read(words) == b'{"words": []}'
    assert store.read(extraction) == b'{"valid": true}'
    assert store.read(csv) == b"a,b\n1,2\n"
    assert words == f"silver/{doc_id}/page-1.words.json"
    assert csv == "gold/export-1/export-1.csv"


def test_path_helpers():
    doc_id = uuid4()
    assert words_rel_path(doc_id, 1) == f"silver/{doc_id}/page-1.words.json"
    assert silver_rel_path(doc_id, "x.json") == f"silver/{doc_id}/x.json"
    assert gold_rel_path("b1", "b1.csv") == "gold/b1/b1.csv"
