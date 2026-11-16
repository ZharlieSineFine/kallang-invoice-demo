# Contract change requests

Workstreams **do not edit contract files** (`src/invoiceflow/contracts/**`,
`db/migrations/**`, `config/company.yaml`, `tests/fixtures/golden/**`,
`tests/unit/contracts/**`, `pyproject.toml`, `docs/CONTRACTS.md`). A workstream owns the values
in its own config file (WS3 `models.yaml`, WS5 `rules.yaml`, WS8 `sap_mapping.yaml`) but must
not rename or remove keys. Add a request here instead and keep building against the current
tag.

The integrator decides, applies the change on `main`, updates the contract tests, and re-tags
(`contracts-v2`, …). Worktrees then rebase onto the new tag.

## Template

```markdown
### CR-00N — short title

- **Workstream:** WSx
- **Status:** OPEN | ACCEPTED | REJECTED
- **What changes:** the exact field, model, table, config key, or dependency
- **Why:** the problem it solves, with the failing case
- **Impact:** who else is affected; does it need a migration or a SCHEMA_VERSION bump?
- **Integrator decision:** the call and the date
```

## Requests
### CR-001 — a shared prompt-injection canary value

- **Workstream:** WS5 (raised), touches WS3
- **Status:** ACCEPTED (integrator, 2026-11-04) — implement at stub swap: add `canary` to
  `config/rules.yaml`; WS3's prompt and WS5's R09 both read it.
- **What changes:** add a `canary` key (a single string) to `config/rules.yaml` (or a shared
  config) so WS3's prompt and WS5's R09 check use the same sentinel.
- **Why:** R09 must confirm "the canary does not appear in the output", but no canary value
  is defined in the contract. WS5 currently hard-codes `KALLANG-INTERNAL-CANARY-9f3a` in
  `rules/r09.py`; WS3 would need to embed the same string in its prompt, which is fragile
  across workstreams.
- **Impact:** additive config key only; no schema or migration change. WS5 reads it from
  `rules_config["canary"]` with the current constant as a fallback.

### CR-002 — add `pipeline.recheck` for review-time checks

- **Workstream:** WS7
- **Status:** ACCEPTED (integrator, 2026-11-04) — implement `pipeline.recheck` at stub swap.
- **What changes:** add a public `recheck` entry point to `src/invoiceflow/pipeline/`
  (the WS7 build plan calls it `pipeline.recheck`). Proposed shape:
  `recheck(doc_id, *, invoice, extraction, document, master, coding_lines, locations,
  prior_invoices, rules_config, today, run_id) -> CheckOutcome`, re-running the WS5 rules
  against the current stored values and returning the findings plus a routing decision.
