"""Model configuration for WS3 (config/models.yaml values plus environment overrides).

The YAML file keeps the keys; this module turns them into a frozen :class:`ModelConfig`
with paths resolved against the repo root and secrets read from environment variables.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from invoiceflow.contracts import LLMMode
from invoiceflow.settings import load_config, load_env_file, repo_root

IMAGES_MODES = ("auto", "always", "never")


@dataclass(frozen=True)
class ModelConfig:
    """Resolved model settings. Frozen, so a client cannot change it after it is built."""

    provider: str
    base_url: str
    model: str
    fallback_model: str
    think: bool
    keep_alive: str
    options: Mapping[str, Any] = field(default_factory=dict)
    context_warning_ratio: float = 0.9
    images_mode: str = "auto"
    page_dpi: int = 150
    mode: LLMMode = LLMMode.LIVE
    cache_dir: Path = field(default_factory=Path)
    prompt_path: Path = field(default_factory=Path)
    azure: Mapping[str, str] = field(default_factory=dict)

    @property
    def num_ctx(self) -> int:
        return int(self.options["num_ctx"])

    @property
    def num_predict(self) -> int:
        return int(self.options["num_predict"])

    @property
    def temperature(self) -> float:
        return float(self.options["temperature"])

    @property
    def seed(self) -> int:
        return int(self.options["seed"])

    def options_for_call(self) -> dict[str, Any]:
        """The options block sent to the model on every call (always includes num_ctx)."""
        return {
            "temperature": self.temperature,
            "seed": self.seed,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
        }


def _frozen(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


def _env(name: str | None, default: str = "") -> str:
    """Read an environment variable by *name*; ``None``/empty means 'no variable'."""
    if not name:
        return default
    return os.environ.get(name, default)


def _mode_from_env(value: str | None) -> LLMMode:
    normalized = (value or "live").strip().lower()
    if normalized == "live":
        return LLMMode.LIVE
    if normalized == "replay":
        return LLMMode.REPLAY
    raise ValueError(f"LLM_MODE must be 'live' or 'replay', got {value!r}")


def load_model_config(root: Path | None = None) -> ModelConfig:
    """Read ``config/models.yaml`` and resolve environment overrides into a ModelConfig."""
    root = root or repo_root()
    load_env_file(root / ".env")
    raw = load_config("models")
    images = raw.get("images", {}) or {}
    azure = raw.get("azure", {}) or {}
    images_mode = str(images.get("mode", "auto"))
    if images_mode not in IMAGES_MODES:
        raise ValueError(f"config models.yaml images.mode must be one of {IMAGES_MODES}")
    return ModelConfig(
        provider=str(raw["provider"]),
        base_url=_env(str(raw.get("base_url_env")), str(raw.get("default_base_url", ""))),
        model=str(raw["model"]),
        fallback_model=str(raw["fallback_model"]),
        think=bool(raw.get("think", False)),
        keep_alive=str(raw.get("keep_alive", "30m")),
        options=_frozen(raw.get("options", {})),
        context_warning_ratio=float(raw.get("context_warning_ratio", 0.9)),
        images_mode=images_mode,
        page_dpi=int(images.get("page_dpi", 150)),
        mode=_mode_from_env(_env(str(raw.get("mode_env"))) or None),
        cache_dir=root / str(raw.get("cache_dir", "data/llm_cache")),
        prompt_path=root / str(raw.get("prompt", "prompts/extract_v1.md")),
        azure=_frozen({str(k): str(v) for k, v in azure.items()}),
    )
