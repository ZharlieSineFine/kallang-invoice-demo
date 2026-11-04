# HANDOFF — WS6: Platform and pipelines

Branch `ws6-platform`, based on tag `contracts-v1`. All acceptance criteria verified on this
Mac (Docker Desktop running, dev Postgres on 5433, Ollama pulled but **not called by WS6**).

> **Commit status:** the working tree changes are complete and `make test` passes, but the
> `git add`/`git commit` step is blocked by the harness sandbox (the shared git metadata lives
> under `~/Projects/kallang-invoice-demo/.git`, outside this worktree's write scope, and the
> escalation approval channel is unavailable). To commit, run from the worktree:
>
> ```bash
> cd ~/Projects/kallang-ws6-platform
> git add Makefile README.md .dockerignore HANDOFF-ws6.md docker-compose.yaml docker/ dags/ \
>   db/init/ scripts/ src/invoiceflow/pipeline/steps.py src/invoiceflow/storage/ \
>   src/invoiceflow/store/ tests/integration/ws6/ tests/unit/pipeline/test_steps.py \
>   tests/unit/storage/ tests/unit/store/
> git commit -m "WS6: platform and pipelines"
> ```

## What's done

### Platform (`docker/`, `docker-compose.yaml`, `compose.dev.yaml`, `db/`)

