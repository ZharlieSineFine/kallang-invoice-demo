import pytest

from invoiceflow.contracts import LLMMode
from invoiceflow.extract import load_model_config


def test_load_model_config_matches_yaml():
    c = load_model_config()
    assert c.provider == "ollama"
    assert c.model == "gemma4:12b"
    assert c.fallback_model == "qwen3-vl:4b"
    assert c.think is False
    assert c.num_ctx == 8192
    assert c.num_predict == 2048
    assert c.temperature == 0
    assert c.seed == 42
    assert c.images_mode == "auto"
    assert c.page_dpi == 150
    assert c.context_warning_ratio == 0.9
    assert c.mode is LLMMode.LIVE
    assert c.prompt_path.name == "extract_v1.md"
    assert c.cache_dir.name == "llm_cache"
    assert c.azure["api_key_env"] == "AZURE_OPENAI_API_KEY"


def test_mode_env_replay(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "replay")
    assert load_model_config().mode is LLMMode.REPLAY


def test_mode_env_invalid(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "bogus")
    with pytest.raises(ValueError, match="LLM_MODE"):
        load_model_config()


def test_base_url_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://elsewhere:1234")
    assert load_model_config().base_url == "http://elsewhere:1234"


def test_options_for_call_always_includes_num_ctx(make_config):
    opts = make_config().options_for_call()
    assert opts["num_ctx"] == 8192
    assert opts["num_predict"] == 2048
    assert opts["temperature"] == 0
    assert opts["seed"] == 42


def test_config_is_frozen(make_config):
    c = make_config()
    with pytest.raises(AttributeError):
        c.model = "other"  # type: ignore[misc]


def test_unload_limit_comes_from_yaml():
    # The Ollama runner grows with every request on the demo Mac, so the limit must stay on.
    assert load_model_config().unload_above_gb > 0


def test_unload_limit_defaults_to_off(make_config):
    assert make_config().unload_above_gb == 0