- **Why:** the Review page must rerun checks after a reviewer corrects a field or line item.
  At `contracts-v1` there is no `recheck` (only `check_stage`, whose golden stubs return the
  fixture's recorded findings regardless of the corrected value), so a corrected subtotal
  still shows R02. WS7 carries a clearly marked temporary adapter in `app/recheck.py` until
  this lands.
- **Impact:** WS7 only consumes it; no schema change. Needs the WS5 rule signature and a
  decision on which context fields may be rebuilt from Postgres versus re-read from the
  original parse.

### CR-003 — define the evaluation report format for the dashboard

- **Workstream:** WS7
- **Status:** ACCEPTED (integrator, 2026-11-04) — define `reports/latest.json` with WS8 at
  stub swap.
- **What changes:** publish a stable JSON report shape and path for the latest evaluation
  (WS8 `evaluate/`), e.g. `reports/latest.json` with `generated_at`, `set_name` (must mark
  synthetic runs), `document_count`, `auto_pass_rate`, `accuracy`, `per_rule`, and
  `mismatches`. Add the path and top-level keys to `docs/CONTRACTS.md`.
- **Why:** the Dashboard must show the latest evaluation "labeled synthetic", but contracts-v1
  defines the evaluation input models only, not the report file. WS7's loader accepts a
  small set of common key names and shows the raw payload, which is guesswork.
- **Impact:** WS7 and WS8; no database change.

### CR-004 — document the Airflow REST trigger settings

- **Workstream:** WS7
- **Status:** ACCEPTED (integrator, 2026-11-04) — add the env names to `.env.example` at
  stub swap; WS6's compose provides the values.
- **What changes:** add the Airflow REST settings to `.env.example` / `docs/CONTRACTS.md`
  (proposed: `AIRFLOW_BASE_URL`, `AIRFLOW_DAG_ID=invoice_intake`, `AIRFLOW_USERNAME`,
  `AIRFLOW_PASSWORD`, `AIRFLOW_AUTH_TOKEN`). WS7 also needs the DAG id that the Upload page
  should trigger.
- **Why:** the Upload page starts `invoice_intake` through the Airflow REST API when the
  login setup works, otherwise it shows a link. At `contracts-v1` no Airflow endpoint or
  credential names are defined, so WS7 reads the names above and falls back to a link.
- **Impact:** WS6 owns the Airflow stack and `.env.example`; WS7 only reads the values.
  No secret is committed.

### CR-005 — make `reports/baseline.json` trackable in git

- **Workstream:** WS8
- **Status:** ACCEPTED (integrator, 2026-11-04) — `.gitignore` changed to `reports/*` so the
  `!reports/baseline.json` negation works.
- **What changes:** the `.gitignore` rule `reports/` swallows the negation
  `!reports/baseline.json`; the gate baseline must be committable.
- **Why:** `make gate` compares against `reports/baseline.json`.
- **Impact:** none beyond git tracking.

### CR-006 — `.gitignore` `reports/` pattern swallows `reports/baseline.json`

- **Workstream:** WS8
- **Status:** OPEN
- **What changes:** change the `.gitignore` rule from `reports/` to `reports/*` so the
  existing `!reports/baseline.json` exception can re-include the release-gate baseline.
- **Why:** `reports/` ignores the directory itself, so Git never descends into it and the
  `!reports/baseline.json` line has no effect. WS8's gate compares against
  `reports/baseline.json`, which should be version-controlled. Workaround on this branch:
  `git add -f reports/baseline.json`.
- **Impact:** none on runtime code; only the tracked-vs-ignored status of one report file.
  No migration, no `SCHEMA_VERSION` bump.
- **Integrator decision:** —


### CR-007 — `Repository` reads and writes the export needs

- **Workstream:** integrator (Phase 2)
- **Status:** ACCEPTED (integrator, 2026-11-04)
- **What changes:** `Repository` gains `set_document_meta(doc_id, doc_type, vendor_id)` and
  `stored_invoice(doc_id)`; `record_export` gains an optional `manifest`; `prior_invoices(None)`
  returns earlier invoices for every known vendor.
- **Why:** `documents.doc_type` and `documents.vendor_id` were never written, the export DAG
  wrote a stub CSV because nothing could read back a `NormalizedInvoice`, and R05 never saw
  earlier invoices because intake passed none.
- **Impact:** no migration and no `SCHEMA_VERSION` bump. Existing callers keep working.

### CR-008 — `Repository` support for showing a document while the model reads it

- **Workstream:** integrator (Phase 2)
- **Status:** ACCEPTED (integrator, 2026-11-13)
- **What changes:** `Repository` gains `unfinished_document(sha256)` and
  `discard_document(doc_id, file_id)`. `pipeline.steps` gains `intake_in_steps`, which commits
  the RECEIVED document before the model runs and the outcome after it.
- **Why:** intake saved everything in one transaction at the end, so the review app could not
  show the invoice being read (user request 2026-11-13, "Processing…" card). Committing
  RECEIVED early needs two things the contract lacked: removing that placeholder when
  processing fails, so a retry is not skipped as a duplicate of itself, and finding it when the
  process was killed, so the retry resumes it instead of losing the invoice.
- **Impact:** no migration and no `SCHEMA_VERSION` bump; `DocStatus.RECEIVED` already exists.
  `intake_document` keeps its single-transaction behavior for `make e2e` and the fixtures.
