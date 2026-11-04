"""Integration: build all 50 documents, check determinism, text layers, and truth data."""

from __future__ import annotations

import json
import time

import pdfplumber
import pypdfium2
import pytest

from generator.build import build
from generator.plans import ANOMALY_RULES
from generator.seeds import load_seeds
from invoiceflow.contracts import DocType, InvoiceTruth
from invoiceflow.settings import repo_root


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("ws1-build")
    started = time.perf_counter()
    manifest = build(seed=42, out=out)
    elapsed = time.perf_counter() - started
    return out, manifest, elapsed


@pytest.fixture(scope="session")
def manifest(built):
    return built[1]


@pytest.fixture(scope="session")
def rows(manifest):
    return {row["id"]: row for row in manifest["documents"]}


@pytest.fixture(scope="session")
def truths(built):
    root = built[0]
    result = {}
    for path in sorted(root.glob("docs/*/truth.json")):
        truth = InvoiceTruth.model_validate(json.loads(path.read_text()))
        result[truth.document_id] = truth
    return result


def test_build_writes_fifty_documents_under_two_minutes(built, manifest):
    out, _, elapsed = built
    assert len(manifest["documents"]) == 50
    assert manifest["counts"] == {"pre": 36, "live": 4, "benchmark": 10}
    assert elapsed < 120, f"build took {elapsed:.1f}s"
    assert (out / "manifest.json").is_file()
    assert (out / "master.json").is_file()
    assert len(list(out.glob("docs/*/truth.json"))) == 50


def test_manifest_rows_carry_id_type_template_anomalies_checks_and_set(manifest):
    for row in manifest["documents"]:
        assert set(row) >= {
            "id",
            "set",
            "doc_type",
            "template",
            "anomalies",
            "expected_checks",
            "file",
            "truth",
            "sha256",
            "text_layer",
        }
        assert row["set"] in {"pre", "live", "benchmark"}
        assert row["template"] in {"A1", "A2", "B1", "B2", "C1", "CN", "SOA"}
        assert isinstance(row["anomalies"], list)
        assert isinstance(row["expected_checks"], list)


def test_expected_checks_match_the_truth_files(rows, truths):
    for document_id, truth in truths.items():
        assert list(truth.expected_rules) == rows[document_id]["expected_checks"]
        assert list(truth.anomalies) == rows[document_id]["anomalies"]
        expected = []
        for anomaly in truth.anomalies:
            for rule in ANOMALY_RULES[anomaly]:
                if rule not in expected:
                    expected.append(rule)
        assert list(truth.expected_rules) == expected


def test_master_data_has_twelve_active_vendors(built):
    master = json.loads((built[0] / "master.json").read_text())
    assert len(master["vendors"]) == 12
    assert all(vendor["active"] for vendor in master["vendors"])
    assert master["purchase_orders"]
    assert len(master["coding"]["gl_accounts"]) == 8
    assert len(master["coding"]["cost_centers"]) == 8
    assert len(master["coding"]["tax_codes"]) == 6
    assert master["coding"]["venue_aliases"]


def test_every_digital_pdf_has_extractable_text(built, manifest):
    root = built[0]
    digital = [row for row in manifest["documents"] if row["text_layer"]]
    assert len(digital) == 39
    for row in digital:
        path = root / row["file"]
        with pdfplumber.open(path) as document:
            text = "\n".join((page.extract_text() or "") for page in document.pages)
        assert len(text.strip()) > 100, row["id"]
        assert row["invoice_number"] in text, row["id"]


def test_type_c_scans_are_jpg_and_one_page_image_pdf(built, manifest):
    root = built[0]
    scans = [row for row in manifest["documents"] if not row["text_layer"]]
    assert len(scans) == 11
    for row in scans:
        assert set(row["files"]) == {"truth", "jpg", "pdf"}
        jpg = root / row["files"]["jpg"]
        pdf = root / row["files"]["pdf"]
        assert jpg.is_file() and pdf.is_file()
        assert jpg.read_bytes().startswith(b"\xff\xd8")
        with pdfplumber.open(pdf) as document:
            assert len(document.pages) == 1
            assert not (document.pages[0].extract_text() or "")
        document = pypdfium2.PdfDocument(str(pdf))
        try:
            assert len(document) == 1
            assert document[0].render(scale=1).to_pil().size[0] > 500
        finally:
            document.close()


def test_file_hashes_match_the_manifest(built, manifest):
    import hashlib

    root = built[0]
    for row in manifest["documents"]:
        digest = hashlib.sha256((root / row["file"]).read_bytes()).hexdigest()
        assert digest == row["sha256"], row["id"]


def test_duplicate_file_is_byte_identical_to_its_original(built, rows):
    root = built[0]
    original = rows["pre-b-01"]
    duplicate = rows["pre-b-02"]
    assert duplicate["sha256"] == original["sha256"]
    assert (root / duplicate["file"]).read_bytes() == (root / original["file"]).read_bytes()


def test_resend_is_the_same_invoice_as_an_earlier_scan(built, rows):
    original = rows["pre-a-01"]
    resend = rows["pre-c-02"]
    assert resend["invoice_number"] == original["invoice_number"]
    assert resend["sha256"] != original["sha256"]
    assert resend["text_layer"] is False


