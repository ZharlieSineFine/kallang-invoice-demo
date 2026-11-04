"""WS2 read settings. Values come from ``config/rules.yaml`` where they exist."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from invoiceflow.settings import load_config

MIB = 1024 * 1024


@dataclass(frozen=True)
class ParseConfig:
    max_file_bytes: int = 20 * MIB
    max_pages: int = 20
    review_dpi: int = 150
    ocr_dpi: int = 300
    scanned_page_min_chars: int = 25
    hidden_max_font_size_pt: float = 2.0
    hidden_min_fill_lightness: float = 0.95

    @classmethod
    def from_rules(cls, rules: Mapping[str, Any]) -> ParseConfig:
        """Build from the ``rules.yaml`` mapping, falling back to the contract defaults."""
        hidden = rules.get("hidden_text")
        hidden = hidden if isinstance(hidden, Mapping) else {}
        return cls(
            scanned_page_min_chars=_as_int(
                rules.get("scanned_page_min_chars"), cls.scanned_page_min_chars
            ),
            hidden_max_font_size_pt=_as_float(
                hidden.get("max_font_size_pt"), cls.hidden_max_font_size_pt
            ),
            hidden_min_fill_lightness=_as_float(
                hidden.get("min_fill_lightness"), cls.hidden_min_fill_lightness
            ),
        )

    @classmethod
    def from_repo(cls) -> ParseConfig:
        """Read ``config/rules.yaml``; use defaults when the file is unavailable."""
        try:
            rules = load_config("rules")
        except (FileNotFoundError, OSError):
            return cls()
        return cls.from_rules(rules)


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback
