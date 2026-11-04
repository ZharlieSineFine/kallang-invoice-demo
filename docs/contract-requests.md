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

### CR-001 — add `pipeline.recheck` for review-time checks

- **Workstream:** WS7
- **Status:** OPEN
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
- **Integrator decision:** pending.

### CR-002 — define the evaluation report format for the dashboard

- **Workstream:** WS7
- **Status:** OPEN
- **What changes:** publish a stable JSON report shape and path for the latest evaluation
  (WS8 `evaluate/`), e.g. `reports/latest.json` with `generated_at`, `set_name` (must mark
  synthetic runs), `document_count`, `auto_pass_rate`, `accuracy`, `per_rule`, and
  `mismatches`. Add the path and top-level keys to `docs/CONTRACTS.md`.
- **Why:** the Dashboard must show the latest evaluation "labeled synthetic", but contracts-v1
  defines the evaluation input models only, not the report file. WS7's loader accepts a
  small set of common key names and shows the raw payload, which is guesswork.
- **Impact:** WS7 and WS8; no database change.
- **Integrator decision:** pending.

### CR-003 — document the Airflow REST trigger settings

- **Workstream:** WS7
- **Status:** OPEN
- **What changes:** add the Airflow REST settings to `.env.example` / `docs/CONTRACTS.md`
  (proposed: `AIRFLOW_BASE_URL`, `AIRFLOW_DAG_ID=invoice_intake`, `AIRFLOW_USERNAME`,
  `AIRFLOW_PASSWORD`, `AIRFLOW_AUTH_TOKEN`). WS7 also needs the DAG id that the Upload page
  should trigger.
- **Why:** the Upload page starts `invoice_intake` through the Airflow REST API when the
  login setup works, otherwise it shows a link. At `contracts-v1` no Airflow endpoint or
  credential names are defined, so WS7 reads the names above and falls back to a link.
- **Impact:** WS6 owns the Airflow stack and `.env.example`; WS7 only reads the values.
  No secret is committed.
- **Integrator decision:** pending.
