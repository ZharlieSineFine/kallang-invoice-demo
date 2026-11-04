"""Replay cache: recorded model responses under ``data/llm_cache/``.

Each response is keyed by a SHA-256 over the model, prompt version, schema version, the
input text, the page-image hashes, and the request parameters. The same request always
maps to the same key, so replays are byte-for-byte reproducible.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from invoiceflow.settings import repo_root


class CacheMiss(LookupError):
    """A replay was requested but no recorded response exists for the key."""


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def cache_key(
    *,
    model: str,
    prompt_version: str,
    schema_version: str,
    page_texts: tuple[str, ...],
    image_hashes: tuple[str, ...],
    params: Mapping[str, Any],
) -> str:
    """Deterministic cache key for one request. Image *hashes*, not raw bytes, go in."""
    payload = {
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "page_texts": list(page_texts),
        "image_hashes": list(image_hashes),
        "params": _canonical(dict(params)),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheEntry:
    """One recorded response: the full ExtractionResult plus stats the contract drops."""

    key: str
    result: Mapping[str, Any]  # ExtractionResult.model_dump(mode="json"), mode as recorded
    durations: Mapping[str, Any]  # ns durations, done_reason, cached prompt tokens
    context_warning: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "result": dict(self.result),
            "durations": dict(self.durations),
            "context_warning": self.context_warning,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CacheEntry:
        return cls(
            key=str(payload["key"]),
            result=dict(payload["result"]),
            durations=dict(payload.get("durations", {})),
            context_warning=bool(payload.get("context_warning", False)),
        )


class ExtractionRecorder:
    """Reads and writes one JSON file per cache key under the cache directory."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or (repo_root() / "data" / "llm_cache")

    def path_for(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def save(self, entry: CacheEntry) -> Path:
        path = self.path_for(entry.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(entry.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def load(self, key: str) -> CacheEntry | None:
        path = self.path_for(key)
        if not path.is_file():
            return None
        return CacheEntry.from_dict(json.loads(path.read_text(encoding="utf-8")))
