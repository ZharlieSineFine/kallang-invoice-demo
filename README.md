# Kallang Track 10 local demo

A local, synthetic version of the Option A invoice pipeline for The Kallang Group: intake,
model extraction, normalization, checks, human review, and a hypothetical SAP CSV export.
The demo runs on this Mac; the pipeline logic is plain Python so the same functions can run
in Azure Functions later.

**On Windows:** follow [`docs/windows-setup.md`](docs/windows-setup.md). The 54 generated
invoices and the recorded model answers are in the repo, so the demo loads without the model.

**Status: Phase 0 complete** (git tag `contracts-v1`). Contracts, database schema, config,
golden fixtures, and a skeleton pipeline on stubs all work. The real stages arrive in Phase 1
across eight workstreams. The build plan lives in the Obsidian vault; the short version is
[`docs/CONTRACTS.md`](docs/CONTRACTS.md).

## What works today

```text
make skeleton
fixture                    invoice         status        expected      findings
golden-a-clean             SAV-2026-0412   AUTO_PASSED   AUTO_PASSED   none
golden-a-total-mismatch    SAV-2026-0413   NEEDS_REVIEW  NEEDS_REVIEW  R02 on subtotal
skeleton OK
```

Both golden invoices run through every pipeline stage. The stages are placeholders that replay
the recorded fixtures, but the wiring — parse → extract → normalize → code → locate → check →
route — is the real one. The twin invoice reproduces the slide-3 story: its lines add up to
S$1,080.00 while the printed subtotal says S$1,090.00, so it goes to review with R02 on the
subtotal. Everything is synthetic.

## Requirements

