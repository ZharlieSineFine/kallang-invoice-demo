from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from invoiceflow.parse import ParseConfig
from invoiceflow.settings import load_config


def test_config_values_come_from_rules_yaml():
    config = ParseConfig.from_rules(load_config("rules"))
    assert config.scanned_page_min_chars == 25
    assert config.hidden_max_font_size_pt == pytest.approx(2.0)
    assert config.hidden_min_fill_lightness == pytest.approx(0.95)
    assert config.max_file_bytes == 20 * 1024 * 1024
    assert config.max_pages == 20


def test_config_from_repo_reads_the_real_file():
    assert ParseConfig.from_repo().scanned_page_min_chars == 25


def test_missing_rules_values_fall_back():
    config = ParseConfig.from_rules({})
    assert config.scanned_page_min_chars == 25
    assert config.hidden_max_font_size_pt == pytest.approx(2.0)


def test_config_is_frozen():
    with pytest.raises(FrozenInstanceError):
        ParseConfig().max_pages = 3  # type: ignore[misc]


def test_invalid_rules_values_fall_back():
    config = ParseConfig.from_rules(
        {
            "scanned_page_min_chars": "not-a-number",
            "hidden_text": {"max_font_size_pt": "nope", "min_fill_lightness": None},
        }
    )
    assert config.scanned_page_min_chars == 25
    assert config.hidden_max_font_size_pt == pytest.approx(2.0)
    assert config.hidden_min_fill_lightness == pytest.approx(0.95)


def test_from_repo_falls_back_when_config_is_missing(monkeypatch):
    import invoiceflow.parse.config as module

    def missing(_name):
        raise FileNotFoundError("no rules.yaml")

    monkeypatch.setattr(module, "load_config", missing)
    assert module.ParseConfig.from_repo().max_pages == 20
