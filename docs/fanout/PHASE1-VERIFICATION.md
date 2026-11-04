# Phase 1 manual verification — step-by-step runbook

Run everything from your own terminal (no sandbox involved), in this order. Each step says
what to run, what to expect, and where the result appears. Expected outputs were captured
on this Mac on 2026-11-04 with gemma4:12b live.

Working directory throughout: `cd ~/Projects/kallang-invoice-demo`

---

## Part 0 — Prerequisites (one-time checks)

```bash
cd ~/Projects/kallang-invoice-demo
uv --version                       # uv 0.11.x
docker info | head -3              # "Server Version" — Docker Desktop must be running
docker-compose --version           # standalone binary (the Makefile uses it)
curl -fsS http://127.0.0.1:11434/api/tags | python3 -m json.tool | grep '"name"'
                                   # expect "gemma4:12b" (7.7 GB)
tesseract --version | head -1      # tesseract 5.5.4
```

If `docker-compose` is missing, run `make` targets with `COMPOSE="docker compose"` instead.

## Part 1 — Setup, repo state, and the two main gates

```bash
make setup          # uv sync + creates .env (and AIRFLOW_UID)
make doctor         # docker / memory / ollama / ports — all "ok"
git log --oneline -12
```

`git log` should show one merge commit per workstream (ws6-platform first, then ws2, ws4,
ws5, ws3, ws1, ws7, ws8) plus the integration commits (`267b959` stub swap, the
`.gitignore`/test-rename fixes).

```bash
make test           # ~5-7 min (includes live Ollama tests + db tests if Postgres is up)
                    # expect: 729 passed, ~96% coverage, gate 80% met
make skeleton       # ~2-4 min live (calls gemma4:12b twice)
```

`skeleton` output must be exactly:

```
fixture                    invoice         status        expected      findings
golden-a-clean             SAV-2026-0412   AUTO_PASSED   AUTO_PASSED   none
golden-a-total-mismatch    SAV-2026-0413   NEEDS_REVIEW  NEEDS_REVIEW  R02 on subtotal
skeleton OK
```

(Despite its help text, `skeleton` now runs the REAL stages, not stubs.) Re-run with
`LLM_MODE=replay make skeleton` later and it works with Ollama stopped, served from
`data/llm_cache/` — the live run above records the cache as it goes.

## Part 2 — WS1: the synthetic dataset

```bash
# WeasyPrint needs Homebrew Pango on macOS:
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run python generator/build.py --seed 42
ls data/generated/            # 50 documents: 36 "pre", 4 "live", 10 "benchmark"
                              # each folder: the file + truth.json (+ manifest)
```

Byte-identical reproducibility check:

```bash
mv data/generated /tmp/gen1
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run python generator/build.py --seed 42
diff -r /tmp/gen1 data/generated && echo "IDENTICAL"    # expect IDENTICAL, no diff lines
```

Look at samples: `open data/generated/.../*.pdf` (a type A), a type C scan (JPG + image PDF
with no text layer), and `cat` one `truth.json`. The live set contains the 1,080/1,090
invoice, the bank-account-swap, and the hidden-instructions invoice.

Tests: `uv run pytest tests/unit/generator tests/integration/ws1 -q` — all pass.

Note: the `make data` target is not wired yet (prints a message); the direct command above
is the WS1 CLI.

## Part 3 — WS2: reading documents (parse + OCR)

```bash
uv run pytest tests/unit/parse tests/integration/ws2 -q    # all pass (94 collected there)
```

Manual look — parse a golden PDF and show words/hidden words:

```bash
uv run python scripts/demo_parse.py
```

Expect: 1 page, 119 words, 0 hidden, `source=PDF_TEXT`, and the first prompt lines
(Stagecraft AV Rentals … TAX INVOICE …).

Then OCR a WS1 scan (from Part 2) — type C documents live one folder each under
`data/generated/docs/` as `<id>/<id>.pdf` and `<id>/<id>.jpg`:

```bash
uv run python scripts/demo_parse.py "data/generated/docs/pre-c-01/pre-c-01.pdf"
```

Expect `source=OCR`, `ocr_mean_conf` around 82–92 (e.g. 85.11), and no hidden words.
Other type C docs: `ls data/generated/docs | grep '^pre-c'` (and `bench-c-*`).

