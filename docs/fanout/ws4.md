# Brief: WS4: Standardizing values and finding them on the page

You are building workstream **WS4: Standardizing values and finding them on the page** of the Kallang Track 10 local demo
(AI invoice processing for The Kallang Group; full plan: Track 10 Local Demo Build Plan.md
in the user's Obsidian vault).

- Worktree: ~/Projects/kallang-ws4-locate (branch `ws4-locate`, based on tag `contracts-v1`).
- Read first: `docs/CONTRACTS.md`, `src/invoiceflow/contracts/`, `tests/fixtures/golden/`.
- Your section of the build plan is pasted below. It lists what to build, what you own, and
  when you are done.
- You own only: `src/invoiceflow/normalize/`, `src/invoiceflow/locate/`, plus your tests under `tests/unit/normalize/`, `tests/unit/locate/`, and `tests/integration/ws4/`. Do not edit anything else.
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


### WS4: Standardizing values and finding them on the page (build plan section)

Build:

- **`normalize/`**, which converts:
  - amounts (S$, SGD, commas, spaces, parentheses for negatives) to `Decimal`
  - dates in common Singapore formats. Day comes first by default and month first for vendors
    with a US locale, and an "ambiguous" flag is set when the two could be confused.
  - IDs, uppercased with spaces and hyphens removed
  - text, with NFKC applied, zero-width characters removed, spaces collapsed, and case folded
- **`to_normalized(extraction, vendor)`**, which returns a `NormalizedInvoice` plus a list of
  conversion problems.
- **`locate/`**, which looks for each value on the page:
  - It searches runs of 1-8 consecutive words, spanning up to 3 lines for addresses and
    descriptions, and skips hidden words.
  - It tries an exact match first, then an equal number, then a rapidfuzz score of 90 or more.
  - When a value appears more than once, it prefers the match next to its label ("Total",
    "GST", "Invoice No.").

Implement the `VendorMatcher`, `Normalizer`, and `Locator` protocols from
`contracts/interfaces.py`.

### WS4 done when

- Unit tests cover:
  - "S$1,090.00" against "1090"
  - "12 Oct 2026" against "12/10/2026"
  - "M2-1234567-8" against "M212345678"
  - zero-width characters
  - a subtotal equal to the total
- Given the truth values, at least 98% of fields are found on generated digital PDFs.
  (WS1 runs in parallel; prove this against `tests/fixtures/golden/` now and note the
  remaining gap in your HANDOFF.)

The golden fixture already ships `locations.json` with expected `FieldLocation` objects;
use them as test vectors. Do not call Ollama.