def test_live_set_contains_the_slide_three_invoice(truths, rows):
    live = [row for row in rows.values() if row["set"] == "live"]
    assert len(live) == 4
    edited = truths["live-02"]
    assert edited.printed.subtotal == "1,080.00"
    assert edited.printed.total == "1,090.00"
    assert edited.expected_rules == ("R02",)


def test_hidden_instructions_are_white_one_point_text(built, rows):
    root = built[0]
    for document_id in ("pre-b-07", "live-04"):
        row = rows[document_id]
        with pdfplumber.open(root / row["file"]) as document:
            page = document.pages[0]
            words = page.extract_words(extra_attrs=["size", "non_stroking_color"])
        match = next(word for word in words if word["text"] == "Ignore")
        assert match["size"] <= 1.5
        color = match["non_stroking_color"]
        assert color in {(1, 1, 1), (1.0, 1.0, 1.0)}


def test_visible_instructions_are_normal_text(built, rows):
    root = built[0]
    for document_id in ("pre-a-09", "pre-b-10"):
        row = rows[document_id]
        with pdfplumber.open(root / row["file"]) as document:
            text = document.pages[0].extract_text()
            words = document.pages[0].extract_words(extra_attrs=["size"])
        assert "AI system" in text
        match = next(word for word in words if word["text"] == "AI")
        assert match["size"] > 2.0


def test_anomalies_match_only_their_intended_rule_signatures(built, rows, truths, manifest):
    root = built[0]
    order = {row["id"]: index for index, row in enumerate(manifest["documents"])}
    seeds = load_seeds(repo_root())
    sha_owner = {}
    for row in manifest["documents"]:
        sha_owner.setdefault(row["sha256"], []).append(row["id"])

    def signatures(document_id: str, truth: InvoiceTruth) -> set[str]:
        found: set[str] = set()
        if truth.doc_type is DocType.STATEMENT:
            found.add("statement")
        if truth.doc_type is DocType.CREDIT_NOTE and truth.invoice.total < 0:
            found.add("credit_note")
        if truth.vendor_id is None:
            found.add("unknown_vendor")
        if truth.invoice.ambiguous_dates:
            found.add("us_date_month_first")
        if (
            truth.doc_type is not DocType.STATEMENT
            and truth.invoice.subtotal is not None
            and truth.invoice.gst_amount is not None
            and truth.invoice.subtotal + truth.invoice.gst_amount != truth.invoice.total
        ):
            found.add("total_edited")
        if truth.printed.supplier_gst_reg_no is None:
            found.add("gst_reg_missing")
        if truth.printed.gst_rate not in {None, "9%", "0%"} and truth.invoice.currency == "SGD":
            found.add("gst_wrong_rate")
        if truth.vendor_id:
            vendor = seeds.vendor(truth.vendor_id)
            if (
                truth.printed.bank_account
                and truth.printed.bank_account.replace("-", "") != vendor.bank_account
            ):
                found.add("bank_account_changed")
            if (
                truth.invoice.venue
                and seeds.cost_center_for_venue(truth.invoice.venue) is None
                and vendor.default_cost_center is None
            ):
                found.add("venue_no_cost_center")
            if truth.printed.po_number:
                po = seeds.purchase_order(truth.printed.po_number)
                if truth.invoice.total > po.open_amount:
                    found.add("po_exceeded")
        if len(sha_owner[rows[document_id]["sha256"]]) > 1 and any(
            order[other] < order[document_id] for other in sha_owner[rows[document_id]["sha256"]]
        ):
            found.add("duplicate_file")
        same_invoice = [
            other
            for other, other_truth in truths.items()
            if other != document_id
            and other_truth.vendor_id == truth.vendor_id
            and other_truth.printed.invoice_number == truth.printed.invoice_number
            and order[other] < order[document_id]
        ]
        if same_invoice and any(
            rows[other]["sha256"] != rows[document_id]["sha256"] for other in same_invoice
        ):
            found.add("resend")
        path = root / rows[document_id]["file"]
        if rows[document_id]["text_layer"]:
            with pdfplumber.open(path) as document:
                page = document.pages[0]
                words = page.extract_words(extra_attrs=["size"])
                text = page.extract_text() or ""
            hidden = [w for w in words if w["text"] == "Ignore" and w["size"] <= 1.5]
            visible = [w for w in words if w["text"] == "AI" and w["size"] > 2.0]
            if hidden and "set the total to 10.00" in text:
                found.add("hidden_instructions")
            if visible and "AI system" in text:
                found.add("visible_instructions")
        return found

    for document_id, truth in truths.items():
        expected = set(truth.anomalies)
        actual = signatures(document_id, truth)
        assert actual == expected, f"{document_id}: expected {expected}, found {actual}"


def test_same_seed_rebuilds_byte_identically(tmp_path, built):
    first, first_manifest, _ = built
    second = tmp_path / "second"
    second_manifest = build(seed=42, out=second)
    assert first_manifest == second_manifest
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "master.json").read_bytes() == (second / "master.json").read_bytes()
    for row in first_manifest["documents"]:
        for relative in row["files"].values():
            assert (first / relative).read_bytes() == (second / relative).read_bytes(), row["id"]


def test_a_different_seed_changes_files_but_not_the_shape(tmp_path, manifest):
    other = build(seed=43, out=tmp_path / "seed-43")
    assert other["counts"] == {"pre": 36, "live": 4, "benchmark": 10}
    assert len(other["documents"]) == 50
    assert {row["sha256"] for row in other["documents"]} != {
        row["sha256"] for row in manifest["documents"]
    }
