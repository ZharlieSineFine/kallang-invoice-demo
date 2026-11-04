# Brief: WS8: SAP coding, export, and evaluation

You are building workstream **WS8: SAP coding, export, and evaluation** of the Kallang Track 10 local demo
(AI invoice processing for The Kallang Group; full plan: Track 10 Local Demo Build Plan.md
in the user's Obsidian vault).

- Worktree: ~/Projects/kallang-ws8-export (branch `ws8-export`, based on tag `contracts-v1`).
- Read first: `docs/CONTRACTS.md`, `src/invoiceflow/contracts/`, `tests/fixtures/golden/`.
- Your section of the build plan is pasted below. It lists what to build, what you own, and
  when you are done.
- You own only: `src/invoiceflow/coding/`, `src/invoiceflow/export/`, `src/invoiceflow/evaluate/`, `config/sap_mapping.yaml` (values only), plus your tests under `tests/unit/coding/`, `tests/unit/export/`, `tests/unit/evaluate/`, and `tests/integration/ws8/`. Do not edit anything else.
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

## Your build plan section


### WS8: SAP export and evaluation (build plan section)

Build:

- **`coding/`:**
  - `assign(invoice, vendor, po, coding_master) -> tuple[CodingLine, ...]`, which applies the
    precedence rules in section 5.5 (pasted below). It groups lines by GL account, cost
    center, and tax code.
  - It splits the GST across the coding lines, with any cents of difference placed on the
    largest line.
  - It sets the tax code from the supplier's GST status.
  - It's a pure function: no database or file access.
- **`export/`:**
  - **Mapping engine** for `config/sap_mapping.yaml`. It handles constants, invoice fields,
    coding-line fields, templates, maximum lengths, and the date format. It writes one row per
    coding line.
  - **Batch checks:**
    - every required column is filled
    - no vendor and reference pair appears twice
    - for each invoice, the net amounts plus the tax amounts equal the gross amount
    - totals agree with the documents
    - every GL account, cost center, and tax code exists in the seed data
    - no document was exported before
  - **CSV writer:** UTF-8, quoted, with a formula-injection guard on free-text columns.
  - **Manifest JSON:** batch ID, row count, total, the CSV's SHA-256, and the mapping, model,
    prompt, and rule versions.
  - Each invoice is exported only once; one database transaction enforces this
    (`export_rows.doc_id` is UNIQUE).
- **`evaluate/`:**
  - **Measures:**
    - header-field accuracy by type
    - line-item precision and recall
    - the share of invoices with every header field right
    - coding accuracy: GL account, cost center, and tax code compared with the expected coding
      in the truth files
    - each check's precision and recall against the manifest
    - latency
  - **Output:** `reports/eval_<time>.json` and `.md`.
  - **Gate:** `make gate` fails when accuracy drops more than one point below
    `reports/baseline.json`. (The Makefile target is WS6's; implement the evaluation code and
    a CLI now, and say in your HANDOFF what the `eval`/`eval-bench`/`gate` targets should call.)

### How each line gets its coding (build plan section 5.5; first rule that matches wins)

1. The invoice quotes a PO: the GL account and cost center come from the PO.
2. The line or header names a venue: the cost center comes from `venue_cost_centers.csv`, and
   the GL account is the vendor's default.
3. Otherwise, the vendor's default GL account and cost center apply.
4. If nothing matches, R06 flags the line and the reviewer picks values from dropdowns.

The tax code depends on the supplier's GST status:

- `TX` when the supplier shows a GST number and charges 9%
- `NR` when the invoice has no GST number
- `OP` for an overseas vendor
- `ZP` for a 0% line

Each coding line records which rule produced it (`coding_source`). The layout has one row per
coding line, header fields repeated on each row. The GST printed on the invoice is the
authoritative figure: if the line taxes add up to a few cents more or less, the difference
goes on the largest line.

### WS8 done when

- The golden fixtures produce a CSV identical to the expected file. (Write the expected CSV
  into your tests.)
- `assign` has a test for each precedence rule (PO, venue, vendor default, none) and for
  spreading GST rounding across lines.
- A missing required field blocks the batch with a clear message.
- An unknown GL account or cost center blocks the batch.
- A description starting with "=" is made harmless.
- Evaluating the truth against itself scores 100%.

The hypothetical mapping is already in `config/sap_mapping.yaml` (layout: hypothetical); it
will be replaced by Kallang's real template later. Do not call Ollama.

