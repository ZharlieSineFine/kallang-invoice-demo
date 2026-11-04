"""The rule_version hash is deterministic and sensitive to code and config."""

from pathlib import Path

from invoiceflow.rules.version import config_digest, rule_version

_SOURCE = Path(__file__)
_RULES = {"severities": {"R01": "FLAG"}, "tolerances": {"line_amount": "0.01"}}


def test_config_digest_is_deterministic():
    assert config_digest(_RULES) == config_digest(_RULES)


def test_config_digest_changes_with_config():
    assert config_digest(_RULES) != config_digest({**_RULES, "severities": {"R01": "HOLD"}})


def test_rule_version_is_deterministic():
    assert rule_version("R01", _SOURCE, _RULES) == rule_version("R01", _SOURCE, _RULES)


def test_rule_version_changes_with_config():
    changed = {**_RULES, "tolerances": {"line_amount": "0.99"}}
    assert rule_version("R01", _SOURCE, _RULES) != rule_version("R01", _SOURCE, changed)
