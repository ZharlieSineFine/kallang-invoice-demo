"""LLM clients behind the ``LLMClient`` protocol: live Ollama, OpenAI-compatible, replay.

- :class:`OllamaClient` calls the native ``/api/chat`` with ``format`` set to the
  ``InvoiceExtraction`` schema, ``think`` off, deterministic sampling, and an explicit
  ``num_ctx`` on every call.
- :class:`OpenAICompatClient` is the same interface over ``response_format``/``json_schema``
  (Azure OpenAI later; not used in the demo).
- :class:`ReplayClient` replays recorded responses so the demo works with Ollama stopped.

All clients validate with Pydantic and retry once with the error message before marking a
result invalid.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from invoiceflow.contracts import (
    SCHEMA_VERSION,
    ExtractionRequest,
    ExtractionResult,
    InvoiceExtraction,
    LLMMode,
)
from invoiceflow.extract.cache import CacheEntry, CacheMiss, ExtractionRecorder, cache_key
from invoiceflow.extract.config import ModelConfig
from invoiceflow.extract.images import encode_image_base64, image_hashes, select_images
from invoiceflow.extract.prompt import (
    PROMPT_VERSION,
    load_prompt_template,
    page_text_block,
    render_prompt,
)
from invoiceflow.extract.schema import inline_schema, output_schema, schema_name
from invoiceflow.extract.validation import validate_output

logger = logging.getLogger("invoiceflow.extract")


def ns_to_ms(nanoseconds: int | None) -> int | None:
    return None if nanoseconds is None else round(nanoseconds / 1_000_000)


def context_warning_triggered(prompt_tokens: int | None, num_ctx: int, ratio: float) -> bool:
    """True when a prompt used ``ratio`` (e.g. 0.9) or more of ``num_ctx``."""
    if prompt_tokens is None:
        return False
    return prompt_tokens >= num_ctx * ratio


def context_warning_message(prompt_tokens: int, num_ctx: int, ratio: float) -> str:
    return (
        f"prompt used {prompt_tokens} tokens, {ratio:.0%} of num_ctx {num_ctx}; "
        "consider a smaller page or a larger num_ctx"
    )


def request_params(config: ModelConfig, image_paths: tuple[str, ...]) -> dict[str, Any]:
    """The parameters a call was made with; recorded and part of the replay key."""
    return {
        "temperature": config.temperature,
        "seed": config.seed,
        "num_ctx": config.num_ctx,
        "num_predict": config.num_predict,
        "think": config.think,
        "images_mode": config.images_mode,
        "n_images": len(image_paths),
    }


_BYTES_PER_GB = 1_000_000_000


class _BaseClient:
    """Shared orchestration: build the request, call, validate, retry once, record."""

    def __init__(
        self,
        config: ModelConfig,
        *,
        recorder: ExtractionRecorder | None = None,
        http: httpx.Client | None = None,
        prompt_template: str | None = None,
    ):
        self.config = config
        self.recorder = recorder or ExtractionRecorder(config.cache_dir)
        self._http = http
        self._prompt_template = (
            load_prompt_template(config.prompt_path) if prompt_template is None else prompt_template
        )

    # -- subclasses ---------------------------------------------------------

    def model_name(self) -> str:
        raise NotImplementedError

    def model_digest(self) -> str | None:
        return None

    def _messages(
        self, document: str, image_paths: tuple[str, ...], *, error_hint: str | None = None
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _call(self, messages: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    # -- shared -------------------------------------------------------------

    def _http_client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=httpx.Timeout(600.0))
        return self._http

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        document = page_text_block(request.page_texts)
        image_paths = select_images(self.config.images_mode, request.image_paths)
        params = request_params(self.config, image_paths)
        key = cache_key(
            model=self.model_name(),
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            page_texts=request.page_texts,
            image_hashes=image_hashes(image_paths),
            params=params,
        )
        raw, stats, extraction, error = self._attempt(document, image_paths)
        result = ExtractionResult(
            extraction_id=uuid4(),
            doc_id=request.doc_id,
            model=self.model_name(),
            model_digest=self.model_digest(),
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            params=params,
            mode=LLMMode.LIVE,
            raw_output=raw,
            extraction=extraction,
            valid=extraction is not None,
            error=error,
            prompt_tokens=stats.get("prompt_eval_count"),
            completion_tokens=stats.get("eval_count"),
            latency_ms=stats.get("latency_ms"),
            created_at=datetime.now(UTC),
        )
        self._record(result, key, stats)
        return result

    def _attempt(
        self, document: str, image_paths: tuple[str, ...]
    ) -> tuple[str, dict[str, Any], InvoiceExtraction | None, str | None]:
        """Call once, then retry once with the validation error if the output is invalid."""
        messages = self._messages(document, image_paths)
        raw, stats = self._call(messages)
        extraction, error = validate_output(raw)
        if extraction is None:
            messages = self._messages(document, image_paths, error_hint=error)
            raw, stats = self._call(messages)
            extraction, error = validate_output(raw)
        return raw, stats, extraction, error

    def _record(self, result: ExtractionResult, key: str, stats: dict[str, Any]) -> None:
        warning = context_warning_triggered(
            result.prompt_tokens, self.config.num_ctx, self.config.context_warning_ratio
        )
        if warning and result.prompt_tokens is not None:
            logger.warning(
                context_warning_message(
                    result.prompt_tokens, self.config.num_ctx, self.config.context_warning_ratio
                )
            )
        self.recorder.save(
            CacheEntry(
                key=key,
                result=result.model_dump(mode="json"),
                durations={
                    "prompt_eval_duration_ns": stats.get("prompt_eval_duration"),
                    "eval_duration_ns": stats.get("eval_duration"),
                    "total_duration_ns": stats.get("total_duration"),
                    "load_duration_ns": stats.get("load_duration"),
                    "done_reason": stats.get("done_reason"),
                    "prompt_eval_cached_count": stats.get("prompt_eval_cached_count"),
                },
                context_warning=warning,
            )
        )


class OllamaClient(_BaseClient):
    """Live client for Ollama's native ``/api/chat``."""

    def model_name(self) -> str:
        return self.config.model

    def model_digest(self) -> str | None:
        if not hasattr(self, "_digest"):
            self._digest = self._fetch_digest()
        return self._digest

    def _fetch_digest(self) -> str | None:
        try:
            response = self._http_client().get(f"{self.config.base_url}/api/tags")
            response.raise_for_status()
            for model in response.json().get("models", []):
                if model.get("name") == self.config.model:
                    return model.get("digest")
        except httpx.HTTPError as exc:
            logger.warning("could not read model digest from /api/tags: %s", exc)
        return None

    def _messages(
        self, document: str, image_paths: tuple[str, ...], *, error_hint: str | None = None
    ) -> list[dict[str, Any]]:
        content = render_prompt(self._prompt_template, document=document)
        if error_hint:
            content += (
                f"\n\nYour previous output was invalid: {error_hint}\n"
                "Return a corrected JSON object matching the schema."
            )
        message: dict[str, Any] = {"role": "user", "content": content}
        if image_paths:
            # Ollama passes images as base64 in the message's images list (the Gemma 4
            # model page recommends the page image come before the text).
            message["images"] = [encode_image_base64(path) for path in image_paths]
        return [message]

    def _loaded_gb(self) -> float:
        """The memory Ollama reports for this model right now; 0.0 when it cannot be read."""
        try:
            response = self._http_client().get(f"{self.config.base_url}/api/ps")
            response.raise_for_status()
            models = response.json().get("models", [])
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("could not read the loaded model size from /api/ps: %s", exc)
            return 0.0
        sizes = (model.get("size", 0) for model in models if model.get("name") == self.config.model)
        return next(sizes, 0) / _BYTES_PER_GB

    def _keep_alive(self) -> str | int:
        """The configured keep-alive, or 0 to unload the model once this request is answered.

        Ollama's runner for this model grows by about 1 GB with every request it serves, and
        a long batch pushes a 16 GB Mac into swap until requests stop returning. A model that
        is unloaded and loaded again starts from its base size. The size comes from Ollama on
        every call because Airflow runs each invoice in its own process, so a counter kept
        here would never reach its limit.
        """
        limit = self.config.unload_above_gb
        if limit > 0 and self._loaded_gb() >= limit:
            return 0
        return self.config.keep_alive

    def _call(self, messages: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        payload = {
            "model": self.config.model,
            "stream": False,
            "format": inline_schema(output_schema()),
            "think": self.config.think,
            "keep_alive": self._keep_alive(),
            "options": self.config.options_for_call(),
            "messages": messages,
        }
        started = time.perf_counter()
        response = self._http_client().post(f"{self.config.base_url}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        content = (data.get("message") or {}).get("content") or ""
        stats = {
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
            "prompt_eval_duration": data.get("prompt_eval_duration"),
            "eval_duration": data.get("eval_duration"),
            "total_duration": data.get("total_duration"),
            "load_duration": data.get("load_duration"),
            "done_reason": data.get("done_reason"),
            "prompt_eval_cached_count": data.get("prompt_eval_cached_count"),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
        return content, stats


class OpenAICompatClient(_BaseClient):
    """OpenAI-compatible chat completions with ``response_format``/``json_schema``.

    Reads endpoint, key, and deployment from the environment variables named in
    ``config/models.yaml`` (Azure OpenAI later). Not used in the demo.
    """

    def __init__(
        self,
        config: ModelConfig,
        *,
        recorder: ExtractionRecorder | None = None,
        http: httpx.Client | None = None,
        prompt_template: str | None = None,
        api_version: str = "2024-08-01-preview",
    ):
        super().__init__(config, recorder=recorder, http=http, prompt_template=prompt_template)
        azure = dict(config.azure)
        self.endpoint = os.environ.get(azure.get("endpoint_env", ""), "")
        self.api_key = os.environ.get(azure.get("api_key_env", ""), "")
        self.deployment = os.environ.get(azure.get("deployment_env", ""), "") or config.model
        self.api_version = api_version

    def model_name(self) -> str:
        return self.deployment

    def _url(self) -> str:
        base = self.endpoint.rstrip("/")
        return (
            f"{base}/openai/deployments/{self.deployment}/chat/completions"
            f"?api-version={self.api_version}"
        )

    def _messages(
        self, document: str, image_paths: tuple[str, ...], *, error_hint: str | None = None
    ) -> list[dict[str, Any]]:
        content = render_prompt(self._prompt_template, document=document)
        if error_hint:
            content += (
                f"\n\nYour previous output was invalid: {error_hint}\n"
                "Return a corrected JSON object matching the schema."
            )
        parts: list[dict[str, Any]] = [{"type": "text", "text": content}]
        for path in image_paths:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encode_image_base64(path)}"},
                }
            )
        return [{"role": "user", "content": parts}]

    def _call(self, messages: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        payload = {
            "model": self.deployment,
            "messages": messages,
            "temperature": self.config.temperature,
            "seed": self.config.seed,
            "max_tokens": self.config.num_predict,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name(),
                    "schema": output_schema(),
                    "strict": False,
                },
            },
        }
        started = time.perf_counter()
        response = self._http_client().post(
            self._url(), json=payload, headers={"api-key": self.api_key}
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        stats = {
            "prompt_eval_count": usage.get("prompt_tokens"),
            "eval_count": usage.get("completion_tokens"),
            "prompt_eval_duration": None,
            "eval_duration": None,
            "total_duration": None,
            "load_duration": None,
            "done_reason": data["choices"][0].get("finish_reason"),
            "prompt_eval_cached_count": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
        return content, stats


class ReplayClient:
    """Replays recorded responses from ``data/llm_cache/``; never calls the model."""

    def __init__(self, config: ModelConfig, *, recorder: ExtractionRecorder | None = None):
        self.config = config
        self.recorder = recorder or ExtractionRecorder(config.cache_dir)

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        image_paths = select_images(self.config.images_mode, request.image_paths)
        key = cache_key(
            model=self.config.model,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            page_texts=request.page_texts,
            image_hashes=image_hashes(image_paths),
            params=request_params(self.config, image_paths),
        )
        entry = self.recorder.load(key)
        if entry is None:
            raise CacheMiss(
                f"no recorded response for cache key {key} (run live once to record it)"
            )
        result = ExtractionResult.model_validate(dict(entry.result))
        return result.model_copy(update={"doc_id": request.doc_id, "mode": LLMMode.REPLAY})


def build_client(config: ModelConfig, *, recorder: ExtractionRecorder | None = None) -> object:
    """The client the config selects: replay when ``LLM_MODE=replay``, else the provider."""
    if config.mode is LLMMode.REPLAY:
        return ReplayClient(config, recorder=recorder)
    if config.provider in ("openai", "azure"):
        return OpenAICompatClient(config, recorder=recorder)
    return OllamaClient(config, recorder=recorder)
