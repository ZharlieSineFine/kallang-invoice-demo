from uuid import UUID

from invoiceflow.contracts import (
    BBox,
    FileKind,
    InvoiceExtraction,
    MatchType,
    PageText,
    ParsedDocument,
    TextSource,
    Word,
)
from invoiceflow.locate import Locator

DOC_ID = UUID("00000000-0000-0000-0000-000000000001")
FILE_ID = UUID("00000000-0000-0000-0000-000000000002")


def word(text: str, x0: float, y0: float, x1: float, y1: float, *, hidden=False) -> Word:
    return Word(text=text, bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1), hidden=hidden)


def document(words: tuple[Word, ...]) -> ParsedDocument:
    return ParsedDocument(
        doc_id=DOC_ID,
        file_id=FILE_ID,
        file_kind=FileKind.PDF,
        pages=(
            PageText(
                page_no=1,
                width_pt=595.0,
                height_pt=842.0,
                source=TextSource.PDF_TEXT,
                words=words,
            ),
        ),
    )


def locate_words(words: tuple[Word, ...], **fields):
    extraction = InvoiceExtraction(**fields)
    return {loc.field: loc for loc in Locator().locate(document(words), extraction)}


def test_locator_implements_the_protocol():
    from invoiceflow.contracts import Locator as LocatorProtocol

    assert isinstance(Locator(), LocatorProtocol)


def test_exact_match():
    words = (
        word("Invoice", 0.10, 0.10, 0.16, 0.11),
        word("No:", 0.17, 0.10, 0.20, 0.11),
        word("SAV-2026-0412", 0.21, 0.10, 0.34, 0.11),
    )

    found = locate_words(words, invoice_number="SAV-2026-0412")["invoice_number"]

    assert found.match_type is MatchType.EXACT
    assert found.score == 100.0
    assert found.page_no == 1
    assert found.matched_text == "SAV-2026-0412"
    assert found.bbox == BBox(x0=0.21, y0=0.10, x1=0.34, y1=0.11)


def test_equal_number_beats_no_match():
    words = (
        word("Total", 0.10, 0.10, 0.16, 0.11),
        word("1,090.00", 0.50, 0.10, 0.60, 0.11),
    )

    found = locate_words(words, total="1090")["total"]

    assert found.match_type is MatchType.NUMERIC
    assert found.score == 100.0
    assert found.bbox == BBox(x0=0.50, y0=0.10, x1=0.60, y1=0.11)


def test_equal_percentage_is_a_numeric_match():
    words = (
        word("GST", 0.10, 0.10, 0.16, 0.11),
        word("9%", 0.50, 0.10, 0.56, 0.11),
    )

    found = locate_words(words, gst_rate="9")["gst_rate"]

    assert found.match_type is MatchType.NUMERIC
    assert found.bbox == BBox(x0=0.50, y0=0.10, x1=0.56, y1=0.11)


def test_fuzzy_match_at_or_above_ninety():
    words = (
        word("Venue:", 0.10, 0.10, 0.16, 0.11),
        word("National", 0.20, 0.10, 0.27, 0.11),
        word("Stadum", 0.28, 0.10, 0.35, 0.11),
    )

    found = locate_words(words, venue="National Stadium")["venue"]

    assert found.match_type is MatchType.FUZZY
    assert 90.0 <= found.score < 100.0


def test_hidden_words_are_skipped():
    words = (
        word("1,090.00", 0.10, 0.10, 0.20, 0.11, hidden=True),
        word("Total", 0.40, 0.10, 0.46, 0.11),
        word("1,090.00", 0.50, 0.10, 0.60, 0.11),
    )

    found = locate_words(words, total="1,090.00")["total"]

    assert found.match_type is MatchType.EXACT
    assert found.bbox == BBox(x0=0.50, y0=0.10, x1=0.60, y1=0.11)


def test_value_that_only_exists_as_hidden_text_is_not_found():
    words = (word("1,090.00", 0.10, 0.10, 0.20, 0.11, hidden=True),)

    found = locate_words(words, total="1,090.00")["total"]

    assert found.match_type is MatchType.NONE
    assert found.bbox is None
    assert found.page_no is None


def test_duplicate_value_prefers_the_match_next_to_its_label():
    words = (
        word("Total", 0.10, 0.10, 0.15, 0.11),
        word("1,090.00", 0.50, 0.10, 0.60, 0.11),
        word("Total", 0.10, 0.20, 0.15, 0.21),
        word("Payable", 0.16, 0.20, 0.22, 0.21),
        word("1,090.00", 0.50, 0.20, 0.60, 0.21),
    )

    found = locate_words(words, subtotal="1,090.00", total="1,090.00")

    assert found["subtotal"].bbox == BBox(x0=0.50, y0=0.10, x1=0.60, y1=0.11)
    assert found["total"].bbox == BBox(x0=0.50, y0=0.20, x1=0.60, y1=0.21)


