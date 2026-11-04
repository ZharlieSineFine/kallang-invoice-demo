from invoiceflow.contracts import InvoiceExtraction
from invoiceflow.extract import extract_json_object, validate_output


def test_extract_json_object_plain():
    assert extract_json_object('{"a": 1}') == '{"a": 1}'


def test_extract_json_object_fenced():
    assert extract_json_object('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_object_prose():
    raw = 'The result is {"title": "TAX INVOICE"} — thanks!'
    assert extract_json_object(raw) == '{"title": "TAX INVOICE"}'


def test_extract_json_object_returns_input_when_no_object():
    assert extract_json_object("no json here") == "no json here"


def test_validate_output_valid():
    extraction, error = validate_output(
        '{"title": "TAX INVOICE", "invoice_number": "SAV-2026-0412"}'
    )
    assert error is None
    assert isinstance(extraction, InvoiceExtraction)
    assert extraction.invoice_number == "SAV-2026-0412"


def test_validate_output_line_items():
    extraction, error = validate_output('{"line_items": [{"line_no": "1", "amount": "540.00"}]}')
    assert error is None
    assert extraction.line_items[0].amount == "540.00"


def test_validate_output_invalid_json():
    extraction, error = validate_output("not json at all")
    assert extraction is None
    assert error


def test_validate_output_wrong_type():
    extraction, error = validate_output('{"invoice_number": 123}')
    assert extraction is None
    assert "invoice_number" in error


def test_validate_output_document_type_enum():
    extraction, error = validate_output('{"document_type": "TAX_INVOICE"}')
    assert error is None
    assert extraction.document_type.value == "TAX_INVOICE"

    extraction, error = validate_output('{"document_type": "BOGUS_TYPE"}')
    assert extraction is None
    assert "document_type" in error
