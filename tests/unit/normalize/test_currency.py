import pytest

from invoiceflow.normalize import infer_currency, normalize_currency


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("S$", "SGD"),
        ("sgd", "SGD"),
        ("Singapore Dollar", "SGD"),
        ("US$", "USD"),
        ("RM", "MYR"),
        ("RMB", "CNY"),
        ("THB", "THB"),
        ("dollars", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_currency(raw, expected):
    assert normalize_currency(raw) == expected


def test_infer_currency_skips_blank_amounts_and_checks_each_prefix():
    assert infer_currency(None, "n/a", "S$1,090.00") == "SGD"
    assert infer_currency("no prefix", "US$ 97.20") == "USD"
    assert infer_currency("no prefix", None) is None
