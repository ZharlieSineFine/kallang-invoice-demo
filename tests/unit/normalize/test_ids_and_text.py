import pytest

from invoiceflow.normalize import clean_text, normalize_id, normalize_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("M2-1234567-8", "M212345678"),
        ("m2 1234567 8", "M212345678"),
        ("  abc-123  ", "ABC123"),
        ("SAV\u20132026\u20130412", "SAV20260412"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_id_removes_spaces_and_hyphens_and_uppercases(raw, expected):
    assert normalize_id(raw) == expected


def test_normalize_text_applies_nfkc_and_casefold():
    fullwidth = "\uff33\uff34\uff21\uff27\uff25\uff23\uff32\uff21\uff26\uff34"
    assert normalize_text(f"  {fullwidth}\u200b   AV  ") == "stagecraft av"
    assert normalize_text("\ufeffInvoice\u00a0No:") == "invoice no:"


def test_zero_width_characters_are_removed_from_ids():
    assert normalize_id("M2\u200b-1234567-8") == "M212345678"


def test_clean_text_preserves_case_but_collapses_whitespace():
    assert clean_text("Stagecraft\u200d   AV\tRentals") == "Stagecraft AV Rentals"
    assert clean_text(None) is None
