from __future__ import annotations

import pytest

from invoiceflow.parse import DocumentParser, ParseConfig


@pytest.fixture()
def parser(tmp_path) -> DocumentParser:
    return DocumentParser(config=ParseConfig(), image_root=tmp_path / "pages")


@pytest.fixture(scope="session")
def golden_clean():
    from invoiceflow.pipeline.golden import load_golden

    return load_golden().fixtures[0]
