from __future__ import annotations

import pytest

from invoiceflow.parse.config import ParseConfig
from invoiceflow.parse.hidden import (
    char_is_hidden,
    is_near_white,
    is_off_page,
    normalize_box,
    raw_word_is_hidden,
    word_from_pdfplumber,
)

PAGE = (0.0, 0.0, 612.0, 792.0)
CONFIG = ParseConfig()


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ((1.0, 1.0, 1.0), True),
        ((0.96, 0.96, 0.96), True),
        ((1.0, 1.0, 0.94), False),
        ((0.5, 0.5, 0.5), False),
        ((255, 255, 255), True),
        (1.0, True),
        (0.0, False),
        ((0.0, 0.0, 0.0, 0.0), True),
        ((0.0, 0.0, 0.0, 0.5), False),
        ("white", True),
        ("BLACK", False),
        ("not-a-colour", False),
        (None, False),
        ((), False),
        (object(), False),
        (("bad",), False),
    ],
)
def test_near_white_colours(color, expected):
    assert is_near_white(color, 0.95) is expected


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        ((-10.0, 100.0, -1.0, 110.0), True),
        ((620.0, 100.0, 700.0, 110.0), True),
        ((100.0, -10.0, 110.0, -1.0), True),
        ((100.0, 800.0, 110.0, 900.0), True),
        ((100.0, 100.0, 200.0, 120.0), False),
        ((0.0, 100.0, 10.0, 120.0), False),
    ],
)
def test_off_page_boxes(box, expected):
    assert is_off_page(*box, PAGE) is expected


def test_normalize_box_clamps_to_the_visible_page():
    bbox = normalize_box(-20, -10, 900, 900, PAGE)
    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == (0.0, 0.0, 1.0, 1.0)


def test_normalize_box_with_zero_page_size():
    bbox = normalize_box(0, 0, 10, 10, (0, 0, 0, 0))
    assert bbox.x1 == 0.0 and bbox.y1 == 0.0


def test_char_hidden_by_size():
    assert char_is_hidden({"size": 1.0}, PAGE, CONFIG) is True
    assert char_is_hidden({"size": 12.0}, PAGE, CONFIG) is False


def test_char_hidden_by_white_fill():
    assert char_is_hidden({"size": 12.0, "non_stroking_color": (1, 1, 1)}, PAGE, CONFIG) is True


def test_char_hidden_by_off_page_position():
    char = {"size": 12.0, "x0": 900, "top": 100, "x1": 950, "bottom": 120}
    assert char_is_hidden(char, PAGE, CONFIG) is True


def test_raw_word_fallback_applies_the_same_rules():
    assert raw_word_is_hidden({"size": 1.0}, PAGE, CONFIG) is True
    assert raw_word_is_hidden({"size": 12.0, "non_stroking_color": "white"}, PAGE, CONFIG) is True
    assert (
        raw_word_is_hidden(
            {"size": 12.0, "x0": 900, "top": 100, "x1": 950, "bottom": 120}, PAGE, CONFIG
        )
        is True
    )
    assert raw_word_is_hidden({"size": 12.0, "x0": 100, "top": 100}, PAGE, CONFIG) is False


def test_word_from_pdfplumber_skips_empty_text():
    assert word_from_pdfplumber({"text": "  "}, PAGE, CONFIG) is None


def test_word_from_pdfplumber_without_chars_uses_the_word_attributes():
    word = word_from_pdfplumber(
        {"text": "secret", "size": 1.0, "x0": 10, "top": 10, "x1": 20, "bottom": 20},
        PAGE,
        CONFIG,
    )
    assert word is not None and word.hidden is True


def test_word_from_pdfplumber_treats_a_string_chars_field_as_missing():
    word = word_from_pdfplumber(
        {"text": "plain", "size": 12.0, "x0": 10, "top": 10, "x1": 20, "bottom": 20, "chars": "x"},
        PAGE,
        CONFIG,
    )
    assert word is not None and word.hidden is False


def test_word_from_pdfplumber_uses_per_character_data():
    char = {
        "size": 12.0,
        "non_stroking_color": (1, 1, 1),
        "x0": 10,
        "top": 10,
        "x1": 20,
        "bottom": 20,
    }
    word = word_from_pdfplumber(
        {
            "text": "secret",
            "size": 12.0,
            "x0": 10,
            "top": 10,
            "x1": 20,
            "bottom": 20,
            "chars": [char],
        },
        PAGE,
        CONFIG,
    )
    assert word is not None and word.hidden is True
