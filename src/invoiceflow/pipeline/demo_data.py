"""`make demo-data`: the parts of the demo load that can be tested without a model.

The script in ``scripts/demo_data.py`` runs the generated "yesterday" batch through the real
pipeline. This module selects the documents, compares what fired against what the generator
planted, and turns pipeline output into evaluation samples, so the demo's accuracy figures
measure the model instead of comparing the answer key with itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from invoiceflow.contracts import InvoiceTruth
from invoiceflow.evaluate.metrics import EvalSample

_DUPLICATE_RULE = "R05"


@dataclass(frozen=True)
class DemoDoc:
    name: str
    set_name: str
    path: Path
    truth_path: Path
    doc_id: UUID
    file_id: UUID
    expected: tuple[str, ...]


@dataclass(frozen=True)
class Score:
    name: str
    status: str
    expected: tuple[str, ...]
    actual: tuple[str, ...]
    skipped: bool = False

    @property
    def missed(self) -> tuple[str, ...]:
        # A byte-identical file is rejected at intake, which is how R05's first case is caught.
        caught = {_DUPLICATE_RULE} if self.skipped else set()
        return tuple(sorted(set(self.expected) - set(self.actual) - caught))

    @property
    def extra(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.actual) - set(self.expected)))

    @property
    def exact(self) -> bool:
        return not self.missed and not self.extra


def load_manifest(root: Path, set_name: str) -> tuple[DemoDoc, ...]:
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise SystemExit(f"no generated documents at {manifest}: run `make data` first")
    documents = json.loads(manifest.read_text(encoding="utf-8"))["documents"]
    return tuple(
        DemoDoc(
            name=doc["id"],
            set_name=doc["set"],
            path=root / doc["file"],
            truth_path=root / doc["truth"],
            doc_id=UUID(doc["doc_id"]),
            file_id=UUID(doc["file_id"]),
            expected=tuple(doc["expected_checks"]),
        )
        for doc in documents
        if doc["set"] == set_name
    )


def load_truth(doc: DemoDoc) -> InvoiceTruth:
    return InvoiceTruth.model_validate_json(doc.truth_path.read_text(encoding="utf-8"))


def require_empty_or_reset(*, document_count: int, reset: bool) -> None:
    if document_count and not reset:
        raise SystemExit(
            f"the database already has {document_count} documents; "
            "rerun with `make demo-data RESET=1` to replace them"
        )


def eval_sample(name: str, truth: InvoiceTruth, result) -> EvalSample:
    """Score what the pipeline produced, not what the truth file says it should have."""
    return EvalSample(
        document_id=name,
        truth=truth,
        predicted_extraction=result.extraction.extraction,
        predicted_coding=result.context.coding_lines,
        predicted_rules=tuple(dict.fromkeys(finding.rule_id for finding in result.findings)),
        latency_ms=result.extraction.latency_ms,
    )


def _difference(score: Score) -> str:
    parts = [f"missed {rule}" for rule in score.missed] + [f"extra {rule}" for rule in score.extra]
    return f"  {score.name:<14} {score.status:<13} {', '.join(parts)}"


def render_scoreboard(scores: tuple[Score, ...]) -> str:
    matched = sum(score.exact for score in scores)
    lines = [f"{matched} of {len(scores)} documents matched the checks the generator planted"]
    lines.extend(_difference(score) for score in scores if not score.exact)
    return "\n".join(lines)
