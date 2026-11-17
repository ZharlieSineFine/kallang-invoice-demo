# Kallang Track 10 local demo — WS6 platform and pipelines.
# `make up` runs the full Airflow stack; `make db-dev` runs the dev Postgres alone.
SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
# `docker-compose` (the standalone binary) works even when a global DOCKER_CONFIG hides the
# `docker compose` cli-plugin; override with COMPOSE="docker compose" if you prefer.
COMPOSE ?= docker-compose
COMPOSE_FULL := $(COMPOSE) -f docker-compose.yaml
COMPOSE_DEV := $(COMPOSE) -f compose.dev.yaml
N ?= golden-a-clean
MODEL ?= gemma4:12b
SEED ?= 42

# WeasyPrint needs Homebrew's Pango, which is not on the default library path.
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
GOLDEN_ENV := DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
else
GOLDEN_ENV :=
endif

.PHONY: help setup doctor up down down-dev logs db-dev fixtures skeleton golden test lint fmt \
        data warm demo-data demo-ready live-set erase-live intake-local drop drop-all drop-live intake export eval eval-bench gate bench snapshot restore reset e2e \
        check-dags

help: ## show this help
	@echo "Kallang Track 10 local demo — WS6 platform and pipelines"
	@echo
	@grep -E '^[a-zA-Z0-9_.-]+:.*## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Demo:        make setup && make data && make up && make reset"
	@echo "             full run:  make drop-all && make intake   (wait for all 50)"
	@echo "             live:      make drop-live && make intake  (about 2 min)"
	@echo "             then:      make export"
	@echo "Dev checks:  make test && make skeleton"
	@echo "Dev DB:      make db-dev && make fixtures"

setup: ## install dependencies and create .env from the example
	$(UV) sync --all-extras
	@if [ ! -f .env ]; then cp .env.example .env; echo "created .env from .env.example"; fi
	@if ! grep -q '^AIRFLOW_UID=' .env; then echo "AIRFLOW_UID=$(shell id -u)" >> .env; echo "set AIRFLOW_UID=$(shell id -u)"; fi
	@echo "setup done"

doctor: ## check the tools and ports the full stack needs
	@bash scripts/doctor.sh

up: ## start the full stack and wait until healthy
	$(COMPOSE_FULL) up -d --build --wait --wait-timeout 120
	@echo "full stack is up: Airflow on http://127.0.0.1:8080, review on http://127.0.0.1:8501"

down: ## stop the full stack
	$(COMPOSE_FULL) down

down-dev: ## stop the dev Postgres
	$(COMPOSE_DEV) down

logs: ## follow the full-stack logs
	$(COMPOSE_FULL) logs -f

db-dev: ## start Postgres and apply migrations
	$(COMPOSE_DEV) up -d --wait
	@$(UV) run python scripts/migrate.py

fixtures: ## load the golden fixtures into the dev database
	@$(UV) run python scripts/load_fixtures.py

skeleton: ## run both golden invoices through every stub stage
	@$(UV) run python -m invoiceflow.pipeline.skeleton

golden: ## rebuild the golden fixture files (needs Pango for WeasyPrint)
	$(GOLDEN_ENV) $(UV) run python scripts/build_golden.py

test: ## run unit and integration tests with coverage
	$(UV) run pytest --cov --cov-report=term-missing

lint: ## ruff check
	$(UV) run ruff check .

fmt: ## format and auto-fix
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

check-dags: ## DAG import test (needs make up)
	@bash scripts/check_dags.sh

# ---- Phase 1 targets owned by other workstreams: message and stop -------------
data: ## generate the synthetic invoice set (SEED defaults to 42)
	@$(GOLDEN_ENV) $(UV) run python generator/build.py --seed $(SEED)

warm: ## load the model and keep it loaded (WS3)
	@echo "make warm: WS3 wires Ollama (MODEL=$(MODEL))."
	@exit 1

demo-data: ## rehearse the demo: every generated invoice through the real pipeline, oldest first, scored, replay cache recorded (RESET=1 wipes existing documents, STACK=1 targets the full stack)
	@$(UV) run python scripts/demo_data.py $(if $(RESET),--reset) $(if $(STACK),--stack)

demo-ready: ## reset and load the 54 demo invoices (LLM_MODE=replay uses the recorded answers); the 5 in data/live-demo-new stay unseen
	@$(UV) run python scripts/demo_data.py --reset

live-set: ## (re)build the 5 live-demo invoices in data/live-demo-new (never loaded by demo-data)
	@$(UV) run python -m generator.live_set

erase-live: ## remove the live-demo invoices (data/live-demo-new, or FOLDER=...) from the database and data/, keeping the 54; DRY=1 only shows
	@$(UV) run python scripts/erase_live.py $(if $(FOLDER),--folder $(FOLDER)) $(if $(DRY),--dry-run)

drop: ## copy a golden fixture into data/inbox (WS1 live docs replace this)
	@mkdir -p data/inbox
	@cp tests/fixtures/golden/$(N)/invoice.pdf data/inbox/$(N).pdf
	@echo "dropped $(N) into data/inbox/$(N).pdf (invoice_intake picks it up)"

drop-all: ## copy the 50 full-run invoices into data/inbox in arrival order (times from the manifest)
	@$(UV) run python scripts/drop.py invoices

drop-live: ## copy the 5 live-demo invoices (data/live-demo-new) into data/inbox
	@$(UV) run python scripts/drop.py live-demo-new

intake-local: ## process data/inbox (e.g. Upload page files) into the dev database without Airflow
	@$(UV) run python scripts/intake_local.py

intake: ## run invoice_intake now instead of waiting for its 5-minute schedule (needs make up)
	$(COMPOSE_FULL) exec -T airflow-scheduler airflow dags trigger invoice_intake
	@echo "triggered invoice_intake"

export: ## trigger the sap_export DAG (needs make up)
	$(COMPOSE_FULL) exec -T airflow-scheduler airflow dags trigger sap_export
	@echo "triggered sap_export"

eval: ## write the evaluation report (WS8)
	@echo "make eval: WS8 builds the evaluator."
	@exit 1

eval-bench: ## score the benchmark set (WS8)
	@echo "make eval-bench: WS8 builds this."
	@exit 1

gate: ## fail if accuracy drops below the baseline (WS8)
	@echo "make gate: WS8 builds the release gate."
	@exit 1

bench: ## run the model benchmark (WS3)
	@echo "make bench: WS3 builds scripts/bench_models.py."
	@exit 1

# ---- WS6 demo-state targets ---------------------------------------------------
snapshot: ## save demo state (pg_dump + tar of data/), NAME in $(N)
	@bash scripts/snapshot.sh $(N)

restore: ## restore demo state, NAME in $(N)
	@bash scripts/restore.sh $(N)

reset: ## wipe demo state (truncate ap + clear data/)
	@bash scripts/reset.sh

e2e: ## golden fixture inbox -> silver -> export, in replay mode
	@$(UV) run python scripts/e2e.py
