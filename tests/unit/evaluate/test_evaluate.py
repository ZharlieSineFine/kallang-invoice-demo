"""Evaluation measure tests, including truth-vs-itself scoring 100%."""

import pytest

from invoiceflow.evaluate.cli import (
    gate_ok,
    golden_samples,
    load_baseline_accuracy,
)
from invoiceflow.evaluate.metrics import EvalSample, evaluate, field_type


def test_truth_against_itself_scores_100():
    report = evaluate(golden_samples())
    assert report.accuracy == 100.0
    assert report.header["all_correct_share"] == 100.0
    assert report.line_items == {"precision": 100.0, "recall": 100.0}
    assert report.coding == {
        "gl": 100.0,
        "cost_center": 100.0,
        "tax_code": 100.0,
        "overall": 100.0,
    }
    assert report.checks == {"precision": 100.0, "recall": 100.0}
    assert report.samples == 2


def test_field_type_categories():
    assert field_type("invoice_date") == "date"
    assert field_type("total") == "money"
    assert field_type("invoice_number") == "id"
    assert field_type("supplier_name") == "text"


def test_wrong_header_field_lowers_accuracy():
    sample = golden_samples()[0]
    wrong = EvalSample(
        document_id=sample.document_id,
        truth=sample.truth,
        predicted_extraction=sample.truth.printed.model_copy(update={"invoice_number": "WRONG"}),
        predicted_coding=sample.predicted_coding,
        predicted_rules=sample.predicted_rules,
    )
    report = evaluate((wrong,))
    assert report.accuracy < 100.0
    assert report.header["by_field"]["invoice_number"] == 0.0


def test_line_item_precision_and_recall():
    sample = golden_samples()[0]
    wrong = EvalSample(
        document_id=sample.document_id,
        truth=sample.truth,
        predicted_extraction=sample.truth.printed.model_copy(
            update={"line_items": sample.truth.printed.line_items[:-1]}
        ),
        predicted_coding=sample.predicted_coding,
        predicted_rules=sample.predicted_rules,
    )
    report = evaluate((wrong,))
    assert report.line_items["precision"] == 100.0
    assert report.line_items["recall"] == 75.0  # 3 of 4 lines matched


def test_coding_accuracy_detects_wrong_gl():
    sample = golden_samples()[0]
    wrong = EvalSample(
        document_id=sample.document_id,
        truth=sample.truth,
        predicted_extraction=sample.truth.printed,
        predicted_coding=(
            sample.truth.expected_coding[0].model_copy(update={"gl_account": "610100"}),
        ),
        predicted_rules=sample.predicted_rules,
    )
    report = evaluate((wrong,))
    assert report.coding["gl"] == 0.0
    assert report.coding["cost_center"] == 100.0


def test_check_precision_and_recall():
    sample = golden_samples()[1]  # total-mismatch expects R02
    wrong = EvalSample(
        document_id=sample.document_id,
        truth=sample.truth,
        predicted_extraction=sample.truth.printed,
        predicted_coding=sample.predicted_coding,
        predicted_rules=(),  # missed R02
    )
    report = evaluate((wrong,))
    assert report.checks["precision"] == 100.0
    assert report.checks["recall"] == 0.0


def test_empty_samples_score_perfect():
    report = evaluate(())
    assert report.accuracy == 100.0
    assert report.samples == 0


def test_report_serializes_to_json_and_markdown():
    report = evaluate(golden_samples())
    assert report.to_dict()["accuracy"] == 100.0
    assert "# Evaluation" in report.to_markdown()
    assert "100.00%" in report.to_markdown()


def test_gate_tolerance():
    assert gate_ok(100.0, 100.0)
    assert gate_ok(99.5, 100.0)
    assert not gate_ok(98.9, 100.0)


def test_load_baseline_accuracy(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text('{"accuracy": 99.0}', encoding="utf-8")
    assert load_baseline_accuracy(path) == 99.0


def test_latency_is_reported():
    from dataclasses import replace

    samples = golden_samples()
    with_latency = tuple(replace(s, latency_ms=i * 10) for i, s in enumerate(samples))
    report = evaluate(with_latency)
    assert report.latency["count"] == 2
    assert report.latency["mean_ms"] == pytest.approx(5.0)
    assert report.latency["max_ms"] == 10
