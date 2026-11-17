#!/usr/bin/env python
"""`make drop-all` / `make drop-live`: copy a generated folder into data/inbox.

Usage:
    uv run python scripts/drop.py invoices     # the 57 the demo database holds
    uv run python scripts/drop.py live-demo    # the 6 kept back for the live demo (data/live-demo)

Each file gets its arrival time from the manifest, so invoice_intake takes them in the order
they arrived, on any machine (git does not keep file times).
"""

from __future__ import annotations

import sys

from invoiceflow.pipeline.demo_data import LIVE_SET_FOLDER, drop_folder, drop_live_set, live_set_dir
from invoiceflow.pipeline.steps import inbox_dir
from invoiceflow.settings import data_dir


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    if argv[0] == LIVE_SET_FOLDER:
        count = drop_live_set(live_set_dir(), inbox_dir())
    else:
        count = drop_folder(data_dir() / "generated", argv[0], inbox_dir())
    print(f"dropped {count} invoices from {argv[0]}/ into data/inbox (oldest arrival first)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
