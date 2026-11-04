#!/usr/bin/env python
"""Render the star demo invoice with the R02 evidence drawn on it.

Draws the golden 1,080/1,090 twin with every located value boxed:
- green: values the system found exactly
- amber: the four line-item amounts (they sum to 1,080.00)
- red: the printed subtotal 1,090.00 (what R02 flags)

Outputs data/demo/twin-flagged.png (full page) and data/demo/twin-totals-zoom.png.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from invoiceflow.settings import repo_root

FIXTURE = repo_root() / "tests" / "fixtures" / "golden" / "golden-a-total-mismatch"
OUT = repo_root() / "data" / "demo"

GREEN = (34, 160, 80)
AMBER = (235, 160, 20)
RED = (215, 50, 50)
LEGEND_BG = (18, 18, 22, 235)


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except OSError:
        return ImageFont.load_default()


def main() -> int:
    image = Image.open(FIXTURE / "page-1.png").convert("RGB")
    w, h = image.size
    locations = json.loads((FIXTURE / "locations.json").read_text())
    draw = ImageDraw.Draw(image, "RGBA")

    line_amounts, totals = [], []
    for loc in locations:
        bbox = loc["bbox"]
        if not bbox:
            continue
        box = (
            bbox["x0"] * w - 3,
            bbox["y0"] * h - 3,
            bbox["x1"] * w + 3,
            bbox["y1"] * h + 3,
        )
        field = loc["field"]
        if field == "subtotal":
            color = RED
            totals.append(box)
        elif field.startswith("line_items") and field.endswith(".amount"):
            color = AMBER
            line_amounts.append(box)
        else:
            color = GREEN
        draw.rectangle(box, outline=color, width=3)

    f = _font(26)
    fb = _font(30)
    # Legend bar at the top.
    draw.rectangle([0, 0, w, 96], fill=LEGEND_BG)
    draw.rectangle([w * 0.03, 30, w * 0.07, 42], outline=GREEN, width=3)
    draw.text((w * 0.08, 24), "located exactly", fill=GREEN, font=f)
    draw.rectangle([w * 0.34, 30, w * 0.38, 42], outline=AMBER, width=3)
    draw.text((w * 0.39, 24), "line items sum to 1,080.00", fill=AMBER, font=f)
    draw.rectangle([w * 0.72, 30, w * 0.76, 42], outline=RED, width=3)
    draw.text((w * 0.77, 24), "printed subtotal 1,090.00 (R02)", fill=RED, font=f)

    # Caption next to the red subtotal box.
    if totals:
        x0, y0, x1, y1 = totals[0]
        draw.text((x1 + 14, y0 - 4), "R02: lines say 1,080.00,\nprinted says 1,090.00", fill=RED, font=fb)

    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / "twin-flagged.png")

    # Zoom on the totals block (subtotal -> payable).
    if totals and line_amounts:
        top = min(b[1] for b in line_amounts) - 30
        bottom = max(b[3] for b in totals) + 90
        zoom = image.crop((0, max(0, int(top)), w, min(h, int(bottom))))
        zoom.save(OUT / "twin-totals-zoom.png")
    print(f"wrote {OUT / 'twin-flagged.png'}")
    print(f"wrote {OUT / 'twin-totals-zoom.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
