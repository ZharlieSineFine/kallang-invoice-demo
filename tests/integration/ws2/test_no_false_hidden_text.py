"""False-alarm test: on the 57 demo invoices the OCR comparison hides nothing a person can
read. Only SHC-2026-7004's planted instruction is hidden, and the trick checks already
catch it."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from invoiceflow.parse import DocumentParser, ParseConfig
from invoiceflow.settings import repo_root

GENERATED = repo_root() / "data" / "generated"
INVOICES = sorted((GENERATED / "invoices").glob("*.pdf"))


def _hidden(path: Path, config: ParseConfig, root: Path) -> list[str]:
    parser = DocumentParser(config=config, image_root=root)
    document = parser.parse(path, file_id=uuid4(), doc_id=uuid4())
    return [word.text for _, word in document.hidden_words]


def test_all_57_demo_invoices_are_there():
    assert len(INVOICES) == 57


@pytest.mark.parametrize("path", INVOICES, ids=lambda path: path.name)
def test_the_comparison_adds_no_hidden_words(path, tmp_path):
    with_ocr = _hidden(path, ParseConfig.from_repo(), tmp_path)
    tricks_only = _hidden(
        path, replace(ParseConfig.from_repo(), hidden_ocr_compare=False), tmp_path
    )
    assert with_ocr == tricks_only
