"""Build the WS1 synthetic invoice set.

Usage::

    uv run python generator/build.py --seed 42
    uv run python -m generator.build --seed 42 --out data/generated

The default output is ``data/generated/`` (git-ignored):

- ``invoices/``: all 57 documents the demo database holds, named by invoice number. When a
  number repeats (the planted re-send and duplicate file), the later arrival gets `` (2)``.
  Each file's time is its arrival time, so an inbox that takes the oldest file first
  processes them in order: the 50 of the recorded full run, the 4 first shown live, then the
  3 at or above the auto-pass value limit (CR-012, added 2026-11-17).
- ``answer-key/``: what each of the 57 documents prints and which checks should fire, same
  names, plus the page image each scan was made from.
- ``manifest.json`` (in arrival order) and ``master.json``.

``make data`` runs the command above.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

if __package__ in {None, ""}:  # direct execution: python generator/build.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generator.plans import DocumentPlan, arrival_order, build_plans
from generator.render import file_sha256, write_pdf, write_scan
from generator.seeds import Seeds, load_seeds
from generator.truth import build_master, build_truth, totals_for
from invoiceflow.settings import repo_root

BUILD_TIME = datetime(2026, 11, 4, tzinfo=UTC)
SCHEMA_VERSION = "ws1-v2"
INVOICE_DIR = "invoices"  # all 57; the 6 for the live demo live in data/live-demo/
ANSWER_KEY_DIR = "answer-key"
# Arrival times are one minute apart, starting here; only their order matters.
FIRST_ARRIVAL = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9-]+$")


def _uuid(seed: int, document_id: str, kind: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"invoiceflow:ws1:{seed}:{document_id}:{kind}"))


def _dump(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def file_names(plans) -> dict[str, str]:
    """Each document's file name: its invoice number, with " (2)" on a later repeat."""
    names: dict[str, str] = {}
    seen: dict[str, int] = {}
    for plan in arrival_order(plans):
        if not _SAFE_NAME.fullmatch(plan.invoice_number):
            raise ValueError(f"{plan.document_id}: {plan.invoice_number!r} is not a safe file name")
        seen[plan.invoice_number] = seen.get(plan.invoice_number, 0) + 1
        count = seen[plan.invoice_number]
        names[plan.document_id] = (
            plan.invoice_number if count == 1 else f"{plan.invoice_number} ({count})"
        )
    return names


def build_document(
    plan: DocumentPlan,
    *,
    seed: int,
    index: int,
    name: str,
    out: Path,
    seeds: Seeds,
    built: dict[str, Path],
) -> dict[str, object]:
    invoice_dir = out / INVOICE_DIR
    key_dir = out / ANSWER_KEY_DIR
    truth_path = key_dir / f"{name}.json"
    truth = build_truth(plan, seeds)
    _dump(truth_path, truth.model_dump(mode="json"))

    files: dict[str, str] = {"truth": _relative(truth_path, out)}
    if plan.copy_of:
        source = built.get(plan.copy_of)
        if source is None:
            raise RuntimeError(f"{plan.document_id} copies {plan.copy_of}, which is not built yet")
        pdf_path = invoice_dir / f"{name}.pdf"
        shutil.copyfile(source, pdf_path)
        files["pdf"] = _relative(pdf_path, out)
        built[plan.document_id] = pdf_path
        sha = file_sha256(pdf_path)
        text_layer = True
    elif plan.template == "C1":
        jpg_path = key_dir / f"{name}.jpg"
        pdf_path = invoice_dir / f"{name}.pdf"
        write_scan(
            plan,
            seeds,
            seed=seed * 100_000 + index,
            jpg_path=jpg_path,
            pdf_path=pdf_path,
        )
        files["jpg"] = _relative(jpg_path, out)
        files["pdf"] = _relative(pdf_path, out)
        built[plan.document_id] = pdf_path
        sha = file_sha256(pdf_path)
        text_layer = False
    else:
        pdf_path = invoice_dir / f"{name}.pdf"
        write_pdf(plan, seeds, pdf_path)
        files["pdf"] = _relative(pdf_path, out)
        built[plan.document_id] = pdf_path
        sha = file_sha256(pdf_path)
        text_layer = True

    totals = totals_for(plan)
    return {
        "id": plan.document_id,
        "doc_type": plan.doc_type.value,
        "template": plan.template,
        "anomalies": list(plan.anomalies),
        "expected_checks": list(plan.expected_rules),
        "doc_id": _uuid(seed, plan.document_id, "doc"),
        "file_id": _uuid(seed, plan.document_id, "file"),
        "file": files["pdf"],
        "truth": files["truth"],
        "files": files,
        "sha256": sha,
        "text_layer": text_layer,
        "vendor_id": plan.vendor_id,
        "invoice_number": plan.invoice_number,
        "currency": plan.currency,
        "total": str(totals.total),
    }


