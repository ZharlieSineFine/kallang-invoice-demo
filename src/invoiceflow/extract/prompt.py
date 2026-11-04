"""Prompt loading and rendering for extraction.

The prompt template lives in ``prompts/extract_v1.md``. It has two placeholders,
``__CANARY__`` and ``__DOCUMENT__``, filled here. The canary token is a fixed string that
lets us detect prompt leakage or injection (see HANDOFF-ws3.md).
"""

from __future__ import annotations

from pathlib import Path

PROMPT_VERSION = "extract-v1"
# The single project-wide canary (CR-001): same value in config/rules.yaml and WS5's R09.
CANARY_TOKEN = "KALLANG-INTERNAL-CANARY-9f3a"

_DOCUMENT_PLACEHOLDER = "__DOCUMENT__"
_CANARY_PLACEHOLDER = "__CANARY__"


def load_prompt_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_prompt(
    template: str,
    *,
    document: str,
    canary: str = CANARY_TOKEN,
) -> str:
    """Fill the template. Both placeholders must be present or rendering raises."""
    missing = [
        name
        for name, placeholder in (
            ("document", _DOCUMENT_PLACEHOLDER),
            ("canary", _CANARY_PLACEHOLDER),
        )
        if placeholder not in template
    ]
    if missing:
        raise ValueError(f"prompt template is missing placeholders: {', '.join(missing)}")
    return template.replace(_CANARY_PLACEHOLDER, canary).replace(_DOCUMENT_PLACEHOLDER, document)


def page_text_block(page_texts: tuple[str, ...]) -> str:
    """Join per-page reading-order text into one document block for the prompt."""
    if not page_texts:
        return ""
    return "\n\n".join(f"--- PAGE {i} ---\n{text}" for i, text in enumerate(page_texts, start=1))
