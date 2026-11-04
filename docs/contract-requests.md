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
- **Status:** OPEN
- **What changes:** add a `canary` key (a single string) to `config/rules.yaml` (or a shared
  config) so WS3's prompt and WS5's R09 check use the same sentinel.
- **Why:** R09 must confirm "the canary does not appear in the output", but no canary value
  is defined in the contract. WS5 currently hard-codes `KALLANG-INTERNAL-CANARY-9f3a` in
  `rules/r09.py`; WS3 would need to embed the same string in its prompt, which is fragile
  across workstreams.
- **Impact:** additive config key only; no schema or migration change. WS5 reads it from
  `rules_config["canary"]` with the current constant as a fallback.
- **Integrator decision:** _pending_
