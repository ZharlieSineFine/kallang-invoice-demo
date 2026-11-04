# Brief: WS5: Checks and routing

You are building workstream **WS5: Checks and routing** of the Kallang Track 10 local demo
(AI invoice processing for The Kallang Group; full plan: Track 10 Local Demo Build Plan.md
in the user's Obsidian vault).

- Worktree: ~/Projects/kallang-ws5-rules (branch `ws5-rules`, based on tag `contracts-v1`).
- Read first: `docs/CONTRACTS.md`, `src/invoiceflow/contracts/`, `tests/fixtures/golden/`.
- Your section of the build plan is pasted below. It lists what to build, what you own, and
  when you are done.
- You own only: `src/invoiceflow/rules/`, `config/rules.yaml` (values only), plus your tests under `tests/unit/rules/` and `tests/integration/ws5/`. Do not edit anything else.
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


### WS5: Checks and routing (build plan section)

Build:

- **Code:** `rules/registry.py`, one file per check (R01-R12), `router.py`, `confidence.py`,
  and the `rule_version` hash.
- **`config/rules.yaml`:** (keys already exist; you own the values)
  - the GST rate table: 7% before 2023, 8% in 2023, 9% from 2024-01-01
  - tolerances, thresholds, and severities
  - the list of instruction phrases, starting from the AgentOps patterns
- **No side effects.** Every check is a pure function of `CheckContext`, with no database or
  file access.

The twelve checks (full rules are in the build plan section 6; each check returns
`Finding` objects with rule_id, rule_version, severity, scope, field, message, evidence):

- R01 every extracted value appears on the page: exactly, as an equal number, or fuzzy >= 90
- R02 quantity x price equals the line amount; lines add up to the subtotal; subtotal + GST
  equals the total (within `tolerances` in config)
- R03 GST: number present and well formed; rate right for the invoice date; GST equals rate x
  net allowing rounding; simplified invoice only up to S$1,000 with GST and says GST included;
  foreign-currency invoice shows SGD amounts
- R04 vendor in the vendor master (GST number or UEN first, then fuzzy name), and the invoice
  is addressed to a Kallang entity (`company.yaml` entity_names); hold when vendor unknown,
  flag a wrong addressee
- R05 not a duplicate: same file hash, same vendor + invoice number, or same vendor + amount
  within `duplicate_window_days`
- R06 every SAP-required column can be filled after mapping, including GL account, cost center
  and tax code on every coding line
- R07 the file is readable (text layer or OCR confidence above threshold); the model output is
  valid after one retry
- R08 the bank account matches the vendor master (digits-only comparison)
- R09 no hidden text, no instruction-like text (`instruction_phrases`), and the canary does
  not appear in the output
- R10 document type: invoice, credit note, statement, quotation, or other
- R11 dates: not in the future, not older than `max_invoice_age_days`, due date on or after
  the invoice date, day/month unambiguous for the vendor locale
- R12 the PO exists, belongs to the same vendor, and has enough open amount left

Routing (implement in `router.py`):

| Status | When |
|---|---|
| AUTO_PASSED | No finding above INFO. In a pilot, `auto_approve_clean: false` sends everything to review. |
| NEEDS_REVIEW | Any flagged field |
| ON_HOLD | R04 (unknown vendor), R05, R08, or R09 |
| MANUAL_ENTRY | R07 |
| NOT_INVOICE | R10: a statement, quotation, or delivery order |

Field confidence comes from the checks, not the model: High = found exactly or as equal
number and nothing flags it; Medium = found only by fuzzy match and nothing flags it;
Low = not found, or a check flags it.

Implement the `Rule` and `Router` protocols from `contracts/interfaces.py`. Do NOT edit
`src/invoiceflow/pipeline/` (WS6 and the integrator wire your rules into the pipeline).

### WS5 done when

- Every check has passing and failing tests.
- The golden fixtures produce their expected findings (`tests/fixtures/golden/`,
  `expected_findings.json`: clean -> none; twin -> R02 on subtotal).
- Test coverage on `rules/` is at least 90%.

In Phase 2, a "perfect extraction" test builds a context from each of WS1's truth files. It
confirms that the expected check fires and no other check does.

