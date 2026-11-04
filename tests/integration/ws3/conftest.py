from pathlib import Path

import pytest

from invoiceflow.contracts import LLMMode
from invoiceflow.extract import ModelConfig
from invoiceflow.pipeline.golden import load_golden


@pytest.fixture(scope="session")
def golden():
    return load_golden()


@pytest.fixture(scope="session")
def clean(golden):
    return golden.by_sha(golden.fixtures[0].sha256)


@pytest.fixture
def config(tmp_path):
    return ModelConfig(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="gemma4:12b",
        fallback_model="qwen3-vl:4b",
        think=False,
        keep_alive="30m",
        options={"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048},
        context_warning_ratio=0.9,
        images_mode="auto",
        page_dpi=150,
        mode=LLMMode.LIVE,
        cache_dir=tmp_path / "cache",
        prompt_path=Path("prompts/extract_v1.md"),
    )
