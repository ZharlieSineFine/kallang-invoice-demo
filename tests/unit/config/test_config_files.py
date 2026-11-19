"""The four config files are part of the contract: workstreams read them, nobody renames keys."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoiceflow.settings import company_timezone, config_path, load_config, repo_root

RULE_IDS = [f"R{n:02d}" for n in range(1, 13)]


def test_repo_root_contains_pyproject():
    assert (repo_root() / "pyproject.toml").is_file()


def test_repo_root_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("INVOICEFLOW_ROOT", str(tmp_path))
    assert repo_root() == tmp_path


def test_missing_config_raises_clear_error():
    with pytest.raises(FileNotFoundError, match=r"nope\.yaml"):
        load_config("nope")


class TestCompany:
    def test_company(self):
        c = load_config("company")
        assert c["company_code"] == "KG01"
        assert c["currency"] == "SGD"
        assert c["entity_names"]


class TestRules:
    def test_every_rule_has_a_severity(self):
        r = load_config("rules")
        assert set(RULE_IDS) <= set(r["severities"])
        assert set(r["severities"].values()) <= {"INFO", "FLAG", "HOLD", "MANUAL"}

    def test_gst_rate_table(self):
        rates = load_config("rules")["gst_rates"]
        starts = [date.fromisoformat(str(row["from"])) for row in rates]
        assert starts == sorted(starts)
        assert rates[-1]["from"] == "2024-01-01"
        assert Decimal(str(rates[-1]["rate_percent"])) == Decimal("9")

    def test_thresholds_are_strings_for_decimal(self):
        r = load_config("rules")
        assert Decimal(r["simplified_invoice_max_total"]) == Decimal("1000.00")
        for value in r["tolerances"].values():
            assert isinstance(value, str), "tolerances are strings so they load as Decimal"


class TestModels:
    def test_chosen_model_and_settings(self):
        m = load_config("models")
        assert m["model"] == "gemma4:12b"
        assert m["fallback_model"] == "qwen3-vl:4b"
        opts = m["options"]
        assert (opts["temperature"], opts["seed"], opts["num_ctx"]) == (0, 42, 8192)
        assert m["think"] is False


class TestSapMapping:
    ALLOWED = ("const:", "doc.", "vendor.", "invoice.", "coding.", "batch.", "template:")

    def test_layout_is_labeled_hypothetical(self):
        assert load_config("sap_mapping")["layout"] == "hypothetical"

    def test_columns(self):
        cols = load_config("sap_mapping")["columns"]
        names = [c["name"] for c in cols]
        assert len(names) == len(set(names))
        required = {c["name"] for c in cols if c.get("required")}
        assert {"VendorNo", "Reference", "GLAccount", "CostCenter", "TaxCode"} <= required
        for c in cols:
            assert c["source"].startswith(self.ALLOWED), c


def test_company_timezone_comes_from_config():
    # The DAG schedules are read in this zone, so "0 18 * * *" means 18:00 in Singapore.
    assert company_timezone() == load_config("company")["timezone"] == "Asia/Singapore"


def test_no_secrets_in_config():
    suspicious = re.compile(r"(api[_-]?key|password|secret|token)\s*:\s*['\"]?[^\s'\"$]", re.I)
    for path in Path(config_path("company")).parent.glob("*.yaml"):
        text = path.read_text()
        assert not suspicious.search(text), f"{path.name} looks like it holds a secret"
        assert "sk-" not in text
