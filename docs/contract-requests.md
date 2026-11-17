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

### CR-009 — add `watchdog` for Streamlit file watching

- **Workstream:** integrator (Phase 2)
- **Status:** ACCEPTED (user, 2026-11-16)
- **What changes:** `pyproject.toml` gains `watchdog>=6.0.0`; `uv.lock` updated.
- **Why:** with watchdog, the review app notices code changes and offers "Always rerun", so
  a demo rehearsal does not need a full Streamlit restart after each change.
- **Impact:** a development convenience; no code imports it. No migration.

### CR-010 — SAP CSV: `InvoiceID` (1, 2, 3 per file) replaces `DocKey`

- **Workstream:** integrator (Phase 2)
- **Status:** ACCEPTED (user, 2026-11-17)
- **What changes:** `config/sap_mapping.yaml`'s first column `DocKey` (`doc.doc_id`, the
  internal UUID) becomes `InvoiceID` (`doc.invoice_id`): the invoices in one file numbered
  1, 2, 3 in file order, every coding-line row of an invoice carrying its number.
  `RowContext` gains `invoice_id`. The batch manifest gains `invoices`, one entry per number:
  `invoice_id`, `doc_id`, `vendor_no`, `reference`, `first_row`, `row_count`.
- **Why:** SAP's Import Supplier Invoices upload groups an invoice's lines by an invoice ID
  that only has to be unique within the file (SAP KBA 3782347); an internal UUID means nothing
  to SAP. The vendor's invoice number alone is not unique across vendors. The manifest keeps
  the link from each row to its document, so the review app's CSV trace still works.
- **Impact:** still 16 columns. The app traces new batches through the manifest and older
  batches through their `DocKey` column. No migration.

### CR-011 — hidden text: OCR comparison, and a 3 pt font limit

- **Workstream:** integrator (Phase 2)
- **Status:** ACCEPTED (user, 2026-11-17)
- **What changes:** `config/rules.yaml` `hidden_text` gains `ocr_compare: true`, and
  `max_font_size_pt` goes from 2.0 to 3.0. `ParseConfig` gains `hidden_ocr_compare`.
  `parse.visibility` renders each text-layer page, reads it with Tesseract as black ink on
  white paper (pixels lighter than 200 count as paper), and marks text-layer words a person
  cannot see as hidden. Runs under 4 letters are ignored, and every run gets a second OCR
  look on a crop, matched by position, before it counts. `parse.hidden` names the reason
  (`tiny_font`, `white_text`, `off_page`, `not_visible`); `parse.pdf.hidden_text_for_file`
  gives the review screen the same answer.
- **Why:** the three trick checks missed light-gray, transparent, covered, and
  same-color-as-background text, and a 2.5 pt font (tested 2026-11-17 on 9 planted
  invoices: 4 of 9 caught before, 9 of 9 after). Hidden words never reach the model.
- **Impact:** about 0.5 s more per digital page. False-alarm test
  (`tests/integration/ws2/test_no_false_hidden_text.py`): the comparison hides no word on any
  of the 54 demo invoices, so prompts, and the replay cache, are unchanged. The smallest real
  text on the 54 is 7.6 pt. No migration.

### CR-012 — auto-pass value limit and a random audit of auto-passed invoices

- **Workstream:** integrator (Phase 2)
- **Status:** ACCEPTED (user, 2026-11-17: 10% audit; limit S$5,000, raised from S$2,500 the
  same day so all 31 auto-passed demo invoices stay auto-passed)
- **What changes:** `config/rules.yaml` `routing` gains `auto_pass_limit_sgd: "5000.00"`:
  `rules.Router` sends a clean invoice at or above it to `NEEDS_REVIEW` with the reason
  "At or above the S$5,000.00 auto-pass limit: …" (credit notes by size, foreign invoices by
  their SGD total). A new `audit` block (`sample_percent: "10"`, `seed`) drives
  `rules.audit.AuditSample`: intake (`pipeline.steps._save_outcome`) logs `audit.selected`
  for an auto-passed invoice the draw picks. The draw hashes the seed with the file's
  fingerprint, so a reload picks the same files. A person's check is logged as
  `audit.completed` (`result` passed or error, `fields`). `RoutingDecision` is unchanged.
- **Why:** reviewer corrections only measure the invoices people see; auto-passed invoices
  reach SAP without a person. The value limit keeps large amounts with a person, and the
  audit sample measures the auto-pass error rate (user's design, 2026-11-17).
- **Impact:** a picked invoice stays `AUTO_PASSED` and exports as usual; the audit is a label
  and a result, never a hold. None of the first 54 reaches the limit (the largest auto-passed
  is S$2,877.60), so all 31 stay auto-passed, and seed `kallang-demo-10` picks 2 of them for the
  audit: GSH-2026-9004 and KSS-2026-8101. Three clean invoices of S$5,000+ were added to show the
  limit (now in `data/generated/invoices/`, the set is 57): each goes to NEEDS_REVIEW. In the live set it picks PCE-2026-9606 only. The evaluation
  scores findings, not statuses, so its figures are unchanged. No migration.
