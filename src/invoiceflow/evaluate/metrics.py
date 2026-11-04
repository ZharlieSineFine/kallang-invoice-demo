"""Evaluation measures for extraction, line items, coding, checks, and latency.

Scores are returned as percentages (0-100). "Evaluating the truth against itself" is a
sample whose predicted values equal the truth values, which must score 100% everywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from invoiceflow.contracts import (
    HEADER_FIELDS,
    CodingLine,
    ExtractedLineItem,
    InvoiceExtraction,
    InvoiceTruth,
)

_DATE_FIELDS = frozenset({"invoice_date", "due_date"})
_MONEY_FIELDS = frozenset(
    {"subtotal", "discount", "gst_amount", "total", "amount_due", "sgd_total", "sgd_gst_amount"}
)
_ID_FIELDS = frozenset(
    {
        "invoice_number",
        "po_number",
        "contract_number",
        "supplier_uen",
        "supplier_gst_reg_no",
        "bank_account",
        "original_invoice_ref",
    }
)
_LINE_FIELDS = ("line_no", "description", "quantity", "unit", "days", "unit_price", "amount")


def field_type(name: str) -> str:
    if name in _DATE_FIELDS:
        return "date"
    if name in _MONEY_FIELDS:
        return "money"
    if name in _ID_FIELDS:
        return "id"
    return "text"


@dataclass(frozen=True)
class EvalSample:
    """One document: the truth and what the pipeline predicted."""

    document_id: str
    truth: InvoiceTruth
    predicted_extraction: InvoiceExtraction | None
    predicted_coding: tuple[CodingLine, ...]
    predicted_rules: tuple[str, ...]
    latency_ms: int | None = None


def _eq(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return left == right


def _pct(fraction: float) -> float:
    return round(fraction * 100.0, 2)


def _line_eq(left: ExtractedLineItem, right: ExtractedLineItem) -> bool:
    return all(_eq(getattr(left, f), getattr(right, f)) for f in _LINE_FIELDS)


def _line_item_matches(
    predicted: tuple[ExtractedLineItem, ...], truth: tuple[ExtractedLineItem, ...]
) -> tuple[int, int, int]:
    """Return (true positives, predicted count, truth count) for one document."""
    matched_truth: set[int] = set()
    matched_pred: set[int] = set()
    for i, pred in enumerate(predicted):
        for j, expected in enumerate(truth):
            if j not in matched_truth and _line_eq(pred, expected):
                matched_pred.add(i)
                matched_truth.add(j)
                break
    return len(matched_pred), len(predicted), len(truth)


def _coding_accuracy(
    predicted: tuple[CodingLine, ...], expected: tuple[CodingLine, ...]
) -> tuple[int, dict[str, int]]:
    """Return (total lines, correct counts per dimension), aligned by line number."""
    total = max(len(predicted), len(expected))
    if total == 0:
        return 0, {"gl": 0, "cost_center": 0, "tax_code": 0, "overall": 0}
    gl = cost_center = tax_code = overall = 0
    for i in range(total):
        pred = predicted[i] if i < len(predicted) else None
        exp = expected[i] if i < len(expected) else None
        if pred is None or exp is None:
            continue
        g = pred.gl_account == exp.gl_account
        c = pred.cost_center == exp.cost_center
        t = pred.tax_code == exp.tax_code
        gl += g
        cost_center += c
        tax_code += t
        overall += g and c and t
    return total, {"gl": gl, "cost_center": cost_center, "tax_code": tax_code, "overall": overall}


def _check_matches(predicted: tuple[str, ...], expected: tuple[str, ...]) -> tuple[int, int, int]:
    pred = set(predicted)
    exp = set(expected)
    return len(pred & exp), len(pred), len(exp)


@dataclass(frozen=True)
class EvalReport:
    accuracy: float
    header: dict[str, Any]
    line_items: dict[str, float]
    coding: dict[str, float]
    checks: dict[str, float]
    latency: dict[str, Any]
    samples: int
    set_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "set_name": self.set_name,
            "samples": self.samples,
            "accuracy": self.accuracy,
            "header": self.header,
            "line_items": self.line_items,
            "coding": self.coding,
            "checks": self.checks,
            "latency": self.latency,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def to_markdown(self) -> str:
        lines = [
            f"# Evaluation — {self.set_name}",
            "",
            f"- Samples: {self.samples}",
            f"- **Header-field accuracy: {self.accuracy:.2f}%**",
            f"- Invoices with every header field right: {self.header['all_correct_share']:.2f}%",
            "",
            "## Header accuracy by type",
            "",
            "| type | accuracy |",
            "|---|---|",
        ]
        for kind, value in self.header["by_type"].items():
            lines.append(f"| {kind} | {value:.2f}% |")
        lines += [
            "",
            "## Line items",
            "",
            f"- Precision: {self.line_items['precision']:.2f}%",
            f"- Recall: {self.line_items['recall']:.2f}%",
            "",
            "## Coding",
            "",
            "| dimension | accuracy |",
            "|---|---|",
            f"| GL account | {self.coding['gl']:.2f}% |",
            f"| Cost center | {self.coding['cost_center']:.2f}% |",
            f"| Tax code | {self.coding['tax_code']:.2f}% |",
            f"| Overall | {self.coding['overall']:.2f}% |",
            "",
            "## Checks",
            "",
            f"- Precision: {self.checks['precision']:.2f}%",
            f"- Recall: {self.checks['recall']:.2f}%",
            "",
            "## Latency",
            "",
            f"- Mean: {self.latency['mean_ms']} ms",
            f"- Max: {self.latency['max_ms']} ms",
            "",
        ]
        return "\n".join(lines)


def evaluate(samples: tuple[EvalSample, ...], *, set_name: str = "golden") -> EvalReport:
    """Score a set of samples. Empty set scores as a perfect report."""
    header_correct = {name: 0 for name in HEADER_FIELDS}
    header_total = 0
    by_type_correct: dict[str, int] = {}
    by_type_total: dict[str, int] = {}
    all_correct = 0

    line_tp = line_pred = line_truth = 0

    coding_correct = {"gl": 0, "cost_center": 0, "tax_code": 0, "overall": 0}
    coding_total = 0

    check_tp = check_pred = check_exp = 0

    latencies: list[int] = []

    for sample in samples:
        if sample.latency_ms is not None:
            latencies.append(sample.latency_ms)

        extraction = sample.predicted_extraction
        doc_all_correct = extraction is not None
        for name in HEADER_FIELDS:
            header_total += 1
            kind = field_type(name)
            by_type_total[kind] = by_type_total.get(kind, 0) + 1
            ok = extraction is not None and _eq(
                getattr(extraction, name), getattr(sample.truth.printed, name)
            )
            if ok:
                header_correct[name] += 1
                by_type_correct[kind] = by_type_correct.get(kind, 0) + 1
            else:
                doc_all_correct = False
        if doc_all_correct:
            all_correct += 1

        tp, pc, tc = _line_item_matches(
            extraction.line_items if extraction is not None else (),
            sample.truth.printed.line_items,
        )
        line_tp += tp
        line_pred += pc
        line_truth += tc

        coding_lines_total, corrects = _coding_accuracy(
            sample.predicted_coding, sample.truth.expected_coding
        )
        coding_total += coding_lines_total
        for key, correct in corrects.items():
            coding_correct[key] += correct

        ctp, cpred, cexp = _check_matches(sample.predicted_rules, sample.truth.expected_rules)
        check_tp += ctp
        check_pred += cpred
        check_exp += cexp

    def _share(correct: int, total: int) -> float:
        return _pct(correct / total) if total else 100.0

    overall = _share(sum(header_correct.values()), header_total)
    header_by_field = {name: _share(header_correct[name], len(samples)) for name in HEADER_FIELDS}
    header_by_type = {
        kind: _share(by_type_correct.get(kind, 0), by_type_total.get(kind, 0))
        for kind in sorted(by_type_total)
    }
    all_correct_share = _pct(all_correct / len(samples)) if samples else 100.0

    line_precision = _pct(line_tp / line_pred) if line_pred else 100.0
    line_recall = _pct(line_tp / line_truth) if line_truth else 100.0

    coding = {
        key: _share(coding_correct[key], coding_total)
        for key in ("gl", "cost_center", "tax_code", "overall")
    }
    check_precision = _pct(check_tp / check_pred) if check_pred else 100.0
    check_recall = _pct(check_tp / check_exp) if check_exp else 100.0

    return EvalReport(
        accuracy=overall,
        header={
            "overall": overall,
            "by_field": header_by_field,
            "by_type": header_by_type,
            "all_correct_share": all_correct_share,
        },
        line_items={"precision": line_precision, "recall": line_recall},
        coding=coding,
        checks={"precision": check_precision, "recall": check_recall},
        latency={
            "mean_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "max_ms": max(latencies) if latencies else None,
            "count": len(latencies),
        },
        samples=len(samples),
        set_name=set_name,
    )
