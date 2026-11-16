#!/usr/bin/env python
"""`make drop-all` / `make drop-live`: copy a generated folder into data/inbox.

Usage:
    uv run python scripts/drop.py invoices     # the 50 for the recorded full run
    uv run python scripts/drop.py live-demo    # the 4 for the live demo

Each file gets its arrival time from the manifest, so invoice_intake takes them in the order
they arrived, on any machine (git does not keep file times).
"""

from __future__ import annotations

import sys

from invoiceflow.pipeline.demo_data import drop_folder
from invoiceflow.pipeline.steps import inbox_dir
from invoiceflow.settings import data_dir


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    count = drop_folder(data_dir() / "generated", argv[0], inbox_dir())
    print(f"dropped {count} invoices from {argv[0]}/ into data/inbox (oldest arrival first)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
