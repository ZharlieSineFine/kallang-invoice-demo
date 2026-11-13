"""Evaluation CLI: a self-check of the golden set, written reports, and the gate.

The golden run scores the truth files against themselves, so its 100% proves the scoring code
works and says nothing about the model. Only a real pipeline run (``make demo-data``) may write
the ``latest.json`` the demo shows.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from invoiceflow.evaluate.metrics import EvalReport, EvalSample, evaluate
from invoiceflow.pipeline.golden import load_golden
from invoiceflow.settings import repo_root

# The release gate: fail when accuracy drops more than this many points below baseline.
GATE_TOLERANCE_POINTS = 1.0

_BASELINE_NAME = "baseline.json"


def golden_samples() -> tuple[EvalSample, ...]:
    """Truth evaluated against itself: must score 100% everywhere."""
    golden = load_golden()
    samples: list[EvalSample] = []
    for fixture in golden.fixtures:
        truth = fixture.truth
        samples.append(
            EvalSample(
                document_id=fixture.fixture_id,
                truth=truth,
                predicted_extraction=truth.printed,
                predicted_coding=truth.expected_coding,
                predicted_rules=truth.expected_rules,
                latency_ms=0,
            )
        )
    return tuple(samples)


def gate_ok(
    accuracy: float, baseline_accuracy: float, tolerance: float = GATE_TOLERANCE_POINTS
) -> bool:
    return accuracy >= baseline_accuracy - tolerance


def load_baseline_accuracy(path: Path) -> float:
    data = json.loads(path.read_text(encoding="utf-8"))
    return float(data["accuracy"])


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def write_report(
    report: EvalReport, out_dir: Path, *, for_dashboard: bool = False
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    json_path = out_dir / f"eval_{stamp}.json"
    md_path = out_dir / f"eval_{stamp}.md"
    json_path.write_text(report.to_json() + "\n", encoding="utf-8")
    md_path.write_text(report.to_markdown() + "\n", encoding="utf-8")
    if for_dashboard:
        # CR-003: a stable path for the dashboard's "latest evaluation" card.
        (out_dir / "latest.json").write_text(report.to_json() + "\n", encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the invoice pipeline and run the gate.")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="write reports/baseline.json from the golden truth (100%% score)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="fail if accuracy drops more than one point below reports/baseline.json",
    )
    parser.add_argument("--out", default=str(repo_root() / "reports"), help="report directory")
    args = parser.parse_args(argv)

    report = evaluate(golden_samples())
    out_dir = Path(args.out)

    if args.baseline:
        out_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = out_dir / _BASELINE_NAME
        baseline_path.write_text(report.to_json() + "\n", encoding="utf-8")
        print(f"wrote {baseline_path} (accuracy {report.accuracy:.2f}%)")
        return 0

    json_path, md_path = write_report(report, out_dir)
    print(f"accuracy {report.accuracy:.2f}% ({report.samples} sample(s))")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")

    if args.gate:
        baseline_path = out_dir / _BASELINE_NAME
        if not baseline_path.is_file():
            print(f"no baseline at {baseline_path}; run with --baseline first", file=sys.stderr)
            return 2
        baseline_accuracy = load_baseline_accuracy(baseline_path)
        if gate_ok(report.accuracy, baseline_accuracy):
            print(f"gate OK: {report.accuracy:.2f}% vs baseline {baseline_accuracy:.2f}%")
            return 0
        print(
            f"gate FAILED: {report.accuracy:.2f}% is more than {GATE_TOLERANCE_POINTS} "
            f"point(s) below baseline {baseline_accuracy:.2f}%",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