## Part 4 — WS4: standardizing and locating values

```bash
uv run pytest tests/unit/normalize tests/unit/locate tests/integration/ws4 -q   # all pass
```

Manual look:

```bash
uv run python scripts/demo_locate.py
```

Expect:

```
S$1,090.00      -> 1090.00
12 Oct 2026 (SG)-> 2026-10-12
M2-1234567-8    -> M212345678
...
  subtotal         EXACT  score=100.0 page=1 matched_text='1,080.00'
  total            EXACT  score=100.0 page=1 matched_text='1,177.20'
```

All four shown fields should be `EXACT` matches.

## Part 5 — WS5: checks R01–R12 and routing

```bash
uv run pytest tests/unit/rules tests/integration/ws5 -q     # all pass
```

The rules' real behavior is visible in `make skeleton` (Part 1): the twin produces exactly
`R02 on subtotal` with the expected evidence, and the clean invoice produces nothing. To see
the evidence object, run the integration test verbosely:

```bash
uv run pytest tests/integration/ws5 -q -s | grep -A2 R02
```

## Part 6 — WS3: model extraction

```bash
uv run pytest tests/unit/extract -q            # replay/schema tests, no model needed
uv run pytest tests/unit/extract -m ollama -q  # live gemma4:12b: golden extraction == truth
```

Benchmark (the bench script expects one folder per document with `invoice.pdf` inside, so
first stage the 10 `bench-*` documents from WS1's output):

```bash
mkdir -p data/benchmark && for d in data/generated/docs/bench-*; do mkdir -p "data/benchmark/$(basename "$d")" && cp "$d/$(basename "$d").pdf" "data/benchmark/$(basename "$d")/invoice.pdf"; done
```

Then run it (one line; `--limit 2` runs 4 model calls, ~3-5 min):

```bash
uv run python scripts/bench_models.py --docs data/benchmark --out data/bench --modes text,image --dpi 150 --limit 2
```

Expect: `benchmark: 4 calls, 4 succeeded`, then `latency csv`, `memory`, `raw outputs` lines.
(The script also prints "fallback model 'qwen3-vl:4b' is not pulled; skipping" — that is
correct: we run gemma4:12b only.)

```bash
ls data/bench/                          # latency.csv, memory.json, raw/ outputs
```

Replay proof: `LLM_MODE=replay make skeleton` → same table as Part 1, no model calls
(watch `ollama ps` — no load event).

## Part 7 — WS8: SAP coding, export, evaluation

```bash
uv run pytest tests/unit/coding tests/unit/export tests/unit/evaluate tests/integration/ws8 -q

uv run python -m invoiceflow.export     # golden fixtures -> CSV
# expect: wrote data/export/... (2 row(s)) + a manifest
find data/export -name '*.csv' -exec cat {} \;    # header + 2 rows, GL 610200/KG1100/TX

uv run python -m invoiceflow.evaluate   # golden truth vs itself
# expect: accuracy 100.00%; writes reports/eval_<time>.json, .md, and reports/latest.json
uv run python -m invoiceflow.evaluate --gate    # "gate OK: 100.00% vs baseline ..."
```

Note: the `make eval` / `make gate` / `make export`(CSV) targets are not wired to these
CLIs yet; the direct commands above are the real WS8 entry points.

## Part 8 — WS6 (1/2): dev database

```bash
make db-dev          # Postgres 16 on 127.0.0.1:5433, migrations applied
make fixtures        # loads the two golden documents through the REAL pipeline
```

Expect the fixtures table:

```
2 document(s): 42 fields, 8 line items, 2 coding lines, 1 finding(s)
  golden-a-clean           AUTO_PASSED    SAV-2026-0412   findings: none
  golden-a-total-mismatch  NEEDS_REVIEW   SAV-2026-0413   findings: R02
```

Look inside the database:

```bash
docker-compose -f compose.dev.yaml exec -T postgres psql -U ap -d ap -c \
  "SELECT status, count(*) FROM documents GROUP BY 1;"
docker-compose -f compose.dev.yaml exec -T postgres psql -U ap -d ap -c \
  "SELECT rule_id, field, evidence FROM findings;"
```

## Part 9 — WS7: the review app (manual UI flow)

With the dev DB up (Part 8):

```bash
uv run streamlit run app/main.py        # open http://localhost:8501
```

In the UI: **Queue → Review** the `golden-a-total-mismatch` invoice:

1. See the page image with boxes; the subtotal box is red (flagged by R02).
2. Correct subtotal `1,090.00 → 1,080.00`, GST `98.10 → 97.20`, total `1,188.10 → 1,177.20`
   (correcting the subtotal alone re-triggers R03, as the fixtures keep GST/total
   consistent with the printed subtotal — this is noted in HANDOFF-ws7.md).
3. Checks rerun: R02 clears. Approve.
4. Confirm in SQL:

```bash
docker-compose -f compose.dev.yaml exec -T postgres psql -U ap -d ap -c \
  "SELECT status FROM documents WHERE doc_id = (SELECT doc_id FROM fields \
   WHERE name='invoice_number' AND value_raw='SAV-2026-0413');"
# expect APPROVED
```

AppTest coverage: `uv run pytest tests/unit/app tests/integration/ws7 -q` (191 collected).

## Part 10 — WS6 (2/2): the full stack and the two DAGs

```bash
make doctor          # all green, ports 8080/8501 free
make up              # builds the images (~2-5 min first time), waits healthy
make check-dags      # DAG import test: no errors
```

Open http://127.0.0.1:8080 (Airflow UI — no login) and http://127.0.0.1:8501 (review app
inside the container).

