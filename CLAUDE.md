# CLAUDE.md — Kallang Track 10 local demo

Local, synthetic version of the Option A invoice pipeline for The Kallang Group: intake →
model extraction → normalization → on-page checks → human review → hypothetical SAP CSV
export. Phase 1 is **complete and merged**; remaining work is the Phase 2 visual demo and
rehearsal prep. All data is synthetic.

## Where things stand (2026-11-13)

- Phase 0 (contracts, schema, golden fixtures, stub pipeline) is tagged `contracts-v1`.
- All eight Phase 1 workstreams are merged into `main`; the pipeline runs on the **real**
  stages (parse/extract/normalize/locate/rules/coding), not stubs.
- Branch `feat/visual-demo`: the visual demo from `docs/demo-plan.md` (Demo page, flow strip,
  technical toggle, inbox grid, compliance cards, CSV trace) is committed. The fixes that
  make it run on real data were uncommitted as of 2026-11-13 (check `git status`).
- `make demo-data RESET=1` loads the 36-invoice "yesterday" batch through gemma4:12b (about
  20 min, ~26 s per invoice) and scores it against the generator's planted checks. Live run
  2026-11-13: 32 of 36 matched; header accuracy 97.14% on 35 (the byte-identical copy is
  skipped at intake); check precision 72.7%, recall 100%, coding 85.7%. The 4 that differ
  are model misreads the checks caught (pre-cn-02, pre-usd-01), an OCR bank-digit misread
  (pre-c-02, R08 FLAG), and R06 following R04 on the unknown vendor (pre-c-04).
- The live set (live-01..04) routes as planned: AUTO_PASSED, R02, R08, R09.
- Replay works with no model: `LLM_MODE=replay make demo-data RESET=1` reproduces the live run
  in ~16 s; `make e2e` passes the same way.
- Full stack verified 2026-11-13: containers reach host Ollama, the `sap_export` DAG writes the
  16-column CSV (19 rows), and the container review app runs `app/main.py` (it served a WS6
  placeholder before; `docker/review_app.py` is now unused).
- `make test`: 839 passed (without the live-model tests).

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
make demo-data RESET=1   # 36 "yesterday" invoices through the live model (~20 min), scored
make demo-data RESET=1 STACK=1   # same, into the full stack's Postgres on 127.0.0.1:5434
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
  (CR-001..007 are accepted). New features that need contract changes go through there.
- Tests first, ruff clean, synthetic data only, no new dependencies.
- Unwired make targets: `warm`, `bench`, `eval`, `eval-bench`, `gate` print a message and
  exit — call the underlying CLIs directly (see above). `make data` and `make demo-data` work.
- `python -m invoiceflow.evaluate` scores the golden truth against itself (always 100%). It
  proves the scoring code, not the model, so it never writes `reports/latest.json`; only
  `make demo-data` does, from real pipeline output.
- Reviewer changes never auto-pass: a clean recheck after a correction goes to NEEDS_REVIEW,
  a correction clears a FLAG on that field but never a HOLD, and a HOLD needs a release
  comment before approval.
- Ollama's runner grows about 1 GB per request on this Mac; `unload_above_gb` in
  `config/models.yaml` unloads the model after a request once it passes that size.

## Next work (in order)

1. Decide R03 on a 0% rate: it flags the USD invoice's zero-rated "0%" as a wrong rate.
2. Phase 2 gates per `docs/fanout/MERGE-RUNBOOK.md`: `make bench`/`eval-bench`, model-choice
   note, reviewers, rehearsal, snapshot/restore.
3. Wire the remaining make targets (`warm`, `bench`, `eval`, `eval-bench`, `gate`).
4. Demo gaps: no in-app export button (export runs through Airflow) and no live flow strip
   during an upload.
5. Before loading with `STACK=1`, empty `data/inbox`: the stack's intake DAG picks up any
   file there while the load runs.
