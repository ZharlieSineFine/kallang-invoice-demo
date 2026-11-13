import json
import logging
from uuid import uuid4

import httpx
import pytest

from invoiceflow.contracts import ExtractionRequest, LLMMode
from invoiceflow.extract import (
    CacheMiss,
    ExtractionRecorder,
    OllamaClient,
    OpenAICompatClient,
    ReplayClient,
    build_client,
    context_warning_triggered,
    ns_to_ms,
)

VALID_RAW = '{"title": "TAX INVOICE", "invoice_number": "SAV-2026-0412"}'
DIGEST = "c7597fc90b86aff6965317f37dd5465402284e26382d9b4bf2dfe3ef1491f4b6"


def _ollama_response(content, prompt_eval_count=10, eval_count=20):
    return {
        "model": "gemma4:12b",
        "done": True,
        "done_reason": "stop",
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "prompt_eval_duration": 1000,
        "eval_duration": 2000,
        "total_duration": 3000,
        "load_duration": 0,
    }


def _ollama_client(config, responses, prompt_template):
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": config.model, "digest": DIGEST}]})
        return httpx.Response(200, json=responses.pop(0))

    return OllamaClient(
        config,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        prompt_template=prompt_template,
    )


def _request(**overrides):
    base = {"doc_id": uuid4(), "page_texts": ("SAV-2026-0412",)}
    base.update(overrides)
    return ExtractionRequest(**base)


class TestOllamaClient:
    def test_extract_returns_valid_result_and_records(self, config, prompt_template):
        client = _ollama_client(config, [_ollama_response(VALID_RAW)], prompt_template)
        result = client.extract(_request())
        assert result.valid
        assert result.extraction.invoice_number == "SAV-2026-0412"
        assert result.model == "gemma4:12b"
        assert result.model_digest == DIGEST
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20
        assert result.latency_ms is not None
        assert result.mode is LLMMode.LIVE
        assert result.schema_version == "extraction-v1"
        assert result.prompt_version == "extract-v1"
        assert result.params["num_ctx"] == 8192
        assert list(config.cache_dir.glob("*.json"))

    def _keep_alive_sent(self, config, prompt_template, loaded_bytes):
        """Run one extraction per reported size; return each keep_alive sent and the paths hit."""
        sizes = list(loaded_bytes)
        sent, paths = [], []

        def handler(request):
            paths.append(request.url.path)
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": []})
            if request.url.path == "/api/ps":
                size = sizes.pop(0)
                if size is None:
                    return httpx.Response(500)
                return httpx.Response(200, json={"models": [{"name": config.model, "size": size}]})
            sent.append(json.loads(request.content)["keep_alive"])
            return httpx.Response(200, json=_ollama_response(VALID_RAW))

        client = OllamaClient(
            config,
            http=httpx.Client(transport=httpx.MockTransport(handler)),
            prompt_template=prompt_template,
        )
        for _ in loaded_bytes:
            client.extract(_request())
        return sent, paths

    def test_a_model_grown_past_the_limit_is_unloaded_after_the_request(
        self, make_config, prompt_template
    ):
        config = make_config(keep_alive="30m", unload_above_gb=11.0)
        sent, _ = self._keep_alive_sent(
            config, prompt_template, [8_000_000_000, 11_500_000_000, 7_700_000_000]
        )
        assert sent == ["30m", 0, "30m"]

    def test_unknown_model_size_never_blocks_an_extraction(self, make_config, prompt_template):
        config = make_config(keep_alive="30m", unload_above_gb=11.0)
        sent, _ = self._keep_alive_sent(config, prompt_template, [None])
        assert sent == ["30m"]

    def test_model_size_is_not_checked_when_the_limit_is_off(self, make_config, prompt_template):
        config = make_config(keep_alive="30m")
        sent, paths = self._keep_alive_sent(config, prompt_template, [20_000_000_000])
        assert sent == ["30m"]
        assert "/api/ps" not in paths

    def test_request_payload_sets_format_think_and_num_ctx(self, config, prompt_template):
        captured = {}

        def handler(request):
            if request.url.path == "/api/tags":
                return httpx.Response(
                    200, json={"models": [{"name": config.model, "digest": DIGEST}]}
                )
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_ollama_response(VALID_RAW))

        client = OllamaClient(
            config,
            http=httpx.Client(transport=httpx.MockTransport(handler)),
            prompt_template=prompt_template,
        )
        client.extract(_request())
        payload = captured["payload"]
        assert payload["think"] is False
        assert payload["stream"] is False
        assert payload["options"]["num_ctx"] == 8192
        assert payload["options"]["num_predict"] == 2048
        assert payload["options"]["temperature"] == 0
        assert payload["options"]["seed"] == 42
        assert payload["format"]["type"] == "object"
        assert "$ref" not in json.dumps(payload["format"])
        assert "invoice_number" in payload["format"]["required"]

    def test_parser_reads_only_content_and_ignores_thinking(self, config, prompt_template):
        response = _ollama_response(VALID_RAW)
        response["message"]["thinking"] = "hidden reasoning that must not leak"
        client = _ollama_client(config, [response], prompt_template)
        result = client.extract(_request())
        assert result.raw_output == VALID_RAW
        assert "hidden reasoning" not in result.raw_output

    def test_retries_once_then_succeeds(self, config, prompt_template):
        responses = [_ollama_response("not json"), _ollama_response(VALID_RAW)]
        client = _ollama_client(config, responses, prompt_template)
        result = client.extract(_request())
        assert result.valid
        assert responses == []

    def test_marks_invalid_after_two_failures(self, config, prompt_template):
        responses = [_ollama_response("nope"), _ollama_response("still nope")]
        client = _ollama_client(config, responses, prompt_template)
        result = client.extract(_request())
        assert result.valid is False
        assert result.extraction is None
        assert result.error

    def test_context_warning_fires_at_90_percent(self, config, prompt_template, caplog):
        client = _ollama_client(
            config, [_ollama_response(VALID_RAW, prompt_eval_count=8000)], prompt_template
        )
        with caplog.at_level(logging.WARNING, logger="invoiceflow.extract"):
            client.extract(_request())
        assert any("num_ctx" in message for message in caplog.messages)

    def test_no_context_warning_below_threshold(self, config, prompt_template, caplog):
        client = _ollama_client(
            config, [_ollama_response(VALID_RAW, prompt_eval_count=10)], prompt_template
        )
        with caplog.at_level(logging.WARNING, logger="invoiceflow.extract"):
            client.extract(_request())
        assert not any("num_ctx" in message for message in caplog.messages)

    def test_sends_images_as_base64(self, config, prompt_template, tmp_path):
        image = tmp_path / "page.png"
        image.write_bytes(b"\x89PNG image")
        captured = {}

        def handler(request):
            if request.url.path == "/api/tags":
                return httpx.Response(
                    200, json={"models": [{"name": config.model, "digest": DIGEST}]}
                )
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_ollama_response(VALID_RAW))

        client = OllamaClient(
            config,
            http=httpx.Client(transport=httpx.MockTransport(handler)),
            prompt_template=prompt_template,
        )
        client.extract(_request(image_paths=(str(image),)))
        message = captured["payload"]["messages"][0]
        assert message["images"] == ["iVBORyBpbWFnZQ=="]  # base64 of b"\x89PNG image"


