"""Benchmark writes its files: latency CSV, memory JSON, and raw outputs.

Run with a fake client so no Ollama is needed — the file-writing path is what we check.
"""

import importlib.util
import sys
from datetime import UTC, datetime
from uuid import uuid4

from invoiceflow.contracts import ExtractionRequest, ExtractionResult, InvoiceExtraction, LLMMode
from invoiceflow.settings import golden_dir, repo_root


def _load_bench():
    path = repo_root() / "scripts" / "bench_models.py"
    spec = importlib.util.spec_from_file_location("bench_models", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look themselves up in sys.modules
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        return ExtractionResult(
            extraction_id=uuid4(),
            doc_id=request.doc_id,
            model="fake",
            prompt_version="extract-v1",
            schema_version="extraction-v1",
            params={},
            mode=LLMMode.LIVE,
            raw_output='{"title": "TAX INVOICE"}',
            extraction=InvoiceExtraction(title="TAX INVOICE"),
            valid=True,
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            created_at=datetime.now(UTC),
        )


def test_discover_documents_finds_golden():
    bench = _load_bench()
    docs = bench.discover_documents(golden_dir())
    assert [d.doc_id for d in docs] == ["golden-a-clean", "golden-a-total-mismatch"]


def test_benchmark_writes_its_files(config, tmp_path):
    bench = _load_bench()
    out_dir = tmp_path / "bench"
    docs = [
        bench.BenchmarkDoc(doc_id="doc-a", pdf_path=golden_dir() / "golden-a-clean" / "invoice.pdf")
    ]
    summary = bench.run_benchmark(
        config,
        docs,
        out_dir,
        modes=("text", "image"),
        dpis=(150,),
        fallback=False,
        client_factory=lambda cfg: FakeClient(),
        ps_fn=lambda: {"models": [{"name": config.model, "size": 123, "size_vram": 45}]},
        unload_fn=lambda: None,
    )

    assert summary["csv_path"].is_file()
    assert summary["memory_path"].is_file()
    rows = summary["rows"]
    assert len(rows) == 2  # text + image@150
    assert {row.mode for row in rows} == {"text", "image"}
    assert all(row.success for row in rows)
    assert rows[0].memory_bytes == 123
    assert rows[0].memory_vram_bytes == 45

    csv_text = summary["csv_path"].read_text()
    assert "latency_ms" in csv_text and "doc-a" in csv_text
    assert "memory_vram_bytes" in csv_text

    raw_files = list((out_dir / "raw").rglob("*.json"))
    assert len(raw_files) == 2
