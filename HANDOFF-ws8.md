# HANDOFF — WS8: SAP coding, export, and evaluation

Branch `ws8-export` (based on tag `contracts-v1`). This workstream owns
`src/invoiceflow/coding/`, `src/invoiceflow/export/`, `src/invoiceflow/evaluate/`,
`config/sap_mapping.yaml` (values), and its tests.

## What's done

### `coding/` — `assign(invoice, vendor, po, coding_master)`

`src/invoiceflow/coding/assign.py` implements the build-plan section 5.5 coder as a pure
function, exposed both as `assign(...)` and as `SapCoder` (satisfies the `Coder` protocol,
so it is a drop-in for the Phase 0 `GoldenCoder` stub).

- Precedence (first match wins): PO → venue (header or line description) → vendor default →
  `CodingSource.NONE` (leaves GL/cost center blank for R06/review).
- Lines are grouped by `(GL account, cost center, tax code)`; `source_line_nos` records which
  invoice lines rolled up into each coding line.
- GST is split proportionally to net amounts and the printed `invoice.gst_amount` is
  authoritative — `split_gst` puts any cents of rounding difference on the largest line.
- Tax code: `OP` (overseas vendor), `NR` (no GST number), `ZP` (0% rate), `TX` (GST number +
  9%), falling back to the vendor's `default_tax_code`.

`assign` reproduces `truth.expected_coding` byte-for-byte for both golden fixtures (verified
by test and by the smoke check below).

### `export/` — mapping, batch checks, CSV, manifest, export-once

- `mapping.py` — `config/sap_mapping.yaml` engine: `const:`, `doc.` / `vendor.` / `invoice.` /
  `coding.` / `batch.` paths, `template:` sources, `max_len` truncation, and the configured
  `date_format`. One row per coding line.
- `checks.py` — `check_batch(...)` runs all six batch checks and returns clear problems
  (`BatchError`): required columns filled, unique `(vendor, reference)`, per-invoice
  net+tax == gross, batch totals agree with documents, GL/cost-center/tax-code exist in the
  seed data, and no previously-exported `doc_id`.
- `csvio.py` — UTF-8, fully quoted CSV (`csv.QUOTE_ALL`, CRLF), with a formula-injection
  guard (`'` prefix) on free-text columns.
- `manifest.py` — batch ID, row count, total, CSV SHA-256, mapping/model/prompt/rule
  versions.
- `exporter.py` — `build_batch` (check + render), `write_batch` (CSV + manifest to disk),
  `export_documents` (end-to-end, no DB), and `record_export` (one Postgres transaction;
  relies on the schema's `export_rows.doc_id UNIQUE` for export-once).

### `evaluate/` — measures, report, and gate

- `metrics.py` — header-field accuracy (overall, by field, by type date/money/id/text), the
  share of invoices with every header field right, line-item precision/recall, coding
  accuracy (GL / cost center / tax code / overall), per-check precision/recall, and latency.
- `cli.py` — `python -m invoiceflow.evaluate` writes `reports/eval_<time>.json` + `.md`;
  `--baseline` writes `reports/baseline.json`; `--gate` fails (exit 1) when accuracy is more
  than 1 point below baseline.

## How to run it

```bash
cd ~/Projects/kallang-ws8-export
# (once) the shared uv cache dir in this environment is broken; use a scratch cache:
export UV_CACHE_DIR=/tmp/uv-cache-ws8

make test          # 187 tests pass, 95.85% coverage (80% gate)
make skeleton      # golden fixtures still route AUTO_PASSED / NEEDS_REVIEW
make lint          # ruff check clean

# SAP CSV demo (exports the reconcilable fixture, skips the total-mismatch one):
uv run python -m invoiceflow.export --out /tmp/ws8-export

# evaluation
uv run python -m invoiceflow.evaluate --baseline   # writes reports/baseline.json
uv run python -m invoiceflow.evaluate              # writes reports/eval_<time>.{json,md}
uv run python -m invoiceflow.evaluate --gate       # exit 1 if accuracy drops >1pt
```

### What the WS6 Makefile targets should call

| Target | Should call |
|---|---|
| `export` | `uv run python -m invoiceflow.export` (WS6's DAG calls `export_documents(...)` directly) |
| `eval` | `uv run python -m invoiceflow.evaluate` |
| `eval-bench` | score the benchmark set via `evaluate(samples)`; needs WS1's benchmark set first |
| `gate` | `uv run python -m invoiceflow.evaluate --gate` |

## Acceptance criteria (done-when)

- ✅ Golden fixtures produce a CSV identical to the expected file — `test_golden_csv_identical_to_expected`
  hardcodes the expected 16-column CSV and compares byte-for-byte.
- ✅ `assign` has a test per precedence rule (PO, header venue, line venue, vendor default,
  none) and for GST rounding spread (`test_split_gst`, `test_rounding_difference_lands_on_largest_line`).
- ✅ A missing required field blocks the batch with a clear message.
- ✅ An unknown GL account / cost center / tax code blocks the batch.
- ✅ A description starting with `=` is made harmless (`neutralize_formula`, `test_guard_free_text...`).
- ✅ Evaluating the truth against itself scores 100% (`test_truth_against_itself_scores_100`).

## What's left / notes

- **Wire `SapCoder` into the pipeline.** `pipeline/stubs.py` still uses `GoldenCoder`; the
  swap is the integrator's one-line change in `PipelineDeps` (per CONTRACTS.md §5). `SapCoder`
  already produces the same coding as `GoldenCoder` for both fixtures.
- **`eval-bench` needs WS1's benchmark set.** `evaluate()` accepts arbitrary `EvalSample`s,
  so only the sample-building step is missing; no changes to the measures themselves.
- **`reports/baseline.json` is force-added** (`git add -f`) because the existing `.gitignore`
  `reports/` rule swallows the `!reports/baseline.json` exception — see `docs/contract-requests.md`
  CR-001 (change `reports/` to `reports/*`).
- **The total-mismatch fixture is correctly rejected by export.** Its lines sum to 1080.00
  while its printed total is 1188.10, so `net + tax != gross` and the batch check blocks it —
  exactly the R02 anomaly the demo is about.
- Only synthetic golden data is used; Ollama was never called.
