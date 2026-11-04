"""Reading order: words into visual lines, lines top-to-bottom, words left-to-right."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from invoiceflow.contracts import ParsedDocument, Word

_MIN_TOLERANCE = 0.0015


def reading_order_text(words: Iterable[Word]) -> str:
    """Prompt text for one page. Hidden words are left out."""
    visible = [word for word in words if not word.hidden and word.text.strip()]
    if not visible:
        return ""
    lines = group_into_lines(visible)
    return "\n".join(" ".join(word.text for word in line) for line in lines)


def group_into_lines(words: Sequence[Word]) -> tuple[tuple[Word, ...], ...]:
    """Group words whose vertical centres are close, then order by position."""
    ordered = sorted(words, key=lambda word: (word.bbox.y0 + word.bbox.y1, word.bbox.x0))
    lines: list[list[Word]] = []
    for word in ordered:
        centre = (word.bbox.y0 + word.bbox.y1) / 2
        height = word.bbox.height
        placed = False
        for line in reversed(lines):
            centres = sorted((member.bbox.y0 + member.bbox.y1) / 2 for member in line)
            line_centre = centres[len(centres) // 2]
            line_height = sorted(member.bbox.height for member in line)[len(line) // 2]
            tolerance = max(_MIN_TOLERANCE, 0.5 * min(height, line_height))
            if abs(centre - line_centre) <= tolerance:
                line.append(word)
                placed = True
                break
        if not placed:
            lines.append([word])

    for line in lines:
        line.sort(key=lambda word: (word.bbox.x0, word.bbox.y0))
    lines.sort(
        key=lambda line: (
            sorted((word.bbox.y0 + word.bbox.y1) / 2 for word in line)[len(line) // 2],
            min(word.bbox.x0 for word in line),
        )
    )
    return tuple(tuple(line) for line in lines)


def page_texts(document: ParsedDocument) -> tuple[str, ...]:
    """One string per page, in page order, with hidden words removed."""
    pages = sorted(document.pages, key=lambda page: page.page_no)
    return tuple(reading_order_text(page.words) for page in pages)
