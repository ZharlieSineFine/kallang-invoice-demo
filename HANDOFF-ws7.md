# HANDOFF — WS7: Review app and dashboard

**Branch:** `ws7-app` (based on tag `contracts-v1`)
**Owned paths:** `app/`, `tests/unit/app/`, `tests/integration/ws7/`
**Commit:** `ws7-app` HEAD (see `git log --oneline -1`; the bundle below has the same commit)
**Acceptance:** `make test` passes (191 tests); 92% statement coverage on `app/` when measured
with `--cov=app`; the three WS7 done-when items are verified below.

## Commit / sandbox note

The normal git commit path was blocked because this worktree's shared index lives at
`~/Projects/kallang-invoice-demo/.git/worktrees/kallang-ws7-app`, outside the workspace
sandbox. The commit was created with a worktree-local git directory (`.git-ws7-local`, which
uses the shared object database as an alternate), so `git log` in this worktree shows the WS7
commit on `ws7-app`. The same commit is also in `ws7-app.bundle` at the repo root. To put
it on the branch visible from the main worktree:

```bash
git -C ~/Projects/kallang-invoice-demo fetch \
  ~/Projects/kallang-ws7-app/ws7-app.bundle ws7-app:ws7-app
```

The original worktree link was
`gitdir: /Users/huskydawg/Projects/kallang-invoice-demo/.git/worktrees/kallang-ws7-app`;
restore that file to go back to the shared worktree metadata. The main worktree itself was
not modified.


## What is done

Six Streamlit pages, one module each under `app/pages/`:

| Page | What it does |
|---|---|
| **Upload** | Saves the bytes to `data/inbox/` under a content-addressed name, then triggers `invoice_intake` over the Airflow REST API. If Airflow is not configured or the request fails, the saved file stays in the inbox and the page shows the Airflow grid link. |
| **Queue** | Lists every document with status, value, finding count, worst severity, replay flag, and a button that opens the document in Review. |
| **Review** | Page image with green/amber/red boxes, field picker that highlights a box and shows a zoom crop, replay badge, findings, confirm/correct/approve/reject/release-hold actions, editable line-item table, editable coding panel (GL account / cost center / tax code, with the rule that set them), and review history. |
| **Trace** | Extraction metadata, run list, findings from every run, review actions, and the append-only event stream. |
| **Dashboard** | Documents processed, auto-pass rate, findings by check, seconds per invoice, corrections by field and vendor, holds/status, and the latest evaluation with a `SYNTHETIC EVALUATION` badge. |
| **Batches** | Export batches, exported-invoice count, approved-but-not-exported count, and the documents in each batch. |

Supporting modules:

- `app/queries.py` — every database read; SQL only SELECTs.
- `app/repo.py` — **temporary** write adapter for the WS6 `store.repo` that does not exist at
  `contracts-v1`. It keeps field/line/coding history (`is_current` moves, new row inserted).
- `app/backend.py` — `Backend` protocol plus `PostgresBackend`; the only class that composes
  reads/writes. A future `store.repo` swaps into this file, not into the pages.
- `app/recheck.py` — **temporary** stand-in for the missing `pipeline.recheck` (CR-001). It
  recomputes R02 (lines vs subtotal) and R03 (subtotal + GST vs total) from current values and
  applies the configured severities/routing. WS5 still owns the full R01–R12 set.
- `app/boxes.py` — page-fraction geometry, word lookup (exact + fuzzy), three-color overlay,
  zoom crop. No mutation of the page or bundle.
- `app/upload.py`, `app/airflow.py` — inbox save, safe filenames, REST trigger, link fallback.
- `app/evaluation.py` — tolerant latest-report loader; marks synthetic unless the report says
  `live` (CR-002).
- `app/formatting.py`, `app/models.py`, `app/ui.py` — pure parsing/formatting, frozen view
  models, and shared Streamlit helpers.

## How to run

