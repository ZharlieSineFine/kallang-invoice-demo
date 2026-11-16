"""`make demo-data`: the parts of the demo load that can be tested without a model.

The script in ``scripts/demo_data.py`` runs every generated document through the real pipeline,
in the order they reach the inbox, as a rehearsal of the recorded demo. This module reads the
documents, compares what fired against what the generator planted, and turns pipeline output
into evaluation samples, so the demo's accuracy figures measure the model instead of comparing
the answer key with itself.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from invoiceflow.contracts import InvoiceTruth
from invoiceflow.evaluate.metrics import EvalSample

_DUPLICATE_RULE = "R05"


@dataclass(frozen=True)
class DemoDoc:
    name: str  # the file name without .pdf: the invoice number, plus " (2)" on a repeat
    folder: str  # "invoices" for the full run, "live-demo" for the four uploaded live
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
    folder: str = ""

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


def load_manifest(root: Path) -> tuple[DemoDoc, ...]:
    """Every document, in the order the manifest lists them: the order they arrive."""
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise SystemExit(f"no generated documents at {manifest}: run `make data` first")
    documents = json.loads(manifest.read_text(encoding="utf-8"))["documents"]
    return tuple(
        DemoDoc(
            name=Path(doc["file"]).stem,
            folder=Path(doc["file"]).parent.name,
            path=root / doc["file"],
            truth_path=root / doc["truth"],
            doc_id=UUID(doc["doc_id"]),
            file_id=UUID(doc["file_id"]),
            expected=tuple(doc["expected_checks"]),
        )
        for doc in documents
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
    return f"  {score.name:<22} {score.status:<13} {', '.join(parts)}"


def _folder_board(folder: str, scores: tuple[Score, ...]) -> list[str]:
    label = f"{folder}/: " if folder else ""
    matched = sum(score.exact for score in scores)
    total = f"{label}{matched} of {len(scores)} documents matched the checks the generator planted"
    return [total, *(_difference(score) for score in scores if not score.exact)]


def render_scoreboard(scores: tuple[Score, ...]) -> str:
    """One total per folder, in the order the folders arrive, each followed by its differences."""
    folders = dict.fromkeys(score.folder for score in scores)
    return "\n".join(
        line
        for folder in folders
        for line in _folder_board(folder, tuple(s for s in scores if s.folder == folder))
    )


def drop_folder(root: Path, folder: str, inbox: Path) -> int:
    """Copy one generated folder into the inbox and give each file its arrival time.

    The times come from the manifest, not the files: git does not keep file times, so a fresh
    clone would otherwise lose the order intake reads the inbox in. Returns the count.
    """
    manifest = root / "manifest.json"
    rows = (
        json.loads(manifest.read_text(encoding="utf-8"))["documents"] if manifest.is_file() else []
    )
    chosen = [row for row in rows if Path(row["file"]).parent.name == folder]
    if not chosen:
        raise SystemExit(f"no documents in {root / folder}: run `make data` first")
    inbox.mkdir(parents=True, exist_ok=True)
    for row in chosen:
        target = inbox / Path(row["file"]).name
        shutil.copyfile(root / row["file"], target)
        arrived = datetime.fromisoformat(row["received_at"].replace("Z", "+00:00")).timestamp()
        os.utime(target, (arrived, arrived))
    return len(chosen)
