"""Layer 3 on screen: values the system changed on its own are highlighted above the table."""

from __future__ import annotations

from dataclasses import replace

from test_pages import _run
from test_story import _advance

from app.cleanup import cleanup_box_html, cleanups, highlight_cleaned
from app.pages import review, story


def _spaced(bundle):
    fields = tuple(
        replace(field, value_raw=field.value_norm.replace("-", "- ", 1))
        if field.name == "invoice_number"
        else field
        for field in bundle.fields
    )
    return replace(bundle, fields=fields)


def _markdown(at) -> list[str]:
    return [item.value for item in at.markdown]


def test_a_cleaned_invoice_number_is_listed(mismatch_bundle):
    bundle = _spaced(mismatch_bundle)
    number = bundle.field("invoice_number").value_norm
    (change,) = cleanups(bundle.fields)
    assert change.field == "invoice_number"
    assert change.label == "Invoice number"
    assert change.printed == number.replace("-", "- ", 1)
    assert change.stored == number
    assert "hyphen" in change.reason


def test_nothing_is_listed_when_nothing_was_cleaned(mismatch_bundle):
    # Dates and amounts always change form by design, so they are never listed.
    assert cleanups(mismatch_bundle.fields) == ()
    assert cleanup_box_html(()) == ""


def test_the_box_says_who_changed_what_and_why_in_plain_words(mismatch_bundle):
    html = cleanup_box_html(cleanups(_spaced(mismatch_bundle).fields))
    assert 'data-cleanups="1"' in html
    assert "Changed automatically by the system" in html
    assert "not by a person" in html
    assert "Read on the invoice" in html and "Stored as" in html
    assert "letters and digits" in html


def test_the_box_escapes_what_ocr_read():
    from app.cleanup import Cleanup

    html = cleanup_box_html((Cleanup("invoice_number", "Invoice number", "<b>X</b>", "X", "r"),))
    assert "<b>X</b>" not in html and "&lt;b&gt;X&lt;/b&gt;" in html


def test_the_changed_row_is_highlighted(mismatch_bundle):
    import pandas as pd

    frame = pd.DataFrame([{"field": "invoice_number"}, {"field": "total"}])
    styles = highlight_cleaned(frame, {"invoice_number"})._compute().ctx
    assert any("background-color" in str(style) for (row, _), style in styles.items() if row == 0)
    assert not any(row == 1 for (row, _) in styles)


def test_the_demo_step_shows_the_box_above_the_table(fake_backend, mismatch_bundle):
    spaced = _spaced(mismatch_bundle)
    fake_backend.bundles[spaced.document.doc_id] = spaced
    at = _run(story, fake_backend)
    _advance(at, 3)  # Step 4: "How does the system turn printing into numbers?"
    boxes = [text for text in _markdown(at) if "data-cleanups" in text]
    assert boxes
    # In the column that holds the values table, the box comes first.
    (column,) = [column for column in at.columns if column.dataframe]
    order = [node.type for node in column.children.values()]
    box = next(
        i
        for i, node in enumerate(column.children.values())
        if node.type == "markdown" and "data-cleanups" in node.value
    )
    assert box < order.index("dataframe")


def test_the_review_page_shows_the_box(fake_backend, mismatch_bundle):
    spaced = _spaced(mismatch_bundle)
    fake_backend.bundles[spaced.document.doc_id] = spaced
    at = _run(review, fake_backend)
    at.selectbox(key="review_document").set_value(spaced.document.doc_id).run(timeout=30)
    assert [text for text in _markdown(at) if "data-cleanups" in text]
