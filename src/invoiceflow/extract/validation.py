"""Validate the model's raw output against the InvoiceExtraction contract.

The model is asked for JSON only, but it may still wrap it in prose or code fences, so we
extract the JSON object before Pydantic validation. On failure the caller retries once with
the returned error message.
"""

from __future__ import annotations

from pydantic import ValidationError

from invoiceflow.contracts import InvoiceExtraction


def extract_json_object(text: str) -> str:
    """Best-effort extraction of the JSON object from a model reply.

    Strips surrounding whitespace and code fences, then takes everything from the first
    ``{`` to the last ``}``. Returns the input unchanged when there is nothing to extract,
    so the validation error below names the real problem.
    """
    content = text.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return content
    return content[start : end + 1]


def _format_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for error in exc.errors()[:10]:
            loc = ".".join(str(part) for part in error["loc"]) or "<root>"
            parts.append(f"{loc}: {error['msg']}")
        if parts:
            return "; ".join(parts)
    return str(exc)


def validate_output(raw: str) -> tuple[InvoiceExtraction | None, str | None]:
    """Return ``(extraction, None)`` on success, ``(None, message)`` on failure."""
    json_text = extract_json_object(raw)
    try:
        return InvoiceExtraction.model_validate_json(json_text), None
    except (ValidationError, ValueError) as exc:
        return None, _format_error(exc)
