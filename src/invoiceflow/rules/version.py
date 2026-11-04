"""The ``rule_version`` hash stamped on every finding.

A finding's ``rule_version`` must change when either the rule's code or its YAML config
changes, so a stored finding can always be traced back to the exact code + settings that
produced it. The hash covers the rule source file and the whole ``rules.yaml`` config
(any config edit bumps every rule; that is deliberate and cheap).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def config_digest(rules_config: Mapping[str, Any]) -> str:
    """A stable SHA-256 over the canonical JSON of the rules config."""
    return hashlib.sha256(_canonical(dict(rules_config)).encode("utf-8")).hexdigest()


def rule_version(rule_id: str, source_path: Path, rules_config: Mapping[str, Any]) -> str:
    """Hash the rule's source plus the rules config; returns a short hex digest."""
    payload = f"{source_path.read_text(encoding='utf-8')}\n{_canonical(dict(rules_config))}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