```bash
# from ~/Projects/kallang-ws7-app
export UV_CACHE_DIR=/tmp/uv-cache-ws7      # if the shared uv cache is not writable
uv sync --all-extras

make db-dev && make fixtures               # Postgres on 127.0.0.1:5433 + golden documents
uv run streamlit run app/main.py           # http://localhost:8501
```

Airflow is optional. To let Upload start the DAG, export:

```bash
AIRFLOW_BASE_URL=http://127.0.0.1:8080
AIRFLOW_DAG_ID=invoice_intake
# optional: AIRFLOW_USERNAME / AIRFLOW_PASSWORD, or AIRFLOW_AUTH_TOKEN
```

Without `AIRFLOW_BASE_URL`, Upload still saves the file and shows the grid link. These names
are a contract request (CR-003) because `.env.example` does not define them yet.

Tests:

```bash
make test                                            # full suite, 80% coverage gate
uv run pytest tests/unit/app tests/integration/ws7 \
  --cov=app --cov-report=term-missing                # WS7 paths, 91% coverage
```

Database integration tests skip automatically if Postgres is not reachable.

## Done-when verification

1. **Correct, recheck, approve on the fixture DB.**
   Verified against the real dev database (then `load_fixtures` restored it):

   ```
   before:          NEEDS_REVIEW  [R02 on subtotal]
   correct subtotal to 1,080.00:
                    R02 gone; R03 appears because the printed total 1,188.10 still equals
                    1,090.00 + 98.10
   approve:         APPROVED
   ```

   `tests/integration/ws7/test_review_flow.py` asserts the same flow inside a rolled-back
   transaction, including the history rows (`MODEL` 1,090.00 → `REVIEWER` 1,080.00), the
   `CORRECT`/`APPROVE` reviews, and the recheck event. Correcting the subtotal alone exposes
   R03 because the fixture's GST and total follow the wrong 1,090 subtotal; correcting those
   two fields too (or editing the line items to add up to 1,090.00) produces a clean
   `AUTO_PASSED`. This is expected arithmetic, not a bug.

2. **Boxes line up on three sample pages.**
   `tests/unit/app/test_boxes.py::test_page_boxes_align_on_three_sample_pages` checks the two
   golden PDF pages and a synthetic third page. For every box it asserts the stored word
   text inside the box is non-empty; for the golden pages the subtotal box text is exactly
   1,080.00 / 1,090.00. `tests/integration/ws7/test_review_flow.py` repeats the check against
   the boxes and words actually stored in Postgres.

3. **Streamlit AppTest covers the main flows.**
   `tests/unit/app/test_pages.py` (18 tests) drives all six pages: upload save + fallback,
   queue → review navigation, replay badge, R02 visible, field selection + zoom, correction
   clears R02, approve, reject, confirm, release-hold comment requirement, editable line
   items, editable coding, trace, dashboard synthetic badge, batches, empty states, and the
   sidebar navigation.

## Temporary code / what is left

- **`app/repo.py` is temporary.** When WS6 lands `store.repo` and its `Repository`, replace
  the calls in `app/backend.py`. The schema history rules are already implemented here.
- **`app/recheck.py` is temporary.** It exists only because `pipeline.recheck` is absent at
  `contracts-v1` (CR-001). It handles R02/R03; the real implementation should run the WS5
  rules against the current stored values. The adapter is isolated so this is one swap.
- **Evaluation format is a guess** (CR-002). The dashboard accepts `latest.json` /
  `evaluation.json` / `eval-*.json` and displays the raw payload, but a stable WS8 schema is
  still needed.
- **Airflow settings are not in `.env.example`** (CR-003). The app reads the proposed names
  and falls back to a link.
- No call to Ollama was made. All test data is synthetic/golden.

## Notes for the integrator

- `docs/contract-requests.md` has CR-001, CR-002, and CR-003, all `OPEN`.
- Nothing outside `app/`, the two WS7 test directories, `docs/contract-requests.md`, and this
  handoff was changed.
- The pages read the real `Repository`-shaped data via SQL; when `store.repo` exists, only
  `app/backend.py` and `app/repo.py` need to change.
