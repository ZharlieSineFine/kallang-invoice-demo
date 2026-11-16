"""`make demo-data`: which documents run, how results are scored, and the guard."""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from invoiceflow.pipeline.demo_data import (
    Score,
    eval_sample,
    load_manifest,
    render_scoreboard,
    require_empty_or_reset,
)

DOC = "e3b44d80-6038-5ce2-877d-d71b775fdcd1"
FILE = "47f81e0e-22a9-5063-a5fe-2b32ed004035"


def _manifest(tmp_path):
    documents = [
        {
            "id": "pre-a-03",
            "doc_id": DOC,
            "file_id": FILE,
            "file": "invoices/SAV-2026-1003.pdf",
            "truth": "answer-key/SAV-2026-1003.json",
            "expected_checks": ["R02"],
        },
        {
            "id": "pre-c-02",
            "doc_id": "e3b44d80-6038-5ce2-877d-d71b775fdcd2",
            "file_id": "47f81e0e-22a9-5063-a5fe-2b32ed004036",
            "file": "invoices/SAV-2026-1001 (2).pdf",
            "truth": "answer-key/SAV-2026-1001 (2).json",
            "expected_checks": ["R05"],
        },
        {
            "id": "showcase-pdf-1",
            "doc_id": "e3b44d80-6038-5ce2-877d-d71b775fdcd3",
            "file_id": "47f81e0e-22a9-5063-a5fe-2b32ed004037",
            "file": "live-demo/VTR-2026-9001.pdf",
            "truth": "answer-key/VTR-2026-9001.json",
            "expected_checks": [],
        },
    ]
    (tmp_path / "manifest.json").write_text(json.dumps({"documents": documents}), encoding="utf-8")
    return tmp_path


def test_load_manifest_returns_every_document_in_arrival_order(tmp_path):
    docs = load_manifest(_manifest(tmp_path))
    assert [doc.name for doc in docs] == ["SAV-2026-1003", "SAV-2026-1001 (2)", "VTR-2026-9001"]
    assert [doc.folder for doc in docs] == ["invoices", "invoices", "live-demo"]
    assert docs[0].doc_id == UUID(DOC)
    assert docs[0].file_id == UUID(FILE)
    assert docs[0].expected == ("R02",)
    assert docs[0].path == tmp_path / "invoices/SAV-2026-1003.pdf"
    assert docs[1].truth_path == tmp_path / "answer-key/SAV-2026-1001 (2).json"


def test_load_manifest_explains_what_to_run_when_data_is_missing(tmp_path):
    with pytest.raises(SystemExit, match="make data"):
        load_manifest(tmp_path)


def test_score_separates_missed_and_extra_checks():
    score = Score(name="a", status="NEEDS_REVIEW", expected=("R02", "R08"), actual=("R02", "R11"))
    assert score.missed == ("R08",)
    assert score.extra == ("R11",)
    assert not score.exact


def test_a_skipped_duplicate_counts_as_caught_when_r05_was_expected():
    score = Score(name="a", status="SKIPPED", expected=("R05",), actual=(), skipped=True)
    assert score.missed == ()
    assert score.exact


def test_scoreboard_totals_and_lists_only_the_differences():
    text = render_scoreboard(
        (
            Score(name="ok", status="AUTO_PASSED", expected=(), actual=()),
            Score(name="off", status="NEEDS_REVIEW", expected=("R02",), actual=("R11",)),
        )
    )
    assert "1 of 2 documents matched" in text
    assert "off" in text
    assert "missed R02" in text
    assert "extra R11" in text
    assert "ok " not in text


def test_scoreboard_has_one_total_per_folder():
    text = render_scoreboard(
        (
            Score(name="a", status="AUTO_PASSED", expected=(), actual=(), folder="invoices"),
            Score(name="b", status="ON_HOLD", expected=(), actual=("R08",), folder="invoices"),
            Score(name="c", status="AUTO_PASSED", expected=(), actual=(), folder="live-demo"),
        )
    )
    assert "invoices/: 1 of 2 documents matched" in text
    assert "live-demo/: 1 of 1 documents matched" in text
    assert text.index("invoices/") < text.index("  b ") < text.index("live-demo/")


def test_guard_refuses_to_wipe_existing_documents_without_reset():
    with pytest.raises(SystemExit, match="RESET=1"):
        require_empty_or_reset(document_count=2, reset=False)
    require_empty_or_reset(document_count=2, reset=True)
    require_empty_or_reset(document_count=0, reset=False)


def test_eval_sample_reports_what_the_pipeline_actually_produced(golden):
    from dataclasses import dataclass

    from invoiceflow.contracts import InvoiceTruth

    fixture = golden.fixtures[1]

    @dataclass(frozen=True)
    class Context:
        coding_lines: tuple = ()

    @dataclass(frozen=True)
    class Result:
        extraction: object
        context: object
        findings: tuple

    truth = fixture.truth
    assert isinstance(truth, InvoiceTruth)
    result = Result(
        extraction=fixture.extraction, context=Context(), findings=fixture.expected_findings
    )
    sample = eval_sample("twin", truth, result)
    assert sample.document_id == "twin"
    assert sample.predicted_extraction == fixture.extraction.extraction
    assert sample.predicted_rules == ("R02",)
    assert sample.latency_ms == fixture.extraction.latency_ms