def test_duplicate_id_prefers_its_own_label():
    words = (
        word("UEN:", 0.10, 0.10, 0.14, 0.11),
        word("209900123K", 0.15, 0.10, 0.24, 0.11),
        word("GST", 0.30, 0.10, 0.33, 0.11),
        word("Reg", 0.34, 0.10, 0.37, 0.11),
        word("No:", 0.38, 0.10, 0.41, 0.11),
        word("209900123K", 0.42, 0.10, 0.51, 0.11),
    )

    found = locate_words(
        words,
        supplier_uen="209900123K",
        supplier_gst_reg_no="209900123K",
    )

    assert found["supplier_uen"].bbox == BBox(x0=0.15, y0=0.10, x1=0.24, y1=0.11)
    assert found["supplier_gst_reg_no"].bbox == BBox(x0=0.42, y0=0.10, x1=0.51, y1=0.11)


def test_address_can_span_three_lines():
    words = (
        word("18", 0.10, 0.10, 0.12, 0.11),
        word("Fictional", 0.13, 0.10, 0.19, 0.11),
        word("Lane", 0.20, 0.10, 0.24, 0.11),
        word("#04-12,", 0.10, 0.12, 0.16, 0.13),
        word("Singapore", 0.17, 0.12, 0.24, 0.13),
        word("399999", 0.10, 0.14, 0.18, 0.15),
    )

    found = locate_words(words, supplier_address="18 Fictional Lane #04-12, Singapore 399999")[
        "supplier_address"
    ]

    assert found.match_type is MatchType.EXACT
    assert found.bbox == BBox(x0=0.10, y0=0.10, x1=0.24, y1=0.15)


def test_a_value_spanning_four_lines_is_not_matched():
    words = (
        word("one", 0.10, 0.10, 0.13, 0.11),
        word("two", 0.10, 0.12, 0.13, 0.13),
        word("three", 0.10, 0.14, 0.16, 0.15),
        word("four", 0.10, 0.16, 0.15, 0.17),
    )

    found = locate_words(words, supplier_address="one two three four")["supplier_address"]

    assert found.match_type is MatchType.NONE


def test_line_item_amount_uses_the_description_row_and_rightmost_column():
    words = (
        word("Description", 0.10, 0.20, 0.18, 0.21),
        word("Amount", 0.70, 0.20, 0.77, 0.21),
        word("LED", 0.10, 0.30, 0.13, 0.31),
        word("wall", 0.14, 0.30, 0.17, 0.31),
        word("rental", 0.18, 0.30, 0.23, 0.31),
        word("80.00", 0.50, 0.30, 0.56, 0.31),
        word("80.00", 0.70, 0.30, 0.76, 0.31),
        word("80.00", 0.90, 0.40, 0.96, 0.41),
    )
    extraction = InvoiceExtraction(
        line_items=(
            {
                "line_no": "1",
                "description": "LED wall rental",
                "amount": "80.00",
            },
        )
    )

    locations = {loc.field: loc for loc in Locator().locate(document(words), extraction)}

    assert locations["line_items[0].description"].bbox == BBox(x0=0.10, y0=0.30, x1=0.23, y1=0.31)
    assert locations["line_items[0].amount"].bbox == BBox(x0=0.70, y0=0.30, x1=0.76, y1=0.31)


def test_missing_value_returns_a_none_location():
    found = locate_words((word("Something", 0.10, 0.10, 0.18, 0.11),), total="1,090.00")

    assert found["total"].match_type is MatchType.NONE
    assert found["total"].matched_text is None
    assert found["total"].score == 0.0


def test_blank_extraction_fields_are_reported_as_none_locations():
    found = locate_words((word("Something", 0.10, 0.10, 0.18, 0.11),))

    assert found["invoice_number"].match_type is MatchType.NONE
    assert found["supplier_name"].match_type is MatchType.NONE


def test_a_longer_run_does_not_beat_the_exact_word():
    words = (
        word("Total", 0.10, 0.10, 0.15, 0.11),
        word("1,090.00", 0.50, 0.10, 0.60, 0.11),
    )

    found = locate_words(words, total="1,090.00")["total"]

    assert found.bbox == BBox(x0=0.50, y0=0.10, x1=0.60, y1=0.11)


def test_words_on_a_tilted_scan_line_are_read_left_to_right():
    # From pre-c-05: on a slightly tilted scan, words on one line sit at slightly different
    # heights, and the right-hand column's words fall between them.
    words = (
        word("The", 0.079, 0.1890, 0.105, 0.1975),
        word("INVOICE", 0.560, 0.1880, 0.620, 0.1965),
        word("Kallang", 0.110, 0.1895, 0.162, 0.1980),
        word("DATE", 0.625, 0.1885, 0.660, 0.1970),
        word("Group", 0.168, 0.1885, 0.212, 0.1970),
        word("20/10/2026", 0.700, 0.1890, 0.790, 0.1975),
    )
    location = locate_words(words, buyer_name="The Kallang Group")["buyer_name"]
    assert location.match_type is MatchType.EXACT
    assert location.matched_text == "The Kallang Group"
