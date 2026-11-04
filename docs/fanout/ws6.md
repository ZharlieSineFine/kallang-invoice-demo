# Brief: WS6: Platform and pipelines

You are building workstream **WS6: Platform and pipelines** of the Kallang Track 10 local demo
(AI invoice processing for The Kallang Group; full plan: Track 10 Local Demo Build Plan.md
in the user's Obsidian vault).

- Worktree: ~/Projects/kallang-ws6-platform (branch `ws6-platform`, based on tag `contracts-v1`).
- Read first: `docs/CONTRACTS.md`, `src/invoiceflow/contracts/`, `tests/fixtures/golden/`.
- Your section of the build plan is pasted below. It lists what to build, what you own, and
  when you are done.
- You own only: `docker/`, `docker-compose.yaml`, `compose.dev.yaml`, `db/`, `src/invoiceflow/store/`, `src/invoiceflow/storage/`, `src/invoiceflow/pipeline/`, `dags/`, `scripts/` (except `bench_models.py`), `Makefile`, plus your tests under `tests/unit/store/`, `tests/unit/storage/`, `tests/unit/pipeline/`, and `tests/integration/ws6/`. Do not edit anything else.
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


### WS6: Platform and pipelines (build plan section)

Build:

- **`docker-compose.yaml`**, based on the official Airflow 3.3.2 file:
  - Remove redis, airflow-worker, flower, and the Celery settings.
  - Set `LocalExecutor`.
  - Keep the execution API URL pointing at the api-server service.
  - Use the SimpleAuthManager with `simple_auth_manager_all_admins = True`. This means no
    login, so keep it local only.
  - Set the default time zone to Asia/Singapore.
  - Publish ports on 127.0.0.1 only.
  - Add `review-app`, and one Postgres with two databases (airflow, ap).
- **`docker/airflow.Dockerfile`:** `FROM apache/airflow:3.3.2-python3.12`, install
  `tesseract-ocr`, then install the package.
- **Storage code:**
  - a migration runner in airflow-init
  - `store/repo.py`, using psycopg 3 with parameterized SQL only
  - `storage/LocalBlobStore`, which names files by their content hash and never overwrites
    bronze files
- **`pipeline/` step functions and three DAGs:**
  - `invoice_intake` runs every 5 minutes and on demand, with `max_active_runs=1`. It maps one
    task per document, and runs extraction in the one-slot `llm` pool with 2 retries.
  - `sap_export` runs at 18:00 Singapore time and on demand.
  - `evaluate` runs on demand.
- **Scripts:**
  - the Makefile targets listed in section 9 (see below)
  - `scripts/doctor.sh`, which checks that Docker is running, its memory cap, that Ollama is
    reachable from inside a container, that the models are pulled, and that ports 8080 and
    8501 are free
  - `snapshot` and `restore`, using `pg_dump` plus a tar of `data/`

Implement the `BlobStore` and `Repository` protocols from `contracts/interfaces.py`. The
Phase 0 `devdb/` scaffolding (migration runner, fixture loader) is a reference; replace its
role with `store/` + `storage/`. Keep `compose.dev.yaml` and `make db-dev`/`make fixtures`
working.

Makefile targets to implement/stub per section 9: setup, doctor, up, down, logs, db-dev,
fixtures, skeleton, data, warm, demo-data, drop (N=), export, eval, eval-bench, gate, bench,
snapshot, restore, reset, test, e2e. (WS1's `generator/` CLI, WS3's `bench_models.py`, and
WS8's export/evaluate CLIs provide the commands these targets call; wire what exists now and
leave a clear message for the rest.)

### WS6 done when

- `make up` is healthy in under 2 minutes.
- The DAG import test shows no errors.
- With stubs, the golden fixture moves from the inbox to silver. (The pipeline stages are
  still stubs; that is fine — wire the DAGs/storage now, the integrator swaps in the real
  stages in Phase 2.)
- Running the export twice produces a second batch with zero rows.
- Idle memory use from `docker stats` is measured and written into the README.

Watch out for:

- Airflow 3 tasks talk to Airflow through its API, not its database. Keep invoice data in the
  `ap` database.
- If containers can't reach `host.docker.internal:11434`, run
  `launchctl setenv OLLAMA_HOST "0.0.0.0:11434"` and restart Ollama. This also exposes Ollama
  to your network, so undo it after the demo. Do not call Ollama yourself.
- Docker Desktop is running with the dev Postgres on 5433; ports 8080 and 8501 must stay free;
  bind everything to 127.0.0.1.
- If `docker build` complains it cannot write `~/.docker`, use
  `DOCKER_CONFIG=/Users/huskydawg/Projects/.docker-config` (this directory already exists).

