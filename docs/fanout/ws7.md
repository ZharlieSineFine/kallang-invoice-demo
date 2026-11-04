# Brief: WS7: Review app and dashboard

You are building workstream **WS7: Review app and dashboard** of the Kallang Track 10 local demo
(AI invoice processing for The Kallang Group; full plan: Track 10 Local Demo Build Plan.md
in the user's Obsidian vault).

- Worktree: ~/Projects/kallang-ws7-app (branch `ws7-app`, based on tag `contracts-v1`).
- Read first: `docs/CONTRACTS.md`, `src/invoiceflow/contracts/`, `tests/fixtures/golden/`.
- Your section of the build plan is pasted below. It lists what to build, what you own, and
  when you are done.
- You own only: `app/`, plus your tests under `tests/unit/app/` and `tests/integration/ws7/`. Do not edit anything else.
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


### WS7: Review app and dashboard (build plan section)

Build:

- **Streamlit pages:** Upload, Queue, Review, Trace, Dashboard, and Batches.
- **Upload** saves the file to `data/inbox/`. It then starts `invoice_intake` through the
  Airflow REST API, if that works with the login setup. If not, it shows a link to start the
  run in Airflow.
- **Review:**
  - The page image shows boxes: green for passed, amber for fuzzy, red for flagged.
  - Choosing a field highlights its box and zooms in on it.
  - Actions:
    - confirm
    - correct (saves the new value with source `reviewer` and reruns the checks through
      `pipeline.recheck`)
    - approve
    - reject
    - release a hold (a comment is required)
  - The line-item table can be edited.
  - A coding panel shows each coding line's GL account, cost center, and tax code, plus the
    rule that set them. The reviewer can change any of the three, but only to valid values
    from the seed data. A change is saved with `coding_source = reviewer`.
  - A "replayed response" badge appears when the extraction came from the cache.
- **Dashboard:** documents processed, auto-pass rate, findings by check, seconds per invoice,
  corrections by field and vendor, holds, and the latest evaluation (labeled synthetic).
- **Data access:** reads go in `app/queries.py` (read-only SQL); writes go through
  `store.repo`.

WS6 is building `store/repo.py` in parallel. Code against the `Repository` protocol from
`contracts/interfaces.py`; if the real repository is not available when you test, put a thin
adapter in your own `app/` paths that you clearly mark as temporary in `HANDOFF-ws7.md`.

The dev database already has the two golden documents loaded (make db-dev && make fixtures),
so the Review screen has data to show: `golden-a-clean` (AUTO_PASSED) and
`golden-a-total-mismatch` (NEEDS_REVIEW, R02 on subtotal).

### WS7 done when

- On the fixture database, a reviewer can correct the total on the 1,080/1,090 invoice.
  R02 clears when the checks rerun, and approving sets the status to APPROVED.
- Boxes line up with the words on three sample pages.
- Streamlit's AppTest covers the main flows.

Do not call Ollama. `streamlit` and `pandas` are already dependencies.

