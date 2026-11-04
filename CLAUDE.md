# CLAUDE.md — Kallang Track 10 local demo

Local, synthetic version of the Option A invoice pipeline for The Kallang Group: intake →
model extraction → normalization → on-page checks → human review → hypothetical SAP CSV
export. Phase 1 is **complete and merged**; remaining work is the Phase 2 visual demo and
rehearsal prep. All data is synthetic.

## Where things stand (2026-11-04)

- Phase 0 (contracts, schema, golden fixtures, stub pipeline) is tagged `contracts-v1`.
- All eight Phase 1 workstreams are merged into `main`; the pipeline runs on the **real**
  stages (parse/extract/normalize/locate/rules/coding), not stubs.
- Gates verified: `make test` = 729 passed (≈96% coverage); `make skeleton` routes
  golden-a-clean → AUTO_PASSED and golden-a-total-mismatch → NEEDS_REVIEW/R02 with the live
  gemma4:12b model; `make e2e` = `e2e OK` (export twice, second batch 0 rows).
- The visual demo from `docs/demo-plan.md` is built: Demo page (`app/pages/story.py`), flow
  strip and technical toggle (`app/flow.py`), inbox grid (`app/inbox.py`), compliance cards
  (`app/compliance.py`), CSV trace (`app/csv_trace.py`). It needs the demo data loaded; see
  "Next work".
- Recent fixes: Queue "Open in Review" uses an on_click callback; finding cards render as
  raw HTML with explicit text colors (Streamlit's markdown parser otherwise turns `$…$`
  amounts into LaTeX math, and dark theme makes inherited text unreadable).

## Read these first (in order)

1. `docs/CONTRACTS.md` — frozen contracts, workstream ownership, change process.
2. `docs/fanout/MERGE-RUNBOOK.md` — Phase 2 merge/integration gates.
3. `docs/fanout/PHASE1-VERIFICATION.md` — manual, one-line-command verification walkthrough.
4. `docs/demo-plan.md` — the visual demo plan (next big piece of work).
5. The authoritative build plan lives in the user's Obsidian vault:
   `~/Obsidian Vaults/Charliencyclopedia/PTC Systems AIOps Engineer Intern/AI MVP Hackathon/Track 10 Local Demo Build Plan.md`.

## Commands (all from the repo root, one line each)

```bash
make test            # pytest + coverage (80% gate) — includes live Ollama tests
make skeleton        # both golden invoices through the REAL stages (live model, 2-4 min)
LLM_MODE=replay make skeleton   # same, no model calls (serves data/llm_cache)
make db-dev && make fixtures    # Postgres 16 on 5433 + load the golden documents
make e2e             # inbox -> silver -> export, replay mode, rollback transaction
uv run streamlit run app/main.py   # review app on http://localhost:8501
make up              # full Airflow stack (8080) + review app (8501); make down to stop
uv run python generator/build.py --seed 42        # rebuild the 50-document dataset
uv run python scripts/stage_benchmark.py          # stage bench-* for bench_models.py
uv run python scripts/bench_models.py --docs data/benchmark --out data/bench --modes text,image --dpi 150 --limit 2
uv run python -m invoiceflow.export               # SAP CSV from the golden fixtures
uv run python -m invoiceflow.evaluate --gate      # evaluation + gate
```

Environment: uv 0.11.x, Python 3.12, Docker Desktop, `docker-compose` standalone, Ollama
with gemma4:12b (fallback qwen3-vl:4b deliberately not pulled), Tesseract 5.5.4. WeasyPrint
needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` on macOS. Dev Postgres:
`postgresql://ap:change-me@127.0.0.1:5433/ap` (`.env`).

## Conventions

- Money is `Decimal`; models are frozen Pydantic (`extra="forbid"`); boxes are page
  fractions 0-1 from top-left; one file = one invoice.
- Contracts are frozen: workstreams file requests in `docs/contract-requests.md`
  (CR-001..006 are accepted). New features that need contract changes go through there.
- Tests first, ruff clean, synthetic data only, no new dependencies.
- Unwired make targets: `data`, `warm`, `demo-data`, `bench`, `eval`, `eval-bench`, `gate`
  print a message and exit — call the underlying CLIs directly (see above).

## Next work (in order)

1. Close the gaps the visual demo exposed: `sap_export` still writes the 8-column stub CSV, and
   only APPROVED documents export (not AUTO_PASSED); the pipeline's master data has one vendor;
   `documents.doc_type` is never written; R11 flags every date with day <= 12 as ambiguous;
   R02/R03 misread GST-inclusive simplified invoices.
2. Phase 2 gates per `docs/fanout/MERGE-RUNBOOK.md`: `make bench`/`eval-bench`, model-choice
   note, `make demo-data`, e2e in replay with Ollama stopped, reviewers, rehearsal,
   snapshot/restore.
3. Wire the remaining make targets to the existing CLIs.