Intake DAG:

```bash
make drop N=golden-a-clean       # copies the PDF into data/inbox/
# in the Airflow UI: trigger invoice_intake (or wait <= 5 min for the schedule)
# Grid view: register -> parse -> extract -> check -> summarize, then the doc sits in silver
docker-compose -f docker-compose.yaml exec -T postgres psql -U ap -d ap -c \
  "SELECT status, count(*) FROM documents GROUP BY 1;"
```

Export DAG:

```bash
make export                      # triggers sap_export
# Batch page shows the batch; the CSV lands under data/ (find data -name '*.csv')
make export                      # again: second batch has 0 rows (export-once)
make down                        # stop the stack when done
```

## Part 11 — Automated end-to-end (replay mode)

```bash
make db-dev && make fixtures     # if not already up
make e2e
```

Expect:

```
intake : golden-a-clean -> AUTO_PASSED
export : batch export-... rows=1
export : batch export-... rows=0
e2e OK: inbox -> silver, export twice leaves the second batch empty
```

(`make e2e` runs in replay mode against a transaction that always rolls back, so it never
changes what the review app sees. If it reports `CacheMiss`, run `LLM_MODE=live make
skeleton` once to record the golden fixtures into `data/llm_cache/`.)

---

## Troubleshooting

- **Ports 8080/8501 busy**: `lsof -nP -iTCP:8080 -iTCP:8501 -sTCP:LISTEN` and stop the
  owner, or `make down` any leftover stack.
- **`docker-compose` missing**: prefix make targets with `COMPOSE="docker compose"`.
- **Model slow**: `make skeleton` takes ~50–90 s per invoice on gemma4:12b — that is the
  expected speed, not a hang.
- **`make data` / `make bench` / `make eval` / `make gate` / `make warm` / `make demo-data`
  print a message and exit**: those Makefile targets are deliberately unwired until Phase 2
  prep; use the direct CLI commands given above.

## Sign-off checklist

- [ ] `make test` — 729 passed
- [ ] `make skeleton` — both fixtures route as the table shows
- [ ] `make e2e` — `e2e OK`
- [ ] WS1: 50 docs, byte-identical rebuild
- [ ] WS2: golden parse + one OCR scan read
- [ ] WS4: `S$1,090.00 → 1090.00`, EXACT locations
- [ ] WS5: R02 on the twin, nothing on the clean invoice
- [ ] WS3: live extraction == truth; replay works with Ollama stopped
- [ ] WS8: CSV has 2 rows; evaluate scores 100%; gate OK
- [ ] WS6: stack healthy, intake DAG runs, export twice → 0 rows
- [ ] WS7: corrected total clears R02, approve → APPROVED
