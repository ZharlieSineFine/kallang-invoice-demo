#!/usr/bin/env python
"""Stage WS1's benchmark documents for scripts/bench_models.py.

bench_models.py expects one folder per document containing a file named ``invoice.pdf``.
WS1 writes ``data/generated/docs/<id>/<id>.pdf`` instead, so this copies the 10 ``bench-*``
documents into ``data/benchmark/<id>/invoice.pdf`` (rebuilding the folder each run).

Usage:
    uv run python scripts/stage_benchmark.py
"""

from __future__ import annotations

import shutil

from invoiceflow.settings import repo_root

SOURCE = repo_root() / "data" / "generated" / "docs"
TARGET = repo_root() / "data" / "benchmark"


def main() -> int:
    if not SOURCE.is_dir():
        print(f"not found: {SOURCE} (run the WS1 generator first)", flush=True)
        return 2
    shutil.rmtree(TARGET, ignore_errors=True)
    count = 0
    for folder in sorted(SOURCE.glob("bench-*")):
        pdf = folder / f"{folder.name}.pdf"
        if not pdf.is_file():
            print(f"skipping {folder.name}: no {pdf.name}", flush=True)
            continue
        out = TARGET / folder.name
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf, out / "invoice.pdf")
        count += 1
    print(f"staged {count} benchmark document(s) into {TARGET}")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())
