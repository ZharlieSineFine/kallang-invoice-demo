"""Benchmark the configured extraction models (WS3: run ``make bench`` or this file).

Runs ``gemma4:12b`` in text-only and text+image modes over the benchmark documents, then
runs the fallback ``qwen3-vl:4b`` once (skipped when it is not pulled). It records real
latency, token counts, and the memory ``ollama ps`` reports, and writes:

- raw outputs under ``<out>/raw/<model>/<mode>/``
- a latency CSV at ``<out>/latency.csv``
- the ``ollama ps`` memory snapshots at ``<out>/memory.json``

Each model is unloaded (``keep_alive: 0``) before the next one loads. Because Ollama does
not expose the Gemma 4 image-token budget setting, image mode renders page images at each
requested DPI (150 and 200 by default) so the two can be compared in the CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pdfplumber
import pypdfium2

from invoiceflow.contracts import ExtractionRequest
from invoiceflow.extract import ModelConfig, OllamaClient, load_model_config
from invoiceflow.extract.cache import ExtractionRecorder
from invoiceflow.settings import repo_root


@dataclass
class BenchmarkDoc:
    doc_id: str
    pdf_path: Path


@dataclass
class BenchmarkRow:
    model: str
    mode: str  # text | image
    dpi: int | None
    doc_id: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    memory_bytes: int | None
    memory_vram_bytes: int | None
    success: bool
    error: str | None


def discover_documents(docs_dir: Path) -> list[BenchmarkDoc]:
    """One document per subfolder that contains an ``invoice.pdf``."""
    if not docs_dir.is_dir():
        return []
    found = []
    for folder in sorted(docs_dir.iterdir()):
        pdf = folder / "invoice.pdf"
        if folder.is_dir() and pdf.is_file():
            found.append(BenchmarkDoc(doc_id=folder.name, pdf_path=pdf))
    return found


def extract_text(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def render_page_image(pdf_path: Path, dpi: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{pdf_path.stem}-{dpi}dpi.png"
    if not out.exists():
        pdf = pypdfium2.PdfDocument(str(pdf_path))
        pdf[0].render(scale=dpi / 72).to_pil().save(out)
        pdf.close()
    return out


def model_is_pulled(base_url: str, model: str) -> bool:
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=10)
        response.raise_for_status()
        return any(m.get("name") == model for m in response.json().get("models", []))
    except httpx.HTTPError:
        return False


def ollama_ps(base_url: str) -> dict[str, Any]:
    response = httpx.get(f"{base_url}/api/ps", timeout=10)
    response.raise_for_status()
    return response.json()


def unload_model(base_url: str, model: str) -> None:
    httpx.post(
        f"{base_url}/api/generate",
        json={"model": model, "keep_alive": 0},
        timeout=60,
    )


def memory_bytes(ps: dict[str, Any], model: str) -> tuple[int | None, int | None]:
    for entry in ps.get("models", []):
        if entry.get("name") == model:
            return entry.get("size"), entry.get("size_vram")
    return None, None


def write_csv(rows: list[BenchmarkRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(BenchmarkRow.__dataclass_fields__))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_memory(snapshots: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshots, indent=2) + "\n", encoding="utf-8")


def _case_dir(raw_dir: Path, model: str, mode: str, dpi: int | None) -> Path:
    suffix = f"-{dpi}dpi" if dpi else ""
    return raw_dir / model / f"{mode}{suffix}"


def _run_case(
    client: Any,
    config: ModelConfig,
    doc: BenchmarkDoc,
    *,
    mode: str,
    dpi: int | None,
    raw_dir: Path,
) -> BenchmarkRow:
    """One (document, mode, dpi) call. Writes the raw result and returns the CSV row."""
    image_paths: tuple[str, ...] = ()
    if mode == "image":
        assert dpi is not None
        image_paths = (str(render_page_image(doc.pdf_path, dpi, raw_dir / "images")),)
    request = ExtractionRequest(
        doc_id=uuid4(),
        page_texts=(extract_text(doc.pdf_path),),
        image_paths=image_paths,
    )
    started = time.perf_counter()
    try:
        result = client.extract(request)
        error = result.error
        success = result.valid
        prompt_tokens = result.prompt_tokens
        completion_tokens = result.completion_tokens
    except Exception as exc:
        result = None
        error = f"{type(exc).__name__}: {exc}"
        success = False
        prompt_tokens = None
        completion_tokens = None
    latency_ms = round((time.perf_counter() - started) * 1000)
    case_dir = _case_dir(raw_dir, config.model, mode, dpi)
    case_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "doc_id": doc.doc_id,
        "model": config.model,
        "mode": mode,
        "dpi": dpi,
        "latency_ms": latency_ms,
        "success": success,
        "error": error,
        "raw_output": result.raw_output if result else None,
    }
    (case_dir / f"{doc.doc_id}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return BenchmarkRow(
        model=config.model,
        mode=mode,
        dpi=dpi,
        doc_id=doc.doc_id,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        memory_bytes=None,
        memory_vram_bytes=None,
        success=success,
        error=error,
    )


def _run_model(
    config: ModelConfig,
    docs: list[BenchmarkDoc],
    *,
    modes: tuple[str, ...],
    dpis: tuple[int, ...],
    raw_dir: Path,
    client_factory: Callable[[ModelConfig], Any],
    ps_fn: Callable[[], dict[str, Any]],
    unload_fn: Callable[[], None],
) -> tuple[list[BenchmarkRow], dict[str, Any]]:
    """Run one model across modes/dpis, snapshot memory, then unload it."""
    rows: list[BenchmarkRow] = []
    for mode in modes:
        mode_config = replace(config, images_mode="never" if mode == "text" else "always")
        client = client_factory(mode_config)
        if mode == "text":
            for doc in docs:
                rows.append(
                    _run_case(client, mode_config, doc, mode="text", dpi=None, raw_dir=raw_dir)
                )
        elif mode == "image":
            for dpi in dpis:
                for doc in docs:
                    rows.append(
                        _run_case(client, mode_config, doc, mode="image", dpi=dpi, raw_dir=raw_dir)
                    )
    ps = ps_fn()
    snapshot = {
        "model": config.model,
        "memory_bytes": memory_bytes(ps, config.model)[0],
        "memory_vram_bytes": memory_bytes(ps, config.model)[1],
        "ps": ps,
    }
    for row in rows:
        row.memory_bytes = snapshot["memory_bytes"]
        row.memory_vram_bytes = snapshot["memory_vram_bytes"]
    unload_fn()
    return rows, snapshot


def run_benchmark(
    config: ModelConfig,
    docs: list[BenchmarkDoc],
    out_dir: Path,
    *,
    modes: tuple[str, ...] = ("text", "image"),
    dpis: tuple[int, ...] = (150, 200),
    fallback: bool = True,
    client_factory: Callable[[ModelConfig], Any] | None = None,
    ps_fn: Callable[[], dict[str, Any]] | None = None,
    unload_fn: Callable[[], None] | None = None,
) -> dict[str, Any]:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    factory = client_factory or (
        lambda cfg: OllamaClient(cfg, recorder=ExtractionRecorder(out_dir / "cache"))
    )
    ps = ps_fn or (lambda: ollama_ps(config.base_url))
    unload = unload_fn or (lambda: unload_model(config.base_url, config.model))

    rows, snapshots = _run_model(
        config,
        docs,
        modes=modes,
        dpis=dpis,
        raw_dir=raw_dir,
        client_factory=factory,
        ps_fn=ps,
        unload_fn=unload,
    )

    if fallback:
        fallback_model = config.fallback_model
        if model_is_pulled(config.base_url, fallback_model):
            fallback_config = replace(config, model=fallback_model)
            fallback_rows, fallback_snapshot = _run_model(
                fallback_config,
                docs[:1],
                modes=("text",),
                dpis=(),
                raw_dir=raw_dir,
                client_factory=factory,
                ps_fn=ps,
                unload_fn=lambda: unload_model(config.base_url, fallback_model),
            )
            rows.extend(fallback_rows)
            snapshots.append(fallback_snapshot)
        else:
            print(f"fallback model {fallback_model!r} is not pulled; skipping")

    csv_path = out_dir / "latency.csv"
    memory_path = out_dir / "memory.json"
    write_csv(rows, csv_path)
    write_memory(snapshots, memory_path)
    return {"rows": rows, "csv_path": csv_path, "memory_path": memory_path, "raw_dir": raw_dir}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", default="data/benchmark", help="folder of document subfolders")
    parser.add_argument("--out", default="data/bench", help="where to write benchmark files")
    parser.add_argument("--modes", default="text,image", help="comma list: text,image")
    parser.add_argument("--dpi", default="150,200", help="page-image DPI values for image mode")
    parser.add_argument("--limit", type=int, default=None, help="cap the number of documents")
    parser.add_argument(
        "--skip-fallback", action="store_true", help="do not run the fallback model"
    )
    args = parser.parse_args(argv)

    config = load_model_config()
    docs_dir = (repo_root() / args.docs).resolve()
    docs = discover_documents(docs_dir)
    if not docs:
        print(
            f"no benchmark documents under {docs_dir}; "
            "generate the benchmark set (WS1) or pass --docs tests/fixtures/golden",
            file=sys.stderr,
        )
        return 1
    if args.limit:
        docs = docs[: args.limit]
    summary = run_benchmark(
        config,
        docs,
        (repo_root() / args.out),
        modes=tuple(args.modes.split(",")),
        dpis=tuple(int(d) for d in args.dpi.split(",")),
        fallback=not args.skip_fallback,
    )
    succeeded = sum(1 for row in summary["rows"] if row.success)
    print(f"benchmark: {len(summary['rows'])} calls, {succeeded} succeeded")
    print(f"latency csv: {summary['csv_path']}")
    print(f"memory:      {summary['memory_path']}")
    print(f"raw outputs: {summary['raw_dir']}")
    return 0 if succeeded == len(summary["rows"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
