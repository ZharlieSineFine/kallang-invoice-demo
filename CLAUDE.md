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
  technical toggle, inbox grid, compliance cards, CSV trace) is committed, and the real-data
  fixes are committed as `c122ff3`. The two-folder dataset and the "Processing…" card were
  uncommitted as of 2026-11-13 (check `git status`).
- Dataset: `make data` writes 50 invoices for the recorded full run (`invoices/`) and 4 for
  the live demo (`live-demo/`: two digital PDFs, two scans), named by invoice number.
- `make demo-data RESET=1` runs the 50, then the 4, through gemma4:12b (~27 min, ~30 s per
  invoice) and scores them against the generator's planted checks. Live run 2026-11-13: 47
  of 54 matched; header accuracy 96.97% on 53 (the byte-identical copy is skipped). All 7
  differences are misreads a check caught: quantity or price misread (R02 on KSS-2026-8202,
  MEL-2026-8003, KSS-CN-2026-4002), the USD invoice's lines not read (HAV-2026-6001, R02 and
  R03), the OCR bank digit (SAV-2026-1001 (2), R08), R01 and R06 on the unknown vendor
  (OST-2026-3004), and OCR dropping the last letter of live-demo scan MEL-2026-9003's GST
  number (R03, so it goes to NEEDS_REVIEW; the other 3 live-demo invoices pass clean).
- Intake commits in steps (`intake_in_steps`, CR-008): RECEIVED before the model runs, the
  outcome after. The Queue refreshes every 3 s and shows a "Processing…" card meanwhile. A
  failure removes the placeholder; a killed run is resumed on retry. Checked against real
  Postgres 2026-11-13.
- Replay works with no model: `LLM_MODE=replay make demo-data RESET=1` repeats the live run;
  `make e2e` passes the same way.
- Full stack verified 2026-11-13: containers reach host Ollama, the `sap_export` DAG writes the
  16-column CSV (19 rows), and the container review app runs `app/main.py` (it served a WS6
  placeholder before; `docker/review_app.py` is now unused).
- Demo page Read step shows the parser's rule live: visible characters in the text layer vs
  `scanned_page_min_chars` (25, characters not words; hidden text excluded; a rotated page goes
  to OCR) and highlights the branch taken. Parser and app share `parse.pdf.TextLayerCheck`.
- Invoice numbers (2026-11-16): OCR adds spaces around hyphens ("GSH- 2026-9004"; 5 of the 54
  in the replayed run). Three layers: the normalizer removes spaces around hyphens and slashes
  (`normalize.text.clean_reference`); R05, R10, and the export's vendor + reference check
  compare `invoice_number_key` (letters and digits only, uppercase); intake logs a
  `normalize.cleaned` event, and the Review page and Demo Step 4 show an amber "Changed
  automatically by the system" box ABOVE the values table (user asked 2026-11-16: system-made
  changes must come first and catch the reviewer's eye), with the changed row highlighted. Not a finding on purpose: the evaluator counts every finding as a check that fired.
- `uv run pytest`: 926 passed (2026-11-16).

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
make data                # rebuild: invoices/ (50, full run) + live-demo/ (4) + answer-key/, named by invoice number
make demo-data RESET=1   # rehearsal: the 50, then the 4, through the live model (~27 min), scored per folder
make demo-data RESET=1 STACK=1   # same, into the full stack's Postgres on 127.0.0.1:5434
make drop-all            # copy the 50 into data/inbox; times come from the manifest (git drops file times)
make drop-live           # copy the 4 live-demo invoices in, after the full run has finished
make intake              # trigger invoice_intake now instead of waiting up to 5 min
uv run python scripts/stage_benchmark.py          # stage the 10 benchmark invoices for bench_models.py
uv run python scripts/bench_models.py --docs data/benchmark --out data/bench --modes text,image --dpi 150 --limit 2
uv run python -m invoiceflow.export               # SAP CSV from the golden fixtures
uv run python -m invoiceflow.evaluate --gate      # evaluation + gate
```

Windows: `docs/windows-setup.md`. `data/generated/` and `data/llm_cache/` are tracked in git
(2026-11-16) so a clone can replay without the model; the rest of `data/` stays local, and
`.gitattributes` keeps those files byte-identical. Remote: private
`github.com/ZharlieSineFine/kallang-invoice-demo`.

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
   Live-demo scan MEL-2026-9003 stays as is (user decision 2026-11-13): it shows a check
   catching an OCR slip, a realistic case the audience should see handled.
2. Phase 2 gates per `docs/fanout/MERGE-RUNBOOK.md`: `make bench`/`eval-bench`, model-choice
   note, reviewers, rehearsal, snapshot/restore.
3. Wire the remaining make targets (`warm`, `bench`, `eval`, `eval-bench`, `gate`).
4. Demo gap: no in-app export button (export runs through Airflow).
5. Before loading with `STACK=1`, empty `data/inbox`: the stack's intake DAG picks up any
   file there while the load runs.
6. Intake order matters: the inbox is read oldest file first (file time, then name), so a
   re-send such as `SAV-2026-1001 (2).pdf` is checked after its original. `make drop-all`
   uses `cp -p` to keep the arrival times `make data` stamps; a plain copy would reset them.
