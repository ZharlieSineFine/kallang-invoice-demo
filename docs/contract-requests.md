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

### CR-001 — `.gitignore` `reports/` pattern swallows `reports/baseline.json`

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
