# Brief: WS2: Reading documents

You are building workstream **WS2: Reading documents** of the Kallang Track 10 local demo
(AI invoice processing for The Kallang Group; full plan: Track 10 Local Demo Build Plan.md
in the user's Obsidian vault).

- Worktree: ~/Projects/kallang-ws2-parse (branch `ws2-parse`, based on tag `contracts-v1`).
- Read first: `docs/CONTRACTS.md`, `src/invoiceflow/contracts/`, `tests/fixtures/golden/`.
- Your section of the build plan is pasted below. It lists what to build, what you own, and
  when you are done.
- You own only: `src/invoiceflow/parse/`, plus your tests under `tests/unit/parse/` and `tests/integration/ws2/`. Do not edit anything else.
## Rules for every agent

1. Edit only the paths you own. If a contract needs to change, stop and add the request
   to docs/contract-requests.md; the integrator decides.
2. Write tests first. `make test` must pass, with at least 80% coverage on your paths.
3. Don't add dependencies; Phase 0 has already declared them. If you need one, ask through
   docs/contract-requests.md.
4. No secrets in code. Read settings from `.env` and `config/`.
5. Prefer pure functions and frozen models. Return new objects instead of changing inputs.
6. Use Python 3.12 and type hints, and run `ruff format` and `ruff check`.
7. Use synthetic data only. Never commit a real invoice.
8. Finish with `HANDOFF-<ws>.md`: what's done, how to run it, and what's left.

## Environment notes (all workstreams)

- Your worktree has no venv yet: run `uv sync --all-extras` first. If uv complains about its
  cache directory, run `export UV_CACHE_DIR=/Users/huskydawg/Projects/.uv-cache`.
- Run everything through `uv run`. Python is 3.12 (`.python-version`).
- `make test` runs pytest with coverage (80% gate) and runs the `db` integration tests too;
  they skip automatically when Postgres is not reachable.
- The dev Postgres runs on 127.0.0.1:5433 (container `invoiceflow-postgres-dev`). From your
  worktree: `docker compose -f compose.dev.yaml up -d --wait`, then
  `uv run python scripts/migrate.py` and `uv run python scripts/load_fixtures.py`.
- Ollama (gemma4:12b, 7.7 GB, already pulled) listens on 127.0.0.1:11434.
  **Only WS3 may call it.** All other workstreams must not.
- Tesseract 5.5.4 is installed (`tesseract --version`). The Docker image installs its own copy.
- WeasyPrint on this Mac needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` (see the
  `golden` target in the Makefile for the pattern).
- Commit on your branch. There is no remote: do not push. Do not touch the main worktree at
  ~/Projects/kallang-invoice-demo or any other `kallang-*` worktree.
- Your "done when" list comes from the build plan section pasted below. Treat it as the
  acceptance criteria and verify each item before writing your HANDOFF file.

## Extra rule for this run

This workstream runs on the fast model. If anything you need is not in
`docs/CONTRACTS.md` or the frozen contracts, **stop and add a contract request to
`docs/contract-requests.md`**; do not improvise around the contract, do not rename keys,
and do not edit another workstream's files.

## Your build plan section


### WS2: Reading documents (build plan section)

Build:

- **File type.** Detect it from the file's content, not its extension. Reject files over
  20 MB or 20 pages.
- **PDF words and boxes** with pdfplumber. A page with fewer than about 25 characters counts
  as scanned.
- **Page images** with pypdfium2: 150 DPI for the review screen, 300 DPI for OCR.
- **OCR** with pytesseract `image_to_data`, which returns words, boxes, and confidence.
  - Correct photo rotation from the EXIF data.
  - Detect page rotation with Tesseract's orientation detection.
- **Hidden-text scan** using pdfplumber's character data. Words are marked `hidden = True`
  when they have:
  - a white or near-white fill
  - a font size under 2 pt
  - a position outside the visible page
- **Prompt text.** For each page, produce the text in reading order (words grouped into
  lines, left to right), with hidden words left out.

Implement the `TextExtractor` protocol from `contracts/interfaces.py` (methods `parse` and
`page_texts`). The pipeline will call it through that protocol.

### WS2 done when

- On generated digital PDFs, at least 99% of truth values appear among the words. (WS1 runs in
  parallel; use `tests/fixtures/golden/` for this test now.)
- The hit rate on type C scans is measured and reported. The target is 90%. (Scans may not
  exist yet; write the test to use a fixture you generate locally or skip when absent.)
- The hidden-text invoice is caught. (Create a small hidden-text PDF fixture of your own for
  the unit test.)
- Nothing imports PyMuPDF.

Watch out for: Tesseract 5.5.4 is already installed on the Mac. Do not call Ollama; this
workstream has no model calls.

