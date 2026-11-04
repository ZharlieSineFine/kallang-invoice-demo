"""Find and normalize the latest evaluation report (WS8 writes it; format is CR-002).

The loader is intentionally tolerant of key names because contracts-v1 does not pin the
report shape. It never treats a missing report as an error: the Dashboard says so instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import EvaluationSummary
from invoiceflow.settings import repo_root

_SYNTHETIC_NAMES = {"synthetic", "golden", "pre", "benchmark", "demo"}
_NUMERIC = (int, float)


def _candidates(base: Path) -> list[Path]:
    preferred = [base / "latest.json", base / "evaluation.json", base / "eval.json"]
    found = [path for path in preferred if path.is_file()]
    found.extend(sorted(base.glob("eval-*.json")))
    found.extend(sorted(base.glob("evaluation-*.json")))
    unique: list[Path] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique


def _numeric_metrics(data: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for key, value in data.items():
        if isinstance(value, _NUMERIC) and not isinstance(value, bool):
            metrics[key] = float(value)
    nested = data.get("metrics")
    if isinstance(nested, dict):
        for key, value in nested.items():
            if isinstance(value, _NUMERIC) and not isinstance(value, bool):
                metrics.setdefault(key, float(value))
                metrics[f"metrics.{key}"] = float(value)
    return metrics


def load_evaluation(path: Path) -> EvaluationSummary | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    set_name = str(data.get("set_name") or data.get("set") or "synthetic")
    synthetic = data.get("synthetic")
    if synthetic is None:
        synthetic = set_name.strip().lower() in _SYNTHETIC_NAMES
    count = data.get("document_count") or data.get("documents")
    if isinstance(count, list):
        count = len(count)
    return EvaluationSummary(
        path=str(path),
        generated_at=(
            str(data.get("generated_at") or data.get("created_at"))
            if data.get("generated_at") or data.get("created_at")
            else None
        ),
        set_name=set_name,
        document_count=int(count) if isinstance(count, int) else None,
        metrics=_numeric_metrics(data),
        raw=data,
        synthetic=bool(synthetic),
    )


def latest_evaluation(reports_dir: Path | None = None) -> EvaluationSummary | None:
    base = Path(reports_dir) if reports_dir is not None else repo_root() / "reports"
    for path in _candidates(base):
        summary = load_evaluation(path)
        if summary is not None:
            return summary
    return None


__all__ = ["latest_evaluation", "load_evaluation"]
