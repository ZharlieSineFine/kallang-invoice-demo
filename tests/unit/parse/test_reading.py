from __future__ import annotations

from invoiceflow.contracts import BBox, Word
from invoiceflow.parse.reading import reading_order_text


def _word(text: str, x0: float, y0: float, x1: float, y1: float, *, hidden=False) -> Word:
    return Word(text=text, bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1), hidden=hidden)


def test_words_are_grouped_into_lines_and_sorted_left_to_right():
    words = (
        _word("world", 0.30, 0.100, 0.40, 0.120),
        _word("hello", 0.10, 0.101, 0.20, 0.121),
        _word("second", 0.10, 0.200, 0.20, 0.220),
    )
    assert reading_order_text(words) == "hello world\nsecond"


def test_hidden_words_are_left_out():
    words = (
        _word("visible", 0.10, 0.10, 0.20, 0.12),
        _word("secret", 0.21, 0.10, 0.30, 0.12, hidden=True),
    )
    assert reading_order_text(words) == "visible"


def test_empty_page_is_an_empty_string():
    assert reading_order_text(()) == ""


def test_tall_words_do_not_merge_separate_lines():
    words = (
        _word("heading", 0.10, 0.10, 0.30, 0.14),
        _word("body", 0.10, 0.20, 0.20, 0.22),
        _word("text", 0.21, 0.20, 0.30, 0.22),
    )
    assert reading_order_text(words) == "heading\nbody text"
