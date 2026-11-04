"""The fixture loader's report rendering (no database needed)."""

from uuid import uuid4

from invoiceflow.store.fixtures import LoadedDocument, LoadReport


def test_load_report_render():
    report = LoadReport(
        (LoadedDocument("golden-a-clean", uuid4(), "SAV-2026-0412", "AUTO_PASSED"),)
    )
    text = report.render()
    assert "golden-a-clean" in text
    assert "AUTO_PASSED" in text
    assert "SAV-2026-0412" in text


def test_empty_report_render():
    assert LoadReport(()).render() == "0 document(s) loaded:"
