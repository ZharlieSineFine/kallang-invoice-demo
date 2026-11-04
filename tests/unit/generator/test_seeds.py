"""Seed CSVs carry the fictional master data, with the format checks the brief requires."""

from __future__ import annotations

import re
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from generator.seeds import load_seeds
from invoiceflow.settings import repo_root

UEN = re.compile(r"^2099\d{5}[A-Z]$")


@pytest.fixture()
def seed_root(tmp_path: Path) -> Path:
    target = tmp_path / "seeds"
    shutil.copytree(repo_root() / "seeds", target)
    return tmp_path


def test_thirteen_vendors_twelve_active(seeds):
    assert len(seeds.vendors) == 13
    assert len(seeds.active_vendors()) == 12
    inactive = [v for v in seeds.vendors if not v.active]
    assert [v.vendor_id for v in inactive] == ["V999"]


def test_uens_are_fictional_2099_and_match_gst_numbers(seeds):
    for vendor in seeds.vendors:
        assert UEN.match(vendor.uen), vendor.uen
        assert vendor.gst_reg_no == vendor.uen
        assert vendor.bank_account.isdigit()


def test_coding_data_matches_the_build_plan(seeds):
    assert {c.code for c in seeds.cost_centers} == {
        "KG1100",
        "KG1200",
        "KG1300",
        "KG1400",
        "KG1500",
        "KG2100",
        "KG3100",
        "KG9100",
    }
    assert {g.code for g in seeds.gl_accounts} == {
        "610100",
        "610200",
        "620100",
        "620200",
        "620300",
        "630100",
        "640100",
        "650100",
    }
    assert {t.code for t in seeds.tax_codes} == {"TX", "ZP", "NR", "OP", "BL", "EP"}
    assert seeds.cost_center_for_venue("SIS") == "KG1200"
    assert seeds.cost_center_for_venue("Indoor Stadium") == "KG1200"
    assert seeds.cost_center_for_venue("Kallang Tennis Centre") is None


def test_vendors_have_defaults_and_pos_have_coding(seeds):
    for vendor in seeds.active_vendors():
        assert vendor.default_gl
        assert vendor.default_tax_code
    for po in seeds.purchase_orders:
        assert po.gl_account and po.cost_center
        assert po.open_amount <= po.amount
    assert any(v.default_cost_center is None for v in seeds.active_vendors()), (
        "the venue-no-cost-center anomaly needs a vendor without a default cost center"
    )


def test_master_excludes_the_inactive_unknown_vendor(seeds):
    from generator.truth import company_profile

    master = seeds.master(company=company_profile())
    assert {v.vendor_id for v in master.vendors} == {f"V{number:03d}" for number in range(1, 13)}
    assert all(v.active for v in master.vendors)
    assert master.purchase_orders


def test_missing_seed_file_is_a_clear_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match=r"vendors\.csv"):
        load_seeds(tmp_path)


def test_duplicate_uen_is_refused(seed_root: Path):
    path = seed_root / "seeds" / "vendors.csv"
    text = path.read_text()
    text = text.replace("209900234M", "209900123K", 1)
    path.write_text(text)
    with pytest.raises(ValueError, match="duplicate UEN"):
        load_seeds(seed_root)


def test_uen_must_use_2099(seed_root: Path):
    path = seed_root / "seeds" / "vendors.csv"
    text = path.read_text().replace("209900123K", "201900123K")
    path.write_text(text)
    with pytest.raises(ValueError, match="2099"):
        load_seeds(seed_root)


def test_gst_number_must_equal_uen(seed_root: Path):
    path = seed_root / "seeds" / "vendors.csv"
    text = path.read_text().replace("209900123K,209900123K", "209900123K,209900999Z")
    path.write_text(text)
    with pytest.raises(ValueError, match="GST number"):
        load_seeds(seed_root)


def test_bank_account_must_be_digits(seed_root: Path):
    path = seed_root / "seeds" / "vendors.csv"
    text = path.read_text().replace("0001234567", "000-123456-7", 1)
    path.write_text(text)
    with pytest.raises(ValueError, match="digits"):
        load_seeds(seed_root)


def test_po_cannot_exceed_its_amount(seed_root: Path):
    path = seed_root / "seeds" / "purchase_orders.csv"
    text = path.read_text().replace("5000.00,5000.00", "5000.00,6000.00", 1)
    path.write_text(text)
    with pytest.raises(ValueError, match="open amount"):
        load_seeds(seed_root)


def test_po_coding_must_exist(seed_root: Path):
    path = seed_root / "seeds" / "purchase_orders.csv"
    text = path.read_text().replace("610200,KG1100", "999999,KG1100", 1)
    path.write_text(text)
    with pytest.raises(ValueError, match="unknown GL"):
        load_seeds(seed_root)


def test_amounts_are_decimal(seeds):
    assert isinstance(seeds.purchase_orders[0].amount, Decimal)
    assert isinstance(seeds.tax_codes[0].rate_percent, Decimal)
