# HANDOFF — WS5: Checks and routing

Workstream WS5 is complete on branch `ws5-rules` (based on tag `contracts-v1`). It implements
the twelve checks R01–R12, the router, and field confidence, all as pure functions of
`CheckContext` with no database or filesystem access.

## What's done

### Code (`src/invoiceflow/rules/`)

| File | Purpose |
|---|---|
| `base.py` | `BaseRule` (id, config severity, `finding(...)` helper) plus shared pure helpers: `cfg_decimal`, `fmt2`, `money_sgd`, `digits_only`, `fuzzy_score`, `visible_text`, `gst_rate_for_date`. |
| `version.py` | `rule_version` hash — SHA-256 over the rule source file + the canonical `rules.yaml`, shortened to 16 hex chars. `config_digest` for the same over config alone. |
| `r01.py` … `r12.py` | One file per check (see below). |
| `registry.py` | `build_rules(config)` returns all twelve in order. |
| `confidence.py` | `field_confidences(ctx, findings)` — High (exact/equal-number), Medium (fuzzy), Low (not found or flagged). |
| `router.py` | `Router` — status from highest severity + document type, reasons, and confidence. |
| `__init__.py` | Public exports. |

### The twelve checks

| Rule | What it checks | Severity (config) |
|---|---|---|
| R01 | Every located value appears on the page (EXACT / NUMERIC / FUZZY ≥ `fuzzy_match_min_score`). | FLAG |
| R02 | `quantity × price (× days)` = line amount; lines sum = subtotal; subtotal + GST = total (within `tolerances`). | FLAG |
| R03 | GST number present + well formed; rate matches `gst_rates` for the invoice date; GST = rate × net; simplified-invoice cap/note; foreign-currency SGD amounts. | FLAG |
| R04 | Vendor in master; addressee is a Kallang `entity_names` member. Unknown vendor = HOLD, wrong addressee = FLAG. | HOLD |
| R05 | Not a duplicate: file hash, vendor + number, or vendor + amount within `duplicate_window_days`. | HOLD |
| R06 | SAP-required columns fillable: vendor no, invoice no/date/currency/total, and GL/cost center/tax code on every coding line. | FLAG |
| R07 | Readable (text layer or OCR confidence/chars above thresholds); model output valid after retry. | MANUAL |
| R08 | Bank account matches vendor master (digits-only comparison). | HOLD |
| R09 | No hidden words, no `instruction_phrases` in the document/output, canary absent from output. | HOLD |
| R10 | Document type classification (invoice/credit-note types pass; others get an INFO finding). | INFO |
| R11 | Dates: not future, not older than `max_invoice_age_days`, due ≥ invoice date, `ambiguous_dates` empty. | FLAG |
| R12 | PO exists, belongs to the same vendor, and has enough open amount. | FLAG |

Every finding carries `rule_id`, `rule_version` (the hash), `severity`, `scope`, `field`,
`message`, and `evidence`. Severity comes from `config/rules.yaml` (`severities`), except the
two R04 flavours (unknown vendor → HOLD, wrong addressee → FLAG) which are set in code as the
plan specifies.

### Routing (`router.py`)

| Status | When |
|---|---|
| `AUTO_PASSED` | No finding above INFO (`auto_approve_clean: false` sends clean invoices to review). |
| `NEEDS_REVIEW` | Any FLAG finding. |
| `ON_HOLD` | Any HOLD finding (R04 unknown vendor, R05, R08, R09). |
| `MANUAL_ENTRY` | Any MANUAL finding (R07), or `ctx.invoice is None`. |
| `NOT_INVOICE` | `document_type` is statement, quotation, delivery order, or other. |

Field confidence comes from the checks: EXACT/NUMERIC → High, FUZZY → Medium, NONE → Low; a
field is downgraded to Low when any FLAG-or-above finding names it.

### Config

`config/rules.yaml` already met the brief (GST table 7%/8%/9%, tolerances, thresholds,
severities, instruction phrases) so its values were left unchanged. The prompt-injection
canary is a code constant in `r09.py`; see CR-001 in `docs/contract-requests.md` for moving it
into shared config with WS3.

### Tests

- `tests/unit/rules/` — passing **and** failing tests for every rule, plus registry, router,
  confidence, and version.
- `tests/integration/ws5/test_golden_findings.py` — the golden fixtures through the real
  rules: `golden-a-clean` → `AUTO_PASSED`, no findings; `golden-a-total-mismatch` →
  `NEEDS_REVIEW` with exactly `R02` on `subtotal` (message and evidence match
  `expected_findings.json`).

## How to run it

```bash
cd ~/Projects/kallang-ws5-rules
export UV_CACHE_DIR=~/Projects/kallang-ws5-rules/.uv-cache   # worktree-local cache
uv sync --all-extras                                          # already done here
make test                                                     # 207 tests, rules/ at 98%, total 97%
make skeleton                                                 # golden fixtures still pass via stubs
uv run ruff check . && uv run ruff format --check .           # lint clean
```

`make test` runs the `db` integration tests too; they pass when the dev Postgres is up
(`make db-dev`), and skip otherwise.

## What's left

- **Integrator wiring.** `pipeline/stubs.py` still uses `GoldenFindingsRule`/`SeverityRouter`.
  Swap in `build_rules(config)` + `Router(config)` in `golden_deps` / `PipelineDeps` so the
  real pipeline uses these rules (WS6 / integrator owns that file).
- **CR-001 (open).** A shared canary value in config so WS3's prompt and WS5's R09 agree.
- **R06 header columns** are hard-coded (`invoice_number`, `invoice_date`, `currency`,
  `total`, vendor no) rather than derived from `config/sap_mapping.yaml`, because rules are
  pure and cannot read files. If the SAP layout's required columns change, R06 needs a
  matching update (or the mapping should be passed into `rules_config`).
- **Phase 2 "perfect extraction" test.** Build a `CheckContext` from each of WS1's truth files
  and assert exactly the expected check fires and no other does. The golden integration test
  already covers this shape for the two golden fixtures.
- **R03 GST-number regex** accepts the classic `9 digits + letter` UEN. Broader UEN formats
  (e.g. `T20LL1234A`) would need a config-driven pattern later.

## Notes

- No dependencies added, no secrets in code (the canary is a sentinel, not a secret), Python
  3.12 with type hints, `ruff format` + `ruff check` clean.
- Only owned paths were touched: `src/invoiceflow/rules/`, `tests/unit/rules/`,
  `tests/integration/ws5/`, `docs/contract-requests.md`, and this file.
