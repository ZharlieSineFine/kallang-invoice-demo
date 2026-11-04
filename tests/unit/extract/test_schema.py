import json

from invoiceflow.extract import extraction_schema, inline_schema, output_schema, schema_name


def test_schema_name():
    assert schema_name() == "invoice_extraction"


def test_extraction_schema_has_defs_and_line_items():
    schema = extraction_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "$defs" in schema
    assert "line_items" in schema["properties"]
    assert "document_type" in schema["properties"]


def test_inline_schema_removes_refs_and_defs():
    inlined = inline_schema(extraction_schema())
    serialized = json.dumps(inlined)
    assert "$defs" not in inlined
    assert "definitions" not in inlined
    assert "$ref" not in serialized
    # line_items items are now inline objects
    assert inlined["properties"]["line_items"]["items"]["type"] == "object"
    # document_type enum is inlined into the anyOf
    doc_type = inlined["properties"]["document_type"]["anyOf"][0]
    assert doc_type["type"] == "string"
    assert set(doc_type["enum"]) >= {"TAX_INVOICE", "CREDIT_NOTE"}


def test_output_schema_requires_every_field():
    schema = output_schema()
    assert set(schema["required"]) == set(schema["properties"].keys())
    assert "invoice_number" in schema["required"]
    assert "line_items" in schema["required"]


def test_inline_schema_does_not_mutate_input():
    schema = extraction_schema()
    inline_schema(schema)
    assert "$defs" in schema
    assert "$ref" in json.dumps(schema)
