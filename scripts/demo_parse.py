#!/usr/bin/env python
"""Manual Phase 1 check for WS2: parse a document and show what the reader saw.

Usage:
    uv run python scripts/demo_parse.py [path]

Default path is the golden clean invoice. Point it at any file (digital PDF or a scan
image/PDF) and it prints what ``invoiceflow.parse`` produced: words, boxes, hidden words,
the prompt text, and OCR confidence for scans.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from invoiceflow.parse import DocumentParser

DEFAULT = "tests/fixtures/golden/golden-a-clean/invoice.pdf"


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(DEFAULT)
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2

    parser = DocumentParser()
    document = parser.parse(path, file_id=uuid4(), doc_id=uuid4())
    print(f"file:     {path}")
    print(f"pages:    {len(document.pages)}")
    for page in document.pages:
        print(
            f"  page {page.page_no}: {len(page.words)} words, source={page.source.value}"
            f", size={page.width_pt:.0f}x{page.height_pt:.0f}pt"
            f", ocr_mean_conf={page.ocr_mean_conf}"
        )
    hidden = document.hidden_words
    print(f"hidden:   {len(hidden)} word(s)", end="")
    if hidden:
        shown = ", ".join(
            f"p{page_no}:{word.text[:20]!r}" for page_no, word in hidden[:3]
        )
        print(f" (e.g. {shown})")
    else:
        print()
    texts = parser.page_texts(document)
    for i, text in enumerate(texts, start=1):
        print(f"prompt p{i} (first 140 chars): {text[:140]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
