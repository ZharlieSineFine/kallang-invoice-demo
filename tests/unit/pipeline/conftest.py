import pytest

from invoiceflow.pipeline.golden import load_golden


@pytest.fixture(scope="session")
def golden():
    return load_golden()


@pytest.fixture(scope="session")
def clean(golden):
    return golden.by_sha(golden.fixtures[0].sha256)


@pytest.fixture(scope="session")
def mismatch(golden):
    return next(f for f in golden.fixtures if f.fixture_id == "golden-a-total-mismatch")


@pytest.fixture(autouse=True)
def replay_recorded_answers(monkeypatch):
    """Use the recorded model answers. Live mode (the .env default) would call the model and
    rewrite the tracked files in data/llm_cache/ on every test run."""
    monkeypatch.setenv("LLM_MODE", "replay")