class TestReplayClient:
    def test_replay_returns_recorded_result(self, config, prompt_template):
        live = _ollama_client(config, [_ollama_response(VALID_RAW)], prompt_template)
        request = _request()
        recorded = live.extract(request)

        replay = ReplayClient(config, recorder=ExtractionRecorder(config.cache_dir))
        replayed = replay.extract(request)
        assert replayed.valid
        assert replayed.raw_output == recorded.raw_output
        assert replayed.extraction == recorded.extraction
        assert replayed.mode is LLMMode.REPLAY
        assert replayed.doc_id == request.doc_id
        assert replayed.model == recorded.model

    def test_replay_works_without_network(self, config, prompt_template):
        live = _ollama_client(config, [_ollama_response(VALID_RAW)], prompt_template)
        request = _request()
        live.extract(request)

        replay = ReplayClient(config, recorder=ExtractionRecorder(config.cache_dir))
        assert replay.extract(request).valid

    def test_replay_missing_raises_cache_miss(self, config):
        with pytest.raises(CacheMiss):
            ReplayClient(config).extract(_request())


class TestOpenAICompatClient:
    def test_uses_json_schema_response_format(
        self, config, make_config, monkeypatch, prompt_template
    ):
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-deploy")
        azure = make_config(
            provider="azure",
            azure={
                "endpoint_env": "AZURE_OPENAI_ENDPOINT",
                "api_key_env": "AZURE_OPENAI_API_KEY",
                "deployment_env": "AZURE_OPENAI_DEPLOYMENT",
            },
        )
        captured = {}

        def handler(request):
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": VALID_RAW}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 9},
                },
            )

        client = OpenAICompatClient(
            azure,
            http=httpx.Client(transport=httpx.MockTransport(handler)),
            prompt_template=prompt_template,
        )
        result = client.extract(_request())
        assert result.valid
        assert result.model == "gpt-deploy"
        assert result.prompt_tokens == 7
        assert result.completion_tokens == 9
        assert captured["headers"]["api-key"] == "test-key"
        assert "gpt-deploy" in captured["url"]
        response_format = captured["body"]["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["name"] == "invoice_extraction"
        assert response_format["json_schema"]["schema"]["type"] == "object"


def test_context_warning_triggered():
    assert context_warning_triggered(7373, 8192, 0.9)
    assert not context_warning_triggered(7372, 8192, 0.9)
    assert not context_warning_triggered(None, 8192, 0.9)


def test_ns_to_ms():
    assert ns_to_ms(3_000_000) == 3
    assert ns_to_ms(None) is None


def test_build_client_selects(config, make_config):
    assert isinstance(build_client(config), OllamaClient)
    assert isinstance(build_client(make_config(mode=LLMMode.REPLAY)), ReplayClient)
    assert isinstance(build_client(make_config(provider="azure")), OpenAICompatClient)
