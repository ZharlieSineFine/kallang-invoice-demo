"""WS3: model extraction. Live (Ollama), replay (cache), and OpenAI-compatible clients."""

from invoiceflow.extract.cache import CacheEntry, CacheMiss, ExtractionRecorder, cache_key
from invoiceflow.extract.clients import (
    OllamaClient,
    OpenAICompatClient,
    ReplayClient,
    build_client,
    context_warning_message,
    context_warning_triggered,
    ns_to_ms,
    request_params,
)
from invoiceflow.extract.config import IMAGES_MODES, ModelConfig, load_model_config
from invoiceflow.extract.images import encode_image_base64, image_hashes, select_images
from invoiceflow.extract.prompt import (
    CANARY_TOKEN,
    PROMPT_VERSION,
    load_prompt_template,
    page_text_block,
    render_prompt,
)
from invoiceflow.extract.schema import extraction_schema, inline_schema, output_schema, schema_name
from invoiceflow.extract.validation import extract_json_object, validate_output

__all__ = [
    "CANARY_TOKEN",
    "IMAGES_MODES",
    "PROMPT_VERSION",
    "CacheEntry",
    "CacheMiss",
    "ExtractionRecorder",
    "ModelConfig",
    "OllamaClient",
    "OpenAICompatClient",
    "ReplayClient",
    "build_client",
    "cache_key",
    "context_warning_message",
    "context_warning_triggered",
    "encode_image_base64",
    "extract_json_object",
    "extraction_schema",
    "image_hashes",
    "inline_schema",
    "load_model_config",
    "load_prompt_template",
    "ns_to_ms",
    "output_schema",
    "page_text_block",
    "render_prompt",
    "request_params",
    "schema_name",
    "select_images",
    "validate_output",
]