def _stamp_arrivals(rows: list[dict[str, object]], out: Path) -> list[dict[str, object]]:
    """Give each file its arrival time. The rows come in arrival order."""
    stamped = []
    for arrival, row in enumerate(rows, start=1):
        received = FIRST_ARRIVAL + timedelta(minutes=arrival - 1)
        os.utime(out / str(row["file"]), (received.timestamp(), received.timestamp()))
        stamped.append(
            {**row, "arrival": arrival, "received_at": received.isoformat().replace("+00:00", "Z")}
        )
    return stamped


def build(*, seed: int = 42, out: Path | None = None) -> dict[str, object]:
    """Build every document and return the manifest. Existing output is replaced."""
    root = repo_root()
    target = (out or (root / "data" / "generated")).resolve()
    if target.exists():
        shutil.rmtree(target)
    for folder in (INVOICE_DIR, ANSWER_KEY_DIR):
        (target / folder).mkdir(parents=True)

    seeds = load_seeds(root)
    master = build_master(seeds)
    _dump(target / "master.json", master.model_dump(mode="json"))

    all_plans = build_plans(seed)
    names = file_names(all_plans)
    built: dict[str, Path] = {}
    by_id: dict[str, dict[str, object]] = {}
    # Plan order, so a copy is built after its original; the index keeps each scan's noise.
    for index, plan in enumerate(all_plans):
        by_id[plan.document_id] = build_document(
            plan,
            seed=seed,
            index=index,
            name=names[plan.document_id],
            out=target,
            seeds=seeds,
            built=built,
        )
    rows = _stamp_arrivals([by_id[plan.document_id] for plan in arrival_order(all_plans)], target)

    digital = sum(bool(row["text_layer"]) for row in rows)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "generated_at": BUILD_TIME.isoformat().replace("+00:00", "Z"),
        "master": "master.json",
        "fonts": [
            "FiraSans-Regular.ttf",
            "FiraSans-Bold.ttf",
            "IBMPlexMono-Regular.ttf",
            "IBMPlexMono-Bold.ttf",
        ],
        "counts": {"digital": digital, "scanned": len(rows) - digital},
        "folders": dict(Counter(Path(str(row["file"])).parent.name for row in rows)),
        "documents": rows,
    }
    _dump(target / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the WS1 synthetic invoice set")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory (default data/generated)",
    )
    args = parser.parse_args(argv)

    started = time.perf_counter()
    manifest = build(seed=args.seed, out=args.out)
    elapsed = time.perf_counter() - started
    counts = ", ".join(f"{key}={value}" for key, value in sorted(manifest["counts"].items()))
    folders = ", ".join(f"{count} in {name}/" for name, count in manifest["folders"].items())
    print(f"WS1: wrote {len(manifest['documents'])} documents ({counts}) in {elapsed:.1f}s")
    print(f"     {folders}")
    print(f"manifest: {Path(args.out or repo_root() / 'data' / 'generated') / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
