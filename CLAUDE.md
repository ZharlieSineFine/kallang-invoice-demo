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
- Dataset (two folders since 2026-11-17, user's choice): `make data` writes all 57 the demo
  database holds to `data/generated/invoices/` (the 50 of the full run, the 4 first shown live,
  the 3 over the limit), named by invoice number; `make live-set` writes the 6 for the live
  demo to `data/live-demo/`, never processed before the demo.
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
- Review page fix panel (2026-11-16, user chose "option (a)"): each finding card has a "Fix
  this field" button and the page opens on the first flagged field. The panel shows the value
  read on the invoice and has two actions: "Save correction" (the system misread it: store my
  value, rerun checks) and "Correct as printed" (records CONFIRM and clears that field's FLAG,
  reviewer recorded). `recheck.accepted_fields` keeps a confirmed field's FLAG cleared on later
  rechecks until the field is corrected; a HOLD is never cleared this way, only by "Release the
  hold" (shown only when ON_HOLD). Line values are `line_items[i].attr`; missing header values
  can be typed in; coding findings point to the Coding table, master-data findings say so.
  Code: `app/fix_panel.py`, `app/fields.py`.
- Export from the app (2026-11-17): Demo Step 7 and the Batches page have a "Run the SAP
  export" button (`app/export_action.py`, `PostgresBackend.run_export`), the same
  `export_approved` the Airflow DAG runs, so the CSV no longer needs `make up`. CSVs land in
  `data/gold/<batch_id>/` with a `.manifest.json`.
- Coding follows corrections (2026-11-17): after Save correction or a line edit, the backend
  reruns `coding.assign` on the corrected values (`app/coding_refresh.py`); a reviewer's own
  GL / cost center / tax code is kept, matched on source line numbers. Before this, coding
  kept intake's amounts and the export held MEL-2026-8003 back (net + tax != gross).
- SAP CSV first column is `InvoiceID` (1, 2, 3 per file; CR-010, user chose it 2026-11-17),
  not the internal UUID. The manifest's `invoices` list maps each number to its document;
  the CSV trace reads it, and falls back to the `DocKey` column of older batches.
- Times on screen are Singapore time (`app.formatting.format_time`, zone from
  `config/company.yaml`); the database stores UTC.
- Hidden text (2026-11-17): the Review page explains an R09 hidden-text hold under its card
  (`app/hidden_text.py`): the words, why they cannot be seen, where, and what the model was
  given; a red marker on the page image. Reasons come from `parse.hidden.hidden_reasons`, the
  function that sets the hidden flag. The OCR comparison (`parse/visibility.py`, CR-011)
  hides any text-layer word a person cannot see on the rendered page (covered, transparent,
  light gray, same color as the background); font limit raised to 3 pt. 9 planted samples in
  `data/hidden-text-samples/` (VTR-2026-9101..9109, git-ignored) are all caught;
  `tests/integration/ws2/test_no_false_hidden_text.py` shows no false alarms on the 54.
- Over the limit (user, 2026-11-17): 3 clean invoices of S$5,000+ (in `data/generated/invoices/`)
  (SAV-2026-9701 S$6,398.30, MEL-2026-9702 S$5,973.20, BLP-2026-9703 S$5,777.00), arriving after
  the 54, so the set is now 57 and the first 54 are byte-identical. Every check passes and the
  value limit sends each to NEEDS_REVIEW. Lines are all `qty x price`: a days column, and a
  "16 hr" line after two "1 lot" lines, made gemma misread (R02) in earlier versions.
  `make demo-add` loads generated files not stored yet without a reset (no report rewrite).
- Live demo (user's design, 2026-11-17): the database holds all 57 (`LLM_MODE=replay make
  demo-ready`). Six NEW invoices in `data/live-demo/` (`generator/live_set.py`, tracked in
  git, not in the 54's manifest) are never processed before the demo: CAM-2026-9601,
  PWS-2026-9602 (digital, pass), CWF-2026-9603 (scan, passes), VTR-2026-9604 (hidden text under
  a white box, R09 hold, only the OCR comparison sees it), KSS-2026-9605 (total off by 10, R02),
  PCE-2026-9606 (passes, and the audit seed picks it: the user's design, to show the audit live).
  Dry-run 2026-11-17 with the live model, nothing persisted: all six as planned. After the
  demo, `make erase-live` (`store/erase.py`) removes just them (rows, files, inbox copies, cache
  answers; a batch that included one is removed and its other invoices go back to ready) and
  keeps the 54. The audit log is append-only, so their history stays there. `make drop-live`
  copies the six into the inbox; `make intake-local` processes the inbox without Airflow.
- Upload page (2026-11-18): several files at once, each saved once per session (a rerun used to
  resave a file after it was read). Without `AIRFLOW_BASE_URL` the app reads the inbox itself:
  `app/local_intake.py` runs `python -m invoiceflow.pipeline.local_intake` as a child process
  (pdfium is not thread-safe, so no PDF work in the Streamlit process) and shows progress.
  The light setup has no Airflow at all.
- Airflow trigger (2026-11-18, user chose to show Airflow in the demo): `docker-compose.yaml`
  gives only the review app `AIRFLOW_BASE_URL=http://api-server:8080` (container address) and
  `AIRFLOW_UI_URL=http://127.0.0.1:8080` (browser links), so in the full stack only Airflow
  reads the inbox. `app/airflow.py` uses `/api/v2` (Airflow 3 answers `/api/v1` with "removed"),
  sends `logical_date: null` (required), and starts ONE `invoice_intake` run per upload
  (`conf.files` lists them). No login: `simple_auth_manager_all_admins` adds a token to every
  request. Links: `/dags/<id>` (the grid; Airflow 3 has no `/grid` page) and
  `/dags/<id>/runs/<run_id>`. Verified 2026-11-18 from a review-app container against the
  rebuilt image (run queued, conf shown, link opens it). The image bakes `src/` in, so code
  changes need a rebuild; `make up` passes `--build`.
- DAG schedules run in `company_timezone()` (`config/company.yaml`, 2026-11-18). Airflow reads
  a cron in the start date's zone; with a UTC start date `sap_export` ran at 02:00 SGT.
- Late exports skipped (user, 2026-11-18): with catchup off Airflow still starts the latest
  missed slot (`next_dagrun_info` takes the max of the previous cron time and the start date;
  `run_immediately` only covers a DAG's first run), so any `make up` after a missed 18:00
  exported every ready invoice. `sap_export` now skips a scheduled run starting more than 30
  min after its slot (`pipeline/schedule.missed_slot`); manual runs always run. Pass
  `dag_run.run_type` itself: inside a task its str() is "DagRunType.SCHEDULED" (that bug let
  a 16-hour-late run export on the first try). Verified 2026-11-19 on a fresh stack: the
  startup run for 2026-11-18 18:00 was skipped, with the reason in its log.
- Stage boxes (user, 2026-11-18): `invoice_intake` is `register_files → invoice[n]: parse →
  extract (pool llm, 2 retries) → check → summarize`; each mapped box is labeled with the file
  name (`map_index_template`) and logs one plain line (pages and text layer/OCR, model and
  time, findings and status). Steps in `pipeline/staged.py`; each stage saves its result in
  `data/work/<doc_id>/`, XCom carries IDs and the inbox path. Check reads prior invoices when
  it runs (all files are registered first); register catches a byte-identical copy within
  the run (else `receive_document` would "resume" it); summarize removes the placeholder of
  an invoice that failed after its retries (its file stays in the inbox). Parse and check
  run one at a time (`max_active_tis_per_dagrun=1`), so invoices are checked in arrival order
  (the scheduler orders ready boxes by priority, run, map index). The light setup still uses
  `intake_in_steps`; both give the same outcome (`test_staged_intake.py`). Verified
  2026-11-19 on the real scheduler in replay mode: clean + 1,080/1,090 + a copy -> AUTO_PASSED,
  NEEDS_REVIEW, copy discarded, source `upload`, inbox and `data/work` empty.
- Two compose projects (user, 2026-11-18): `docker-compose.yaml` is project
  `kallang-invoice-demo-stack`, `compose.dev.yaml` stays `kallang-invoice-demo`. Sharing the
  name made `make up` replace the dev container and `make down` remove it (happened once on
  2026-11-18; volume kept, 56 documents intact). They now run side by side (5433 and 5434).
  The old stack volumes `kallang-invoice-demo_airflow-logs` and
  `kallang-invoice-demo_postgres-db-volume` were unused; deleted at the user's request (2026-11-20).
- Light setup's database renamed (2026-11-20, user's request): compose.dev.yaml is project
  `kallang-invoice-light`, container `kallang-invoice-light-db`, volume
  `kallang-invoice-light_db-data` (data copied from `kallang-invoice-demo_postgres-dev-data`,
  since deleted with the ws6 volumes, 2026-11-20). Same port 5433 and `make db-dev` / `make down-dev`.
  `docs/fanout/*.md` still say `invoiceflow-postgres-dev`; they are the 2026-11-04 briefs.
- Audit monitor (user, 2026-11-19; CR-012 addendum): the `evaluate` DAG is now
  `dags/audit_monitor.py` (`audit_monitor`, Mondays 08:00 SGT and by hand). It writes
  `reports/monitor_<date>.json` (git-ignored) from `Repo.audit_counts` and
  `Repo.auto_passed_count`, marked `over_limit` above `audit.error_limit_percent` ("2",
  `config/rules.yaml`). `invoiceflow.evaluate.audit_monitor` holds `AuditSummary` (re-exported
  by `app.models`), the rule of three, and the wording Demo Step 8 also shows
  (`app.audit.monitor_lines` delegates). The Dashboard's accuracy still comes from the answer
  keys via `make demo-data`; the monitor is how accuracy is watched without answer keys.
- Rates (user's option A, 2026-11-19): `gst_rate` is stored as one plain number, "9" for
  9% (`gst_rate_percent`; R03, coding, and recheck compute with it), never "9.00": the
  parser and a reviewer's correction both go through `contracts.money.plain_decimal`. People
  only see "9%": Demo Step 4 (`app.formatting.display_value`), a correction's saved text and
  review log (typed "9.00" is saved as "9%"), and R03 evidence and messages
  (`rules.base.fmt_percent`). Migration `002_rate_evidence_percent` rewrote the old R03
  evidence ("9.00" -> "9%") in both databases. The user declined storing 0.09.
- Hot-patched containers (2026-11-19, during the user's live rehearsal): the stack image
  predates `invoiceflow/evaluate/audit_monitor.py` and the new `Repo` reads, so those two
  files were `docker cp`'d into the running review-app, dag-processor, and scheduler
  containers instead of a rebuild. Replaced by the rebuilt image the same day (`make up`,
  2026-11-19 15:54).
- DAG imports (2026-11-19): the three DAG files import only `airflow`, `pendulum`,
  `invoiceflow.settings` (and `pipeline.schedule` in `sap_export`) at the top; each task
  imports the pipeline when it runs. Airflow parses the file again at every task start with a
  30 s limit, and with the whole pipeline imported at the top the boxes hit "DagBag import
  timeout" and went to up_for_reschedule.
- Slow live rehearsal (2026-11-19, 11:14 to 11:48 SGT, six invoices, 33 minutes): Ollama's
  gemma4:12b plus the 7.7 GB Docker VM did not fit in the Mac's 16 GB. Task starts timed out
  from 11:18, nothing ran for about 19 minutes, the Docker VM logged 8 out-of-memory kills
  (11:31 to 11:36, so Airflow's containers restarted), and Docker Desktop restarted at 11:46.
  After the restart the last four invoices took about 2 minutes. A Docker restart leaves the
  dev Postgres stopped (exit 255): `docker-compose -f compose.dev.yaml up -d --wait`.
- Light theme (2026-11-19): `.streamlit/config.toml` sets `[theme] base = "light"`. Without
  it Streamlit follows the browser or macOS appearance, and this Mac is in dark mode. The
  image installs Streamlit 1.67.0 (pip, not `uv.lock`), the host venv has 1.66.1; their
  default primary colors differ (#C53948 and #FF4B4B), both red. The Next button has been
  `type="primary"` since 2740f7b.
- The six live-demo copies from the user's Upload test (2026-11-18) were moved from
  `data/inbox` to `data/inbox-hold/` (2026-11-19) so the scheduler could not read them; they
  are copies of `data/live-demo/`.
- Value limit and random audit (CR-012, user chose 10% and S$5,000, 2026-11-17): a clean
  invoice at or above `routing.auto_pass_limit_sgd` goes to a person. No demo invoice reaches
  S$5,000, so the 54 keep 31 auto-passed (the user wants 31 shown, 2 of them audited). Intake picks 10% of
  auto-passed invoices (`rules/audit.py`, seed `kallang-demo-10` in `config/rules.yaml`,
  chosen so only PCE-2026-9606 of the live set is picked); a picked one stays AUTO_PASSED,
  exports as usual, and carries "Random audit sample" (`app/audit.py`: inbox card, Queue
  column, Review label and audit buttons, Demo Step 8 "Monitoring auto-passed invoices").
  Changing the seed or the live set means rechecking `test_the_audit_seed_picks_only_the_sixth`.
- Discarded duplicates: Demo Step 1 and the Queue page list a byte-identical copy under
  Discarded, with its proof (`app/duplicates.py`): the copy's name, time and SHA-256 (from the `intake.duplicate_file` event) beside the kept
  original's, a link to it in Review, a download, and the `shasum` / `certutil` commands.
  The user declined an in-app drop-a-file checker (2026-11-17).
- Lag fixes (user approved 2026-11-19): no triggerer service (`make up` has
  `--remove-orphans`), `AIRFLOW__CORE__DAGBAG_IMPORT_TIMEOUT` 120 and the DAG processor's
  limit 180, and `LLM_MODE: ${LLM_MODE:-live}` in the compose env, so `LLM_MODE=replay make
  up` rehearses without the model. `make erase-live` takes `STACK=1` (the stack's database,
  via `store.connection.use_stack_database`, shared with `demo-data STACK=1`) and
  `KEEP_ANSWERS=1` (keeps `data/llm_cache` entries). Replay rehearsal of the six: 15.4 s,
  same outcomes as the live run (4 AUTO_PASSED, 1 NEEDS_REVIEW, 1 ON_HOLD). Steps in
  `docs/demo-plan.md` ("Rehearsal and demo day with Airflow"). The six's recorded answers in
  `data/llm_cache` are untracked: do not commit them; `make erase-live STACK=1` deletes them
  before the demo. The stack was left in live mode with the six erased (2026-11-19).
- Main buttons are blue (`primaryColor = "#1565c0"` in `.streamlit/config.toml`, user's
  choice 2026-11-19), not Streamlit's red.
- Queue delete (user's design, 2026-11-20): every finished document has Select and Delete
  (on its card, or its row under Discarded), and bars above and below the cards delete the
  ticked ones (`app/queue_delete.py`). An `st.dialog` asks first; it opens from `render`,
  outside the 3 s refreshing fragment, or a refresh closes it. An EXPORTED invoice can be
  deleted after a warning that SAP keeps it (user chose a warning over blocking). Backend
  `delete_documents` -> `invoiceflow.store.delete`: rows, stored file, parsed/silver files and
  recorded answer go; one `document.deleted` event each; unlike erase-live, the SAP batch,
  its CSV and its other invoices stay (only the deleted invoice's `export_rows` row goes).
  `PostgresBackend(files_root=, cache_dir=)` lets tests delete from scratch folders.
- Discarded list (`app/discarded.py`) on the Queue and Demo step 1: byte-identical copies
  and NOT_INVOICE documents, which no longer appear in the cards, table, status filter or
  counts. Every page counts from `app/counts.py` (user's report, 2026-11-20: the strip said
  "1 discarded" while the Queue listed 3): received = stored documents + copies; discarded =
  copies + non-invoices; invoices = the rest. The flow strip's Intake box, Demo step 1's
  sentence, the Queue's and Dashboard's "Invoices" metric (`DashboardData.total_invoices`,
  SQL excludes NOT_INVOICE) all agree. `render_flow_strip(..., copies=n)` takes the copies.
- Action results (user's design, 2026-11-20): every button passes an `Act` (what was done,
  to which invoice, by whom) to `ui.run_action`; `app/notice.py` turns the result into a
  `Notice`, `app/notice_view.py` draws it as a colored card under the buttons
  (`ui.show_result(place)`, stays until the next action) and an HTML pop-up at the top right
  (fades after about 7 s, errors 14 s; `pointer-events:none`). It names the invoice, vendor
  and total, says what happens next, records reviewer and time, and tags the new status.
  Color means "it worked" (the user's choice): green worked, even a reject; amber worked but
  a check is still open (or an exported invoice was deleted); red not done; blue nothing
  changed. `ReviewOutcome.checks` (what the rerun found) and `.changed` feed it. Review
  places: fix, decision, release, lines, coding, audit; also export and the Queue's top bar.
- Cards name the value limit (2026-11-20): an invoice sent to a person only by its size (no
  open rule) shows "Needs review · S$5,000 or more", read back from the router's reason
  (`rules.router.limit_in_reason`; `app.inbox._reasons`).
- Review-time recheck (`app/recheck.py`) also recomputes each line's quantity x unit price
  (x days) and the GST amount against `gst_rate` (2026-11-20; user's report on
  KSS-2026-8202, where the model read quantity 720 for the printed 120, three corrections
  followed the flags, and the rerun said "nothing open" with GST still 9% of the old
  subtotal). Intake's R02 line and R03 GST-arithmetic findings are recomputed, not carried
  (`_is_recomputed`). The stack's KSS-2026-8202 was reset on 2026-11-23 (deleted with its
  recorded answer kept, then `LLM_MODE=replay ... demo_data.py --add-new --stack`): no
  reviews, and its R02 flag now carries the line hint. Its event log still lists the old
  corrections and a `document.deleted` event (events are append-only).
- Line flag says where to look (user approved 2026-11-20): `invoiceflow/rules/line_hint.py`,
  shared by R02 and the recheck, shows the arithmetic ("(720 × 19.00)") and, when the
  printed amounts, subtotal, GST and total agree with each other, adds "check this line's
  quantity and unit price on the page first". Write "×" as `\u00d7` in source (ruff RUF001).
  Stored findings keep the text they were written with; only new intakes and reruns get it.
- Discarded copies: the shasum/certutil commands sit behind a switch, off by default.
- Re-export (user's request, 2026-11-20: "do not block future export attempts"; CR-013):
  migration `003_export_history` drops `export_rows` UNIQUE (doc_id), so each send is its own
  row and the history keeps every one. `export_approved(resend=(doc_id, ...))` adds invoices
  sent before (`Repo.previously_exported`) to the run; their status stays EXPORTED and
  `ExportSummary.resent` names them. A run without `resend` (the scheduled `sap_export` DAG)
  still sends only invoices never sent, so nothing goes twice on its own. Demo Step 7 and
  Batches show "Send again (N sent before)" under the export button (`app/export_action.py`,
  a multiselect from `queries.export_history`); the button counts both ("3 ready + 2 sent
  again") and the confirmation names the ones sent again. Delete lists every batch the
  invoice went out in; erase-live sends an invoice back to APPROVED or AUTO_PASSED only when
  no other batch still holds it.
- Readable scans on Review (user's report, 2026-11-20: "very blur"): the stored pages are
  150 DPI and readable at 2x; Review showed them at about half size. `app/page_viewer.py`
  enlarges the field zoom 2.5x (capped at 1,800 px) with a contrast boost, and "View page
  large" opens the whole page in an `st.dialog` with a 100-300% size slider. Display only:
  the stored image the model and checks read is never changed.
- The stack's images copy `src/invoiceflow` at build time (`pip install /tmp/invoiceflow`),
  but `app/` is mounted. A change under `src/invoiceflow` needs `make up` (rebuild, 1-2
  minutes) or the review app fails to import it (2026-11-20: `invoiceflow.rules.line_hint`
  crashed the stack app until the rebuild); a change only under `app/` needs just
  `docker restart kallang-invoice-demo-stack-review-app-1`. Migrations run from the mounted
  repo: `docker exec kallang-invoice-demo-stack-airflow-scheduler-1 python -m
  invoiceflow.store.migrate`.
- `uv run pytest -m "not ollama"`: 1274 passed, 3 deselected (2026-11-23), about 3 minutes.
  The 4 ruff errors in `scripts/demo_boxes.py` (2026-11-04) are not fixed.

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
make up              # full Airflow stack (8080) + review app (8501; stop a host Streamlit first); make down to stop
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
4. Before loading with `STACK=1`, empty `data/inbox`: the stack's intake DAG picks up any
   file there while the load runs.
5. Intake order matters: the inbox is read oldest file first (file time, then name), so a
   re-send such as `SAV-2026-1001 (2).pdf` is checked after its original. `make drop-all`
   uses `cp -p` to keep the arrival times `make data` stamps; a plain copy would reset them.
