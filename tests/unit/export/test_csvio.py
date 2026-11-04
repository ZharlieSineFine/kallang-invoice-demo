"""CSV writer tests: quoting, formula-injection guard, and free-text targeting."""

from datetime import date

from invoiceflow.export.csvio import guard_free_text, neutralize_formula, to_csv
from invoiceflow.export.mapping import RowContext, map_row

EXPORT_DATE = date(2026, 11, 4)


def _row(mapping, clean_doc, **overrides):
    values = dict(
        doc_id=clean_doc.doc_id,
        vendor=clean_doc.vendor,
        invoice=clean_doc.invoice,
        coding_line=clean_doc.coding_lines[0],
        export_date=EXPORT_DATE,
    )
    values.update(overrides)
    return map_row(mapping, RowContext(**values))


def test_neutralize_formula_prefixes_dangerous_start():
    assert neutralize_formula("=SUM(A1)") == "'=SUM(A1)"
    assert neutralize_formula("+cmd") == "'+cmd"
    assert neutralize_formula("-1+2") == "'-1+2"
    assert neutralize_formula("@import") == "'@import"


def test_neutralize_formula_leaves_plain_text_alone():
    assert neutralize_formula("Equipment rental") == "Equipment rental"
    assert neutralize_formula("") == ""


def test_to_csv_writes_header_and_quotes_every_cell(mapping, clean_doc):
    csv_text = to_csv(mapping, (_row(mapping, clean_doc),))
    lines = csv_text.split("\r\n")
    assert lines[0] == ",".join(f'"{name}"' for name in mapping.header)
    assert lines[1] == (
        '"93fe9312-fe79-50bb-b5e7-d18e83dfaff2","KG01","100014","15.10.2026",'
        '"04.11.2026","SAV-2026-0412","SGD","1177.20","1","610200","KG1100",'
        '"1080.00","TX","97.20","4500012345","Equipment rental, PO 4500012345"'
    )


def test_guard_free_text_only_touches_free_text_columns(mapping, clean_doc):
    row = list(_row(mapping, clean_doc))
    line_text_idx = [c.name for c in mapping.columns].index("LineText")
    row[line_text_idx] = "=1+2"
    guarded = guard_free_text(mapping, tuple(row))
    assert guarded[line_text_idx] == "'=1+2"
    reference_idx = [c.name for c in mapping.columns].index("Reference")
    assert guarded[reference_idx] == "SAV-2026-0412"
