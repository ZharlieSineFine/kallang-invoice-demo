"""Which files count as the live-demo set: the manifest's, or every PDF in a folder."""

from __future__ import annotations

import json
from hashlib import sha256

from invoiceflow.store.erase import EraseTarget, target_from_folder


def test_a_folder_with_a_manifest_gives_files_and_invoice_numbers(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"documents": [{"sha256": "a" * 64, "invoice_number": "CAM-2026-9601"}]}),
        encoding="utf-8",
    )
    assert target_from_folder(tmp_path) == EraseTarget(
        sha256s=frozenset({"a" * 64}), invoice_numbers=frozenset({"CAM-2026-9601"})
    )


def test_a_folder_without_one_gives_every_pdf_by_content(tmp_path):
    (tmp_path / "one.pdf").write_bytes(b"%PDF one")
    (tmp_path / "notes.txt").write_text("not a pdf")
    assert target_from_folder(tmp_path) == EraseTarget(
        sha256s=frozenset({sha256(b"%PDF one").hexdigest()})
    )
