"""Live-Ollama acceptance tests. Marked ``ollama`` so ``make test`` skips them when
Ollama is not reachable; run explicitly with ``pytest -m ollama``.
"""

import httpx
import pdfplumber
import pytest

from invoiceflow.contracts import DocType, ExtractionRequest
from invoiceflow.extract import ExtractionRecorder, OllamaClient, ReplayClient

OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def _ollama_reachable() -> bool:
    try:
        httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.ollama,
    pytest.mark.skipif(not _ollama_reachable(), reason="Ollama not reachable on 127.0.0.1:11434"),
]


def _request(clean):
    """Build a request the way WS2's real PDF text extractor will: reading-order text."""
    with pdfplumber.open(clean.pdf_path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    return ExtractionRequest(doc_id=clean.doc_id, page_texts=(text,))


@pytest.mark.ollama
def test_golden_extracts_correctly_against_live_model(clean, config):
    client = OllamaClient(config, recorder=ExtractionRecorder(config.cache_dir))
    result = client.extract(_request(clean))
    assert result.valid, result.error
    assert result.extraction is not None
    extraction = result.extraction
    truth = clean.truth.printed
    assert extraction.document_type is DocType.TAX_INVOICE
    assert extraction.title == truth.title
    assert extraction.invoice_number == truth.invoice_number
    assert extraction.invoice_date == truth.invoice_date
    assert extraction.due_date == truth.due_date
    assert extraction.supplier_name == truth.supplier_name
    assert extraction.supplier_uen == truth.supplier_uen
    assert extraction.subtotal == truth.subtotal
    assert extraction.gst_amount == truth.gst_amount
    assert extraction.total == truth.total
    assert len(extraction.line_items) == len(truth.line_items)
    assert [item.amount for item in extraction.line_items] == [
        item.amount for item in truth.line_items
    ]


@pytest.mark.ollama
def test_two_identical_calls_return_identical_output(clean, config):
    client = OllamaClient(config, recorder=ExtractionRecorder(config.cache_dir))
    request = _request(clean)
    first = client.extract(request)
    second = client.extract(request)
    assert first.raw_output == second.raw_output
    assert first.extraction == second.extraction


@pytest.mark.ollama
def test_replay_works_with_ollama_stopped(clean, config):
    recorder = ExtractionRecorder(config.cache_dir)
    request = _request(clean)
    recorded = OllamaClient(config, recorder=recorder).extract(request)

    # ReplayClient never opens a socket; it reads the recorded cache entry back.
    replayed = ReplayClient(config, recorder=recorder).extract(request)
    assert replayed.valid
    assert replayed.raw_output == recorded.raw_output
    assert replayed.extraction == recorded.extraction
    assert replayed.model_digest == recorded.model_digest
