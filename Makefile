# Kallang Track 10 local demo.
# Phase 0 targets work today. Phase 1 targets name their owner and exit non-zero.
SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
COMPOSE_DEV := docker compose -f compose.dev.yaml
N ?= live-01

# WeasyPrint needs Homebrew's Pango, which is not on the default library path.
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
GOLDEN_ENV := DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
else
GOLDEN_ENV :=
endif

.PHONY: help setup doctor up down logs db-dev fixtures skeleton golden test lint fmt \
        data warm demo-data drop export eval eval-bench gate bench snapshot restore reset e2e

help: ## show this help
	@echo "Kallang Track 10 local demo — Phase 0 (contracts and a skeleton pipeline)"
	@echo
	@grep -E '^[a-zA-Z0-9_.-]+:.*## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Phase 0 flow:  make setup && make test && make skeleton"
	@echo "Database:      make db-dev && make fixtures"

setup: ## install dependencies and create .env from the example
	$(UV) sync --all-extras
	@if [ ! -f .env ]; then cp .env.example .env; echo "created .env from .env.example"; fi
	@echo "setup done"

doctor: ## check the tools Phase 0 needs
	@command -v uv >/dev/null && echo "uv:           $$(uv --version)" || echo "uv:           MISSING"
	@docker info >/dev/null 2>&1 && echo "docker:       running" \
	  || echo "docker:       NOT running (start Docker Desktop)"
	@curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 \
	  && echo "ollama:       reachable" || echo "ollama:       not reachable (needed from WS3 on)"
	@$(UV) run python -c 'from invoiceflow.devdb.connection import connect; connect().close()' \
	  >/dev/null 2>&1 && echo "dev database: reachable" \
	  || echo "dev database: not running (make db-dev)"

up: ## start the full stack (WS6)
	@echo "make up: not in Phase 0. WS6 builds docker-compose.yaml."
	@echo "For now use: make db-dev"
	@exit 1

down: ## stop the dev database
	$(COMPOSE_DEV) down

logs: ## follow the full-stack logs (WS6)
	@echo "make logs: not in Phase 0. WS6 builds the full stack."
	@echo "Dev Postgres logs: docker compose -f compose.dev.yaml logs -f"
	@exit 1

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

data: ## generate the synthetic invoice set (WS1)
	@echo "make data: WS1 builds the generator in Phase 1 (SEED defaults to 42)."
	@exit 1

warm: ## load the model and keep it loaded (WS3)
	@echo "make warm: WS3 wires Ollama in Phase 1 (MODEL= picks a different one)."
	@exit 1

demo-data: ## process the yesterday batch and record the replay cache (WS3, WS6)
	@echo "make demo-data: WS3 and WS6 build this in Phase 1."
	@exit 1

drop: ## copy one live document into the inbox (WS1, WS6)
	@echo "make drop N=$(N): WS1 writes the live documents; WS6 copies them to data/inbox/."
	@exit 1

export: ## start sap_export (WS6, WS8)
	@echo "make export: WS6 wires the DAG; WS8 writes the SAP CSV."
	@exit 1

eval: ## write the evaluation report (WS8)
	@echo "make eval: WS8 builds the evaluator in Phase 1."
	@exit 1

eval-bench: ## score the benchmark set (WS8)
	@echo "make eval-bench: WS8 builds this in Phase 1."
	@exit 1

gate: ## fail if accuracy drops below the baseline (WS8)
	@echo "make gate: WS8 builds the release gate in Phase 1."
	@exit 1

bench: ## run the model benchmark (WS3)
	@echo "make bench: WS3 builds scripts/bench_models.py in Phase 1."
	@exit 1

snapshot: ## save demo state (WS6)
	@echo "make snapshot: WS6 builds this in Phase 1."
	@exit 1

restore: ## restore demo state (WS6)
	@echo "make restore: WS6 builds this in Phase 1."
	@exit 1

reset: ## wipe demo state (WS6)
	@echo "make reset: WS6 builds this in Phase 1."
	@exit 1

e2e: ## run end to end in replay mode (WS6)
	@echo "make e2e: WS6 builds this in Phase 1."
	@exit 1
