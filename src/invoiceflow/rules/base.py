"""Shared machinery for the R01-R12 checks. Everything is a pure function of CheckContext.

A check subclasses :class:`BaseRule`, sets ``rule_id``, and implements ``check``. The base
class wires the config severity and the ``rule_version`` hash so each rule file stays small.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from invoiceflow.contracts import (
    CheckContext,
    Finding,
    ParsedDocument,
    Scope,
    Severity,
)
from invoiceflow.rules.version import rule_version


def cfg_decimal(mapping: Mapping[str, Any], key: str) -> Decimal:
    """Read a config amount as a Decimal (YAML keeps amounts as strings on purpose)."""
    return Decimal(str(mapping[key]))


def fmt2(value: Decimal) -> str:
    """Format a Decimal to two places with no separators, e.g. ``1080.00``."""
    return f"{value:.2f}"


def money_sgd(value: Decimal) -> str:
    """Format a Decimal as SGD with thousands separators, e.g. ``S$1,080.00``."""
    return f"S${value:,.2f}"


def digits_only(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip().casefold()


def fuzzy_score(a: str | None, b: str | None) -> float:
    """Case-insensitive, whitespace-tolerant fuzzy match score (0-100)."""
    return float(fuzz.ratio(_norm(a), _norm(b)))


def visible_text(document: ParsedDocument) -> str:
    """All visible words joined, for the instruction-text scan (R09)."""
    return " ".join(w.text for page in document.pages for w in page.visible_words)


def gst_rate_for_date(config: Mapping[str, Any], on: date) -> Decimal | None:
    """The standard GST rate that applied on ``on``, from the ``gst_rates`` table."""
    rows = sorted(
        (date.fromisoformat(str(row["from"])), Decimal(str(row["rate_percent"])))
        for row in config["gst_rates"]
    )
    applicable = [rate for start, rate in rows if start <= on]
    return applicable[-1] if applicable else None


class BaseRule:
    """A single check. Subclasses set ``rule_id`` and implement ``check``."""

    rule_id: str = ""

    def __init__(self, rules_config: Mapping[str, Any]) -> None:
        self._config = dict(rules_config)
        self.severity = Severity(str(self._config["severities"][self.rule_id]))
        self._version = rule_version(self.rule_id, _source_file(type(self)), self._config)

    @property
    def id(self) -> str:
        return self.rule_id

    @property
    def rule_version(self) -> str:
        return self._version

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        raise NotImplementedError

    def finding(
        self,
        *,
        severity: Severity | None,
        scope: Scope,
        field: str | None = None,
        message: str,
        evidence: Mapping[str, str] | None = None,
    ) -> Finding:
        return Finding(
            rule_id=self.rule_id,
            rule_version=self._version,
            severity=severity if severity is not None else self.severity,
            scope=scope,
            field=field,
            message=message,
            evidence=dict(evidence or {}),
        )


def _source_file(cls: type) -> Path:
    path = inspect.getsourcefile(cls)
    return Path(path) if path else Path(__file__)
