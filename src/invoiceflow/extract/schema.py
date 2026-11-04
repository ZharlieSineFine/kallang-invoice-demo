"""The structured-output JSON schema for :class:`~invoiceflow.contracts.InvoiceExtraction`.

Ollama 0.40 accepts Pydantic's ``$defs``/``$ref`` form, but older servers reject references,
so :func:`inline_schema` is provided and exercised to keep the client portable.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from invoiceflow.contracts import InvoiceExtraction

_SCHEMA_NAME = "invoice_extraction"


def schema_name() -> str:
    """The name registered for the schema (used by OpenAI's ``response_format``)."""
    return _SCHEMA_NAME


def extraction_schema() -> dict[str, Any]:
    """Pydantic's JSON schema for ``InvoiceExtraction`` (what the model must return)."""
    return InvoiceExtraction.model_json_schema()


def output_schema() -> dict[str, Any]:
    """The schema actually sent to the model: every field ``required`` (and nullable).

    Pydantic marks every ``InvoiceExtraction`` field optional (it defaults to ``None``), so a
    model given the bare schema is free to omit keys and, in practice, skips fields. Requiring
    each key — while still allowing ``null`` — forces the model to consider every field, and
    the result still validates against the all-optional contract model.
    """
    schema = extraction_schema()
    return {**schema, "required": list(schema["properties"].keys())}


def _resolve(node: Any, defs: Mapping[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            key = ref.rsplit("/", 1)[-1]
            return _resolve(deepcopy(defs[key]), defs)
        return {k: _resolve(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(item, defs) for item in node]
    return node


def inline_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``schema`` with every ``$ref`` inlined and ``$defs`` dropped."""
    defs = dict(schema.get("$defs", {}))
    defs.update(dict(schema.get("definitions", {})))
    out = _resolve(dict(schema), defs)
    out.pop("$defs", None)
    out.pop("definitions", None)
    return out
