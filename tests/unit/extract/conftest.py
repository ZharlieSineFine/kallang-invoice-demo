from pathlib import Path

import pytest

from invoiceflow.contracts import LLMMode
from invoiceflow.extract import ModelConfig

TEMPLATE = "Doc:\n__DOCUMENT__\n\nCanary token: __CANARY__\n"


@pytest.fixture
def prompt_template() -> str:
    return TEMPLATE


@pytest.fixture
def make_config(tmp_path):
    def _make(**overrides):
        defaults = {
            "provider": "ollama",
            "base_url": "http://ollama.test",
            "model": "gemma4:12b",
            "fallback_model": "qwen3-vl:4b",
            "think": False,
            "keep_alive": "0",
            "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048},
            "context_warning_ratio": 0.9,
            "images_mode": "auto",
            "page_dpi": 150,
            "mode": LLMMode.LIVE,
            "cache_dir": tmp_path / "cache",
            "prompt_path": Path("prompts/extract_v1.md"),
        }
        defaults.update(overrides)
        return ModelConfig(**defaults)

    return _make


@pytest.fixture
def config(make_config):
    return make_config()
