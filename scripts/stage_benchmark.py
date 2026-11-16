#!/usr/bin/env python
"""Stage the benchmark documents for scripts/bench_models.py.

bench_models.py expects one folder per document containing a file named ``invoice.pdf``. The
benchmark uses the 10 clean documents the generator plans for it (4 from layout A, 3 from B,
and 3 scans), which sit in ``data/generated/invoices/`` with every other document. This reads
the manifest to find them and copies each to ``data/benchmark/<invoice number>/invoice.pdf``,
rebuilding the folder each run.

Usage:
    uv run python scripts/stage_benchmark.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from invoiceflow.settings import repo_root

SOURCE = repo_root() / "data" / "generated"
TARGET = repo_root() / "data" / "benchmark"
# Plan ids are generator-internal keys; the benchmark's plans start with this.
BENCHMARK_PREFIX = "bench-"


def main() -> int:
    manifest = SOURCE / "manifest.json"
    if not manifest.is_file():
        print(f"not found: {manifest} (run `make data` first)", flush=True)
        return 2
    documents = json.loads(manifest.read_text(encoding="utf-8"))["documents"]
    shutil.rmtree(TARGET, ignore_errors=True)
    count = 0
    for doc in documents:
        if not str(doc["id"]).startswith(BENCHMARK_PREFIX):
            continue
        pdf = SOURCE / doc["file"]
        out = TARGET / Path(doc["file"]).stem
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf, out / "invoice.pdf")
        count += 1
    print(f"staged {count} benchmark document(s) into {TARGET}")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())
