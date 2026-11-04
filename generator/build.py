"""Build the WS1 synthetic invoice set.

Usage::

    uv run python generator/build.py --seed 42
    uv run python -m generator.build --seed 42 --out data/generated

The default output is ``data/generated/`` (git-ignored): one directory per document with the
file and ``truth.json``, plus ``manifest.json`` and ``master.json``. WS6 should wire
``make data SEED=42`` to the command above.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

if __package__ in {None, ""}:  # direct execution: python generator/build.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generator.plans import DocumentPlan, build_plans
from generator.render import file_sha256, write_pdf, write_scan
from generator.seeds import Seeds, load_seeds
from generator.truth import build_master, build_truth, totals_for
from invoiceflow.settings import repo_root

BUILD_TIME = datetime(2026, 11, 4, tzinfo=UTC)
SCHEMA_VERSION = "ws1-v1"


def _uuid(seed: int, document_id: str, kind: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"invoiceflow:ws1:{seed}:{document_id}:{kind}"))


def _dump(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def build_document(
    plan: DocumentPlan,
    *,
    seed: int,
    index: int,
    out: Path,
    seeds: Seeds,
    built: dict[str, Path],
) -> dict[str, object]:
    doc_dir = out / "docs" / plan.document_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    truth_path = doc_dir / "truth.json"
    truth = build_truth(plan, seeds)
    _dump(truth_path, truth.model_dump(mode="json"))

    files: dict[str, str] = {"truth": _relative(truth_path, out)}
    if plan.copy_of:
        source = built.get(plan.copy_of)
        if source is None:
            raise RuntimeError(f"{plan.document_id} copies {plan.copy_of}, which is not built yet")
        pdf_path = doc_dir / f"{plan.document_id}.pdf"
        shutil.copyfile(source, pdf_path)
        files["pdf"] = _relative(pdf_path, out)
        built[plan.document_id] = pdf_path
        sha = file_sha256(pdf_path)
        text_layer = True
    elif plan.template == "C1":
        jpg_path = doc_dir / f"{plan.document_id}.jpg"
        pdf_path = doc_dir / f"{plan.document_id}.pdf"
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
        pdf_path = doc_dir / f"{plan.document_id}.pdf"
        write_pdf(plan, seeds, pdf_path)
        files["pdf"] = _relative(pdf_path, out)
        built[plan.document_id] = pdf_path
        sha = file_sha256(pdf_path)
        text_layer = True

    totals = totals_for(plan)
    return {
        "id": plan.document_id,
        "set": plan.set_name,
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


def build(
    *,
    seed: int = 42,
    out: Path | None = None,
    plan_filter: str | None = None,
) -> dict[str, object]:
    """Build the set and return the manifest. Existing output is replaced."""
    root = repo_root()
    target = (out or (root / "data" / "generated")).resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    seeds = load_seeds(root)
    master = build_master(seeds)
    _dump(target / "master.json", master.model_dump(mode="json"))

    all_plans = build_plans(seed)
    selected = {
        plan.document_id
        for plan in all_plans
        if plan_filter is None or plan.set_name == plan_filter
    }

    built: dict[str, Path] = {}
    rows = []
    for index, plan in enumerate(all_plans):
        if plan.document_id not in selected:
            continue
        rows.append(
            build_document(plan, seed=seed, index=index, out=target, seeds=seeds, built=built)
        )

    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["set"])] = counts.get(str(row["set"]), 0) + 1
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
        "counts": counts,
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
    parser.add_argument(
        "--only",
        choices=("pre", "live", "benchmark"),
        default=None,
        help="build only one set (debugging; the demo needs all three)",
    )
    args = parser.parse_args(argv)

    started = time.perf_counter()
    manifest = build(seed=args.seed, out=args.out, plan_filter=args.only)
    elapsed = time.perf_counter() - started
    counts = ", ".join(f"{key}={value}" for key, value in sorted(manifest["counts"].items()))
    print(f"WS1: wrote {len(manifest['documents'])} documents ({counts}) in {elapsed:.1f}s")
    print(f"manifest: {Path(args.out or repo_root() / 'data' / 'generated') / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