- **`docker-compose.yaml`** — the full stack, adapted from the official Airflow 3.3.2 file:
  - redis, `airflow-worker`, and flower removed; all Celery settings dropped; executor is
    `LocalExecutor`.
  - `AIRFLOW__CORE__EXECUTION_API_SERVER_URL` points at the `api-server` service.
  - SimpleAuthManager (Airflow 3's default) with
    `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS: 'true'` — no login, local-only.
  - Default timezone `Asia/Singapore`; examples not loaded; DAGs unpaused on creation.
  - Every published port binds to `127.0.0.1` (Airflow API 8080, review app 8501).
  - One Postgres with two databases: `airflow` (metadata) and `ap` (invoice data), created by
    `db/init/01-create-ap-db.sh` on first volume init.
  - `airflow-init` runs `airflow db migrate`, creates the one-slot `llm` pool
    (`airflow pools set llm 1 …`), then applies `db/migrations` to `ap` via
    `python -m invoiceflow.store.migrate`.
  - `review-app` service (placeholder in `docker/review_app.py` until WS7 lands `app/app.py`).
- **`docker/airflow.Dockerfile`** — `FROM apache/airflow:3.3.2-python3.12`, installs
  `tesseract-ocr`, then `pip install ".[app]"` (the `app` extra gives the review-app streamlit).
- **`.dockerignore`** — keeps `.venv`, `.uv-cache`, `data/`, `.env`, etc. out of the build
  context.

### Store and storage (`src/invoiceflow/store/`, `src/invoiceflow/storage/`)

- `store/connection.py` — `database_url()`, `safe_url()`, `connect()` (AP_DATABASE_URL or
  AP_DB_* parts; dev default 127.0.0.1:5433).
- `store/migrate.py` — the production migration runner (advisory-locked, idempotent) plus a
  `python -m invoiceflow.store.migrate` CLI for `airflow-init`.
- `store/repo.py` — `Repo`, the `Repository` protocol over psycopg 3 with **parameterized SQL
  only**. `fields`/`line_items`/`coding_lines` are append-with-history (`is_current`), and
  `record_export` relies on `export_rows.doc_id` uniqueness to enforce export-once.
  Extra (non-protocol) helpers: `save_master`, `master_loaded`, `coding_lines`.
- `store/fixtures.py` — the golden fixture loader (truncate → save master → intake each golden
  PDF), replacing `devdb/fixtures.py`'s role for `make fixtures`.
- `storage/local.py` — `LocalBlobStore`: content-addressed, write-once `bronze/`,
  doc-scoped `silver/`, batch-scoped `gold/`, plus the shared path helpers.

### Pipeline steps and DAGs (`src/invoiceflow/pipeline/steps.py`, `dags/`)

- `steps.py` (no Airflow imports): `intake_document`, `intake_inbox`, `ensure_master`,
  `export_approved`, `evaluate`, `golden_pipeline`, `list_inbox`, `move_processed`,
  `guess_mime`.
- `dags/invoice_intake.py` — every 5 minutes + on demand, `max_active_runs=1`, maps one task
  per document, extraction runs in the one-slot `llm` pool with `retries=2`.
- `dags/sap_export.py` — 18:00 Singapore time + on demand.
- `dags/evaluate.py` — on demand.

### Scripts and Makefile

- Makefile targets wired: `setup`, `doctor`, `up`, `down`, `down-dev`, `logs`, `db-dev`,
  `fixtures`, `skeleton`, `golden`, `test`, `lint`, `fmt`, `check-dags`, `drop`, `export`,
  `snapshot`, `restore`, `reset`, `e2e`.
- Makefile targets left as clear messages for other workstreams: `data` (WS1), `warm` (WS3),
  `demo-data` (WS3/WS6), `eval`/`eval-bench`/`gate` (WS8), `bench` (WS3).
- `scripts/doctor.sh` — checks Docker + memory cap, Ollama reachable from host **and from
  inside a container** (`host.docker.internal`), `gemma4:12b` pulled, ports 8080/8501 free.
- `scripts/snapshot.sh` / `restore.sh` — `pg_dump`/`psql` of `ap` (via `docker compose exec`)
  plus a `tar` of `data/`; `scripts/reset.sh` — truncate `ap` + clear `data/`.
- `scripts/e2e.py` — `make e2e`: golden fixture inbox → silver → export twice, in replay mode.
- `scripts/migrate.py`, `scripts/load_fixtures.py` — repointed from `devdb/` to `store/` +
  `storage/`.

## How to run it

```bash
cd ~/Projects/kallang-ws6-platform

# One-time setup (creates .env, adds AIRFLOW_UID for macOS)
make setup

# Full stack (builds the image the first time; healthy in < 2 minutes)
make up

# Verify the DAGs import and the pool exists
make check-dags

# Demo the intake: drop a golden fixture into the inbox, then trigger the DAG
make drop N=golden-a-clean
docker compose -f docker-compose.yaml exec -T airflow-scheduler airflow dags trigger invoice_intake

# Export (approve the documents first, or the batch is empty), then run again for zero rows
docker compose -f docker-compose.yaml exec -T postgres psql -U ap -d ap \
  -c "UPDATE documents SET status='APPROVED' WHERE status IN ('AUTO_PASSED','NEEDS_REVIEW')"
make export

# Host-side, no-Airflow replay check of the same flow
make e2e

# Dev database (review app / tests) is separate from the full stack
make db-dev && make fixtures
```

Environment gotchas for this Mac:

- `uv` needs a writable cache: `export UV_CACHE_DIR=$PWD/.uv-cache` (a global
  `UV_CACHE_DIR=/Users/huskydawg/Projects/.uv-cache` points at a dir the sandbox can't open).
- `docker compose` (the plugin) is hidden when `DOCKER_CONFIG` points at
  `/Users/huskydawg/Projects/.docker-config`; the Makefile/scripts default to the standalone
  `docker-compose` binary (`COMPOSE=docker compose` overrides).
- `AIRFLOW_UID` is written to `.env` by `make setup` so the container user matches your macOS
  uid and the bind mounts are readable.
- Ollama reachability from a container uses `host.docker.internal:11434`; if that fails run
  `launchctl setenv OLLAMA_HOST "0.0.0.0:11434"` and restart Ollama (undo after the demo).
  **WS6 never calls the model.**

## Verification (done-when)

| Criterion | Result |
|---|---|
| `make up` healthy in under 2 minutes | **1m 29.8s**, all six services healthy |
| DAG import test shows no errors | `make check-dags` → 3 DAGs, "No data found" |
| Golden fixture moves inbox → silver (stubs) | 2 documents land in `ap` (`AUTO_PASSED`, `NEEDS_REVIEW`) with bronze + silver blobs |
| Export twice → second batch zero rows | first `sap_export` 2 rows / 2355.30, second 0 rows / 0.00 |
| Idle memory measured and written to README | **≈1.4 GiB** across six containers (written into `README.md`) |

`make test`: **160 passed**, coverage **95.6%** (80% gate). `ruff check`/`ruff format` clean.

## What's left

- **WS1/Ws2/Ws3/Ws4/Ws5/Ws7/Ws8** swap the stubs in `pipeline/stubs.py` for the real stages
  (`PipelineDeps` is the single swap point). The DAGs call `golden_pipeline()` today; the
  integrator points them at the real deps in Phase 2.
- **WS3** owns Ollama and the replay cache; `warm`, `demo-data`, `bench` are still messages.
- **WS7** owns `app/` — replace `docker/review_app.py` with `app/app.py` in `docker-compose.yaml`.
- **WS8** owns the real SAP CSV (16-column `config/sap_mapping.yaml` layout), the evaluator,
  and `eval`/`eval-bench`/`gate`. `export_approved` writes a 1-row-per-coding-line stub CSV.
- `evaluate` DAG is a counting stub; WS8 adds accuracy scoring.
- The duplicate check (`prior_invoices`) is wired in the repository but not yet exercised by
  the stub pipeline (the golden stub rule R00 doesn't read it).
- `make snapshot`/`restore`/`reset` require the full stack to be up (they use
  `docker compose exec` against the stack Postgres, not the dev Postgres on 5433).

## Notes

- Two Postgres instances exist on purpose: the dev one (`compose.dev.yaml`, 127.0.0.1:5433,
  used by `make test`/`make fixtures`/the review app in dev) and the full-stack one (inside
  the Docker network, `airflow` + `ap`). `data/` is shared between them, so bronze/silver/gold
  blobs from both land in the same tree.
- `scripts/load_fixtures.py` and `make fixtures` still work against the dev database; the
  full-stack `ap` database is populated by the `invoice_intake` DAG (master data is loaded
  lazily by `ensure_master` on first intake).