- macOS with Python 3.12 (managed by [uv](https://docs.astral.sh/uv/))
- Docker Desktop (only for the dev database at this stage)
- For rebuilding the fixture PDFs: Pango (`brew install pango`). The Makefile sets
  `DYLD_FALLBACK_LIBRARY_PATH` for WeasyPrint on Apple Silicon.

## Quickstart

```bash
cd ~/Projects/kallang-invoice-demo
make setup          # install dependencies, create .env from .env.example
make test           # unit + integration tests with coverage
make skeleton       # run both golden invoices through the stub pipeline

make db-dev         # Postgres 16 on 127.0.0.1:5433, then apply db/migrations
make fixtures       # load master data and both documents into the ap database
```

`make db-dev` needs Docker running. `make fixtures` loads the two golden invoices through the
stub pipeline, so the review app (WS7) has documents, boxes, line items, coding lines, and
findings to show before the real stages exist.

`make test` skips the database tests when Postgres is not running; start it first to run all
115 tests.

## Layout

```text
config/            company.yaml, rules.yaml, models.yaml, sap_mapping.yaml
db/migrations/     001_init.sql (20 tables)
docs/              CONTRACTS.md (read this), contract-requests.md
src/invoiceflow/
  contracts/       enums, frozen models, Protocols (frozen at contracts-v1)
  pipeline/        stages, stubs, golden loader, skeleton CLI
  devdb/           Phase 0 dev database: connect, migrate, load fixtures (WS6 replaces)
  parse/ extract/ normalize/ locate/ rules/ coding/ export/ evaluate/ store/ storage/
                   Phase 1 workstream modules (empty placeholders today)
tests/
  unit/            contracts, config, pipeline, devdb
  integration/db/  schema and fixture-load tests (skipped without Postgres)
  fixtures/golden/ two invoices + page image + words + recorded response + truth
scripts/           build_golden.py, migrate.py, load_fixtures.py
compose.dev.yaml   Postgres alone (the full Airflow stack is WS6)
```

## Dev database

Defaults come from `.env` (created by `make setup`) and fall back to
`postgresql://ap:change-me@127.0.0.1:5433/ap`. Override with `AP_DATABASE_URL`.

Migrations are applied once each and tracked in `schema_migrations`. `make fixtures` truncates
the invoice tables and reloads the golden set in one transaction; it is safe to run twice.

`devdb/` is scaffolding for Phase 0. WS6 replaces it with `invoiceflow.store` (the
`Repository`) and `invoiceflow.storage` (`LocalBlobStore`) behind the same contracts.

## Commands

| Command | Does |
|---|---|
| `make help` | list targets |
| `make setup` | `uv sync --all-extras`; create `.env` |
| `make doctor` | check uv, Docker, Ollama, and the dev database |
| `make test` | pytest with coverage (80% minimum) |
| `make lint` / `make fmt` | ruff check / format |
| `make skeleton` | both fixtures through the stub pipeline |
| `make db-dev` / `make down` | start / stop the dev Postgres |
| `make fixtures` | load the golden set into the database |
| `make golden` | rebuild the fixture PDFs, words, and truth files |

Phase 1 targets owned by WS6 (`up`, `down`, `logs`, `drop`, `export`, `snapshot`, `restore`,
`reset`, `e2e`) are wired; the others (`data`, `warm`, `demo-data`, `eval`, `eval-bench`,
`gate`, `bench`) still print the workstream that owns them and stop.

## Full stack (WS6)

`make up` builds and starts the Airflow 3.3.2 stack and is healthy in under 2 minutes. It runs
one Postgres with two databases (`airflow`, `ap`), the Airflow API server / scheduler /
dag-processor / triggerer on `LocalExecutor` with the SimpleAuthManager (everyone is admin, so
it is local-only), and the review-app placeholder. Everything binds to 127.0.0.1 (Airflow
8080, review app 8501).

```bash
make setup && make up    # build + start, wait until healthy
make drop                # copy golden-a-clean into data/inbox
make export              # trigger the sap_export DAG
make e2e                 # inbox -> silver -> export, in replay mode, no Airflow
```

Three DAGs live in `dags/`: `invoice_intake` (every 5 minutes and on demand, one task per
document in the one-slot `llm` pool), `sap_export` (18:00 Singapore time and on demand), and
`evaluate` (on demand). With the Phase 1 stubs the golden fixtures move inbox → bronze →
silver, and running `sap_export` twice leaves the second batch with zero rows (export-once is
enforced by `export_rows.doc_id`).

Idle memory from `docker stats` after `make up` (six containers): **≈1.4 GiB** —
scheduler ~543 MiB, api-server ~277 MiB, triggerer ~263 MiB, dag-processor ~174 MiB, postgres
~77 MiB, review-app ~55 MiB.

## Next

Phase 1 fans out eight workstreams against tag `contracts-v1`:

| WS | Builds |
|---|---|
| WS1 | synthetic invoices, seeds, fonts |
| WS2 | PDF/OCR parsing, hidden-text detection, page images |
| WS3 | Ollama extraction, prompt, replay cache, benchmark |
| WS4 | normalization and on-page location |
| WS5 | checks R01–R12 and routing |
| WS6 | Airflow, Postgres store, blob storage, DAGs, scripts |
| WS7 | Streamlit review app and dashboard |
| WS8 | SAP coding, CSV export, evaluation |

See `docs/CONTRACTS.md` for what each workstream owns and how to request a contract change.

## Notes

- Every name, UEN, bank account, GL account, cost center, and tax code is fictional. UENs use
  the year 2099, which cannot belong to a real company.
- The synthetic dataset was chosen over a Kaggle CRM dataset; the comparison is in
  [`docs/data-decision.md`](docs/data-decision.md).
- The SAP layout is `hypothetical` in `config/sap_mapping.yaml`; it is labeled as such in the
  manifest and will be replaced when Kallang's real template arrives.
- Tesseract 5.5.4 is installed for local OCR tests; the Docker image installs its own copy.
- Gemma 4 12B on Ollama is the chosen model, with `qwen3-vl:4b` as the fallback. Neither is
  wired yet; WS3 owns that.
