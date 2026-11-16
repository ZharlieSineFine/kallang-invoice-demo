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


# ---- invoice numbers: layer 1 (cleanup) and layer 2 (comparison key) ----------------------

from invoiceflow.normalize.text import clean_reference, invoice_number_key  # noqa: E402


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GSH- 2026-9004", "GSH-2026-9004"),  # the OCR slip seen on the live-demo scan
        ("GSH -2026 - 9004", "GSH-2026-9004"),
        ("INV / 2026 / 01", "INV/2026/01"),
        ("SAV \N{EN DASH} 2026", "SAV\N{EN DASH}2026"),  # the dash stays, the spaces go
        ("  GSH-2026-9004  ", "GSH-2026-9004"),
        ("INV 2026 01", "INV 2026 01"),  # a space between letters or digits may be meant
        ("gsh-2026-9004", "gsh-2026-9004"),  # case is kept: the stored value is what was printed
    ],
)
def test_clean_reference_removes_spaces_around_separators_only(raw, expected):
    assert clean_reference(raw) == expected


def test_clean_reference_keeps_empty_values_empty():
    assert clean_reference(None) is None
    assert clean_reference("   ") is None


@pytest.mark.parametrize(
    "variant",
    ["GSH-2026-9004", "GSH- 2026-9004", "gsh 2026 9004", "GSH/2026/9004", "GSH\N{EN DASH}20269004"],
)
def test_invoice_number_key_ignores_spacing_punctuation_and_case(variant):
    assert invoice_number_key(variant) == "GSH20269004"


def test_invoice_number_key_keeps_real_character_differences():
    # O and 0 can change meaning, so they are not treated as the same.
    assert invoice_number_key("GSH-2026-9OO4") != invoice_number_key("GSH-2026-9004")
    assert invoice_number_key(None) == ""


def test_reference_cleanup_reports_only_a_real_change():
    from invoiceflow.normalize.text import reference_cleanup

    assert reference_cleanup("GSH- 2026-9004") == ("GSH- 2026-9004", "GSH-2026-9004")
    assert reference_cleanup("GSH-2026-9004") is None
    assert reference_cleanup("  GSH-2026-9004 ") is None  # trimming is not worth a note
    assert reference_cleanup(None) is None
