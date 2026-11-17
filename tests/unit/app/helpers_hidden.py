"""A tiny PDF with white, 1 pt, and off-page text, for the app's R09 panel tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "parse"))

from helpers import hidden_text_pdf


def hidden_pdf() -> bytes:
    return hidden_text_pdf()
