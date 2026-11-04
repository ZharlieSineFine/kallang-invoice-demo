#!/usr/bin/env python
"""Manual Phase 1 check for WS4: normalize sample values and locate fields on a golden PDF.

Usage:
    uv run python scripts/demo_locate.py

Prints the printed-vs-normalized conversions the runbook asks about, then runs the real
Locator over the golden clean invoice and shows the match for the subtotal and total.
"""

from __future__ import annotations

from uuid import uuid4

from invoiceflow.locate import Locator
from invoiceflow.normalize import normalize_amount, normalize_date, normalize_id
from invoiceflow.parse import DocumentParser
from invoiceflow.pipeline.golden import load_golden


def main() -> int:
    print("== WS4: printed -> normalized ==")
    print("S$1,090.00      ->", normalize_amount("S$1,090.00"))
    print("12 Oct 2026 (SG)->", normalize_date("12 Oct 2026", locale="SG")[0])
    print("M2-1234567-8    ->", normalize_id("M2-1234567-8"))

    golden = load_golden()
    fixture = golden.fixtures[0]
    document = DocumentParser().parse(
        fixture.pdf_path, file_id=uuid4(), doc_id=uuid4()
    )
    locations = Locator().locate(document, fixture.truth.printed)
    print(f"\n== WS4: locate on {fixture.fixture_id} ==")
    print(f"locations: {len(locations)}")
    for name in ("subtotal", "total", "invoice_number", "gst_amount"):
        match = next((loc for loc in locations if loc.field == name), None)
        if match is None:
            print(f"  {name:<16} not returned")
        elif match.bbox is None:
            print(f"  {name:<16} NOT FOUND")
        else:
            print(
                f"  {name:<16} {match.match_type.value:<6} score={match.score:>5} "
                f"page={match.page_no} matched_text={match.matched_text!r}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
