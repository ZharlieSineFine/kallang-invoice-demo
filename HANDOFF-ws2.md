# HANDOFF — WS2: Reading documents

Branch: `ws2-parse` (based on tag `contracts-v1`).
Status: **done**. All WS2 acceptance criteria are covered by tests and pass.

## Commit artifact (headless sandbox note)

The linked worktree's git metadata is outside this workspace
(`~/Projects/kallang-invoice-demo/.git/worktrees/kallang-ws2-parse`), and this headless run
has no approval channel to write there. The change is therefore committed in a temporary
local git dir on branch `ws2-parse`, with the same parent (`cfd106c`) and tree as this
working copy, and exported next to this file:

- `HANDOFF-ws2.bundle` — record it without changing the files already in this worktree:

  ```bash
  git fetch ./HANDOFF-ws2.bundle ws2-parse
  git reset --mixed FETCH_HEAD
  ```

- `HANDOFF-ws2.patch` — for a fresh checkout at `contracts-v1`:
  `git am HANDOFF-ws2.patch`

Apply one of them to record the commit in the linked worktree; the working tree already
contains exactly the commit tree. (No tests were run against the patch itself, but the patch
tree is exactly the tree that passed the runs below.)

## What is done

`src/invoiceflow/parse/` implements the `TextExtractor` protocol:

| Piece | Module | Notes |
|---|---|---|
| Content-based file type | `detect.py` | PDF magic, Pillow-verified images, Peppol/UBL XML, XLSX zip layout; extensions are ignored. |
| Size/page limits | `extractor.py` | Rejects files over 20 MB and PDFs over 20 pages. |
| PDF words + boxes | `pdf.py`, `hidden.py` | pdfplumber `extract_words(return_chars=True)`; boxes are page fractions from the top-left. |
| Scanned-page detection | `extractor.py` | A page with fewer than `scanned_page_min_chars` (25) visible characters is OCR'd. |
| Page images | `images.py` | pypdfium2 rendering: 150 DPI for review, 300 DPI for OCR (OCR page image is downscaled to 150 for review). |
| OCR | `images.py` | pytesseract `image_to_data`; words, page-fraction boxes, per-word confidence, and `ocr_mean_conf`. |
| EXIF + orientation | `images.py` | `ImageOps.exif_transpose` for photos; Tesseract `image_to_osd` for sideways pages. The oriented image is the one saved for review, so boxes stay aligned. |
| Hidden text | `hidden.py` | Near-white fill, font size under 2 pt, and off-page positions; kept as `Word(hidden=True)` evidence. |
| Prompt text | `reading.py` | Words grouped into visual lines, top-to-bottom, left-to-right; hidden words removed. Pages returned in page order. |
| Errors | `errors.py` | `FileTooLargeError`, `TooManyPagesError`, `UnsupportedFileKindError`, `EmptyDocumentError`, `ParseError`. |

Public entry points (from `invoiceflow.parse`):

```python
from invoiceflow.parse import (
    DocumentParser,
    ParseConfig,
    detect_file_kind,
    page_texts,
    parse_document,
)

parser = DocumentParser(config=ParseConfig.from_repo(), image_root=None)
document = parser.parse(path, file_id=file_id, doc_id=doc_id)
texts = parser.page_texts(document)  # or page_texts(document)
```

Defaults are read from `config/rules.yaml` (`scanned_page_min_chars`, `hidden_text.*`).
`image_root` defaults to `<INVOICEFLOW_DATA>/parsed/<doc_id>/page-NNN.png`.

### Integration point (one line, integrator owns it)

`DocumentParser` satisfies the frozen `TextExtractor` protocol. In the real pipeline,
construct it in `PipelineDeps` in place of `GoldenTextExtractor`:

```python
from invoiceflow.parse import DocumentParser

deps = PipelineDeps(..., text_extractor=DocumentParser(), ...)
```

No contract file was changed and no contract request was needed.

## Acceptance criteria verified

| WS2 "done when" | Result |
|---|---|
| ≥99% of truth values appear among words on generated digital PDFs | **100.0%** on both golden fixtures (47 printed truth values each) |
| Type C scan hit rate measured and reported; target 90% | **100.0%** (47 values) using a 300 DPI raster generated locally from `golden-a-clean/invoice.pdf`; test prints the number and asserts ≥90% |
| Hidden-text invoice caught | Generated hidden-text PDF: white fill, 1 pt text, and off-page text are all `hidden=True`; they appear as evidence and are absent from prompt text |
| Nothing imports PyMuPDF | Test inspects every `parse/*.py` for `fitz`/`pymupdf` and checks `sys.modules` after import |

Additional verification: 212 tests pass; parse package coverage is **97.8%** (full-repo
coverage 97%, 80% gate passed). `ruff check .` and `ruff format --check .` pass. The Phase 0
skeleton still runs.

## How to run

```bash
# Only needed when the default uv cache is not writable in your sandbox.
export UV_CACHE_DIR=/Users/huskydawg/Projects/kallang-ws2-parse/.uv-cache
uv sync --all-extras

# WS2 tests and coverage
uv run pytest tests/unit/parse tests/integration/ws2 \
  --cov=invoiceflow.parse --cov-report=term-missing

# Acceptance measurements (prints the hit rates)
uv run pytest -s \
  tests/unit/parse/test_digital.py::test_at_least_99_percent_of_golden_truth_values_are_in_the_words \
  tests/unit/parse/test_images.py::test_type_c_scan_hit_rate_is_at_least_90_percent

# Whole repo
make test
make lint
```

`make test` also runs the DB integration tests; they skip when Postgres is not reachable.
This run had the dev Postgres available and all 212 tests passed.

## What is left / notes for the integrator

- **Wiring only:** replace `GoldenTextExtractor` in `PipelineDeps` with `DocumentParser()`.
  WS2 deliberately did not edit `pipeline/`.
- **PEPPOL_XML / XLSX:** detected from content, but `parse()` raises
  `UnsupportedFileKindError` for them. Reading e-invoices is outside the WS2 build section;
  if the pipeline needs those kinds, that is a new contract/implementation decision.
- **Real type C scans:** the repo has no scan fixtures. The scan test rasterises the golden
  PDF at 300 DPI and scores OCR against the golden truth, so it runs today. When WS1 supplies
  real scans, add them to the same hit-rate test.
- **Rotated PDF pages** (`/Rotate` ≠ 0) are routed through the OCR path so the review image
  and boxes stay aligned; an OCR-empty fallback keeps the PDF text.
- **Image files** use their oriented pixel dimensions for `width_pt`/`height_pt` (boxes are
  fractions, so this only affects display metadata).
- Hidden text is evidence: `ParsedDocument.hidden_words` is available to WS5's R09. Do not
  prompt on hidden words; `page_texts()` already removes them.
- No model calls, no Ollama usage, no secrets, no new dependencies, synthetic data only.
