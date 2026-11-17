"""The 6 new live-demo invoices: nothing in common with the 54, never loaded by the demo
data, and built the same way every time."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest

from generator.live_set import LIVE_SET_DIR, build_live_set, live_plans
from invoiceflow.parse import DocumentParser, ParseConfig
from invoiceflow.parse.hidden import NOT_VISIBLE
from invoiceflow.parse.pdf import hidden_text_for_file
from invoiceflow.rules import Router
from invoiceflow.rules.audit import AuditSample
from invoiceflow.settings import load_config, repo_root

GENERATED = repo_root() / "data" / "generated"


@pytest.fixture(scope="module")
def built(tmp_path_factory, seeds):
    out = tmp_path_factory.mktemp("live-set")
    return out, build_live_set(seeds=seeds, out=out)


def _existing_manifest():
    return json.loads((GENERATED / "manifest.json").read_text(encoding="utf-8"))["documents"]


def test_six_plans_with_numbers_the_54_never_use():
    numbers = [plan.invoice_number for plan in live_plans()]
    assert numbers == [
        "CAM-2026-9601",
        "PWS-2026-9602",
        "CWF-2026-9603",
        "VTR-2026-9604",
        "KSS-2026-9605",
        "PCE-2026-9606",
    ]
    existing = {doc["invoice_number"] for doc in _existing_manifest()}
    assert not set(numbers) & existing


def test_every_vendor_is_in_the_master(seeds):
    for plan in live_plans():
        assert seeds.vendor(plan.vendor_id).active


def test_four_pass_and_two_are_caught():
    expected = [plan.expected_rules for plan in live_plans()]
    assert expected == [(), (), (), ("R09",), ("R02",), ()]
    assert [plan.template for plan in live_plans()].count("C1") == 1  # one scan


def test_the_build_writes_six_pdfs_answer_keys_and_a_manifest(built):
    out, manifest = built
    documents = manifest["documents"]
    assert len(documents) == 6
    for doc in documents:
        assert (out / doc["file"]).is_file()
        assert (out / doc["truth"]).is_file()
    saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest


def test_no_file_matches_any_of_the_54(built):
    _, manifest = built
    existing = {doc["sha256"] for doc in _existing_manifest()}
    assert not {doc["sha256"] for doc in manifest["documents"]} & existing


def test_the_build_is_repeatable(built, tmp_path, seeds):
    _, first = built
    again = build_live_set(seeds=seeds, out=tmp_path)
    assert [d["sha256"] for d in again["documents"]] == [d["sha256"] for d in first["documents"]]


def test_the_live_set_is_not_in_the_folder_the_demo_data_loads():
    assert LIVE_SET_DIR.resolve() == (repo_root() / "data" / "live-demo").resolve()
    assert not LIVE_SET_DIR.resolve().is_relative_to(GENERATED.resolve())


def test_the_hidden_text_is_only_caught_by_the_ocr_comparison(built, tmp_path):
    out, manifest = built
    doc = next(d for d in manifest["documents"] if d["invoice_number"] == "VTR-2026-9604")
    path = out / doc["file"]
    (passage,) = hidden_text_for_file(path, 1, ParseConfig()).passages
    assert passage.reasons == (NOT_VISIBLE,)
    document = DocumentParser(image_root=tmp_path).parse(path, file_id=uuid4(), doc_id=uuid4())
    prompt = " ".join(DocumentParser(image_root=tmp_path).page_texts(document))
    assert "pre-approved" not in prompt


def test_the_audit_seed_picks_only_the_sixth(built):
    """The demo shows the audit on PCE-2026-9606; the other five keep their planned outcome."""
    _, manifest = built
    sample = AuditSample.from_config(load_config("rules"))
    picked = [d["invoice_number"] for d in manifest["documents"] if sample.picks(d["sha256"])]
    assert picked == ["PCE-2026-9606"]


def test_the_invoices_meant_to_pass_are_under_the_auto_pass_limit(built):
    _, manifest = built
    limit = Router(load_config("rules")).auto_pass_limit
    passing = [d for d in manifest["documents"] if not d["expected_checks"]]
    assert all(Decimal(d["total"]) < limit for d in passing)
