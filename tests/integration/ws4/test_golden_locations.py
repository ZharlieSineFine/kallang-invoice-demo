"""WS4 acceptance against the golden digital PDFs.

The golden pages ship the words pdfplumber read and the expected FieldLocation boxes, so the
locator can be scored without waiting for WS1/WS2 to generate more documents. The target is
98% of truth fields found; on the two golden invoices every expected box is reproduced exactly.
"""

from invoiceflow.contracts import FileKind, MatchType, ParsedDocument
from invoiceflow.locate import Locator
from invoiceflow.pipeline.golden import load_golden


def _document(fixture) -> ParsedDocument:
    return ParsedDocument(
        doc_id=fixture.doc_id,
        file_id=fixture.file_id,
        file_kind=FileKind.PDF,
        pages=(fixture.page,),
    )


def test_golden_locations_are_found():
    golden = load_golden()
    total = 0
    found = 0

    for fixture in golden.fixtures:
        actual = {
            loc.field: loc for loc in Locator().locate(_document(fixture), fixture.truth.printed)
        }
        for expected in fixture.locations:
            total += 1
            location = actual.get(expected.field)
            assert location is not None, expected.field
            assert location.match_type is MatchType.EXACT, expected.field
            assert location.page_no == expected.page_no, expected.field
            assert location.bbox == expected.bbox, expected.field
            assert location.matched_text == expected.matched_text, expected.field
            assert location.score == expected.score, expected.field
            found += 1

    assert total > 0
    assert found / total >= 0.98


def test_every_extracted_golden_value_is_located():
    golden = load_golden()

    for fixture in golden.fixtures:
        actual = {
            loc.field: loc for loc in Locator().locate(_document(fixture), fixture.truth.printed)
        }
        for expected in fixture.locations:
            assert actual[expected.field].bbox is not None, expected.field
