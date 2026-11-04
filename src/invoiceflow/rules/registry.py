"""Builds the twelve checks (R01-R12) in order, each with its own rule_version hash."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from invoiceflow.contracts import Rule
from invoiceflow.rules.r01 import R01
from invoiceflow.rules.r02 import R02
from invoiceflow.rules.r03 import R03
from invoiceflow.rules.r04 import R04
from invoiceflow.rules.r05 import R05
from invoiceflow.rules.r06 import R06
from invoiceflow.rules.r07 import R07
from invoiceflow.rules.r08 import R08
from invoiceflow.rules.r09 import R09
from invoiceflow.rules.r10 import R10
from invoiceflow.rules.r11 import R11
from invoiceflow.rules.r12 import R12

_ALL = (R01, R02, R03, R04, R05, R06, R07, R08, R09, R10, R11, R12)


def build_rules(rules_config: Mapping[str, Any]) -> tuple[Rule, ...]:
    """Instantiate every check against one rules config."""
    return tuple(rule_cls(rules_config) for rule_cls in _ALL)
