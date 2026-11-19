# Visual demo plan: showing the pipeline to technical and non-technical audiences

**Decided 2026-11-04.** Phase 1 works and is verified from the terminal, but the demo must be
*watched*, not typed. This plan turns the verified pipeline into a guided, visual 10-minute
story with an evidence panel at every step, using screens the audience can read without
knowing what a terminal is.

Everything below builds on what already exists: the WS7 Streamlit app (Upload, Queue,
Review, Trace, Dashboard, Batches), per-field boxes in Postgres, findings with evidence,
the Airflow grid view, WS1's 54-document synthetic set, and the export CSV + manifest.

---

## 1. Audience and the one ground rule

| Audience | What they need to see | How we show it |
|---|---|---|
| Finance / non-technical | "Did the system read it right? What did it flag? Who fixed it? Is it safe to pay?" | Plain-language captions, big green/amber/red boxes on the invoice image, before/after values, a single sentence per step |
| Technical (Bill, PTC reviewers) | "Which rule fired, on what evidence, with which model/prompt/rule versions, and where exactly on the page" | A "technical view" toggle on the same screens: JSON extraction, finding objects, rule IDs + versions, token/latency stats, the SQL lineage |

**Ground rule — one screen, one question.** Every demo screen answers exactly one question
in one sentence at the top, and every number on screen comes from the database or the
evaluation report (build plan §8). No slide decks; the live app is the deck.

## 2. What we add (deltas on top of Phase 1)

1. **`app/pages/story.py` — the "Demo" page.** A scripted, linear flow with Back/Next that
   walks the audience through the exact story below. Each step renders a stage card
   (title + one-sentence outcome) plus an **evidence panel**: the real output artifact of
   that step for the invoice currently being discussed.
2. **Pipeline flow strip.** A horizontal strip (Intake → Read → Extract → Check → Review →
   Export) shown on every step, with the current stage highlighted and each stage colored
   by the batch's actual outcomes (green passed / amber flagged / red held). Reused by the
   Queue and Dashboard pages.
3. **Technical toggle** (one switch in the sidebar): reveals raw artifacts — extraction
   JSON, findings, rule versions, model digest, prompt version, SQL — next to the friendly
   views.
4. **Inbox batch view.** A thumbnail grid of the 50 documents in the recorded full run
   (`data/generated/invoices/`, each file named by its invoice number): page-1 image,
   type badge (A/B/C, credit note, statement), vendor, amount, and outcome color once
   processed. Clicking a card jumps to that document's review/trace.
   *Optional flourish (stretch):* WS1 renders a display-only `batch-overview.pdf`
   (50 documents, mixed types, multi-page) purely as a visual "here is the pile of invoices
   we received" artifact. The pipeline still processes one file per invoice — multi-invoice
   splitting is explicitly out of scope (build plan §13) — and the overview PDF is shown,
   not ingested.
5. **Compliance cards.** Each check step shows the requirement it enforces, e.g.
   R03 → "IRAS: GST 9% from 2024-01-01; simplified invoices only up to S$1,000"; R08 →
   "SPF advisory, May 2026: bank-detail-change scams". This answers "why does this step
   exist" for both audiences.
6. **CSV trace drill-down.** On the export screen, clicking a CSV row highlights the source
   invoice, its page, and the exact box the value came from, plus the model/prompt/rule
   versions used. (The data exists: `export_rows`, `fields.bbox`, `extractions`,
   `findings.rule_version`.)

No new services: all six items are additions to the existing Streamlit app, reading the
existing `ap` database and `data/` artifacts.

## 3. The storyboard (what each step shows, and its proof artifact)

### Step 0 — The inbox (Question: "what arrived?")
- Screen: batch grid of the 50 full-run documents (39 digital PDFs, 11 image-only scans,
  anomalies included) with type badges and amounts.
- Proof artifact: the files themselves in `data/`; every card links to its page-1 image.

### Step 1 — Read (Question: "can the system even read these?")
- Screen: one invoice; the page image with **all detected words boxed**; digital PDFs show
  the text layer, type C shows OCR words + confidence (82–92%).
- Proof artifact: words + boxes from `pages`/`PageText`; hidden-text demo (see Step 4) shows
  the white text the audience cannot see but the system found.

### Step 2 — Extract (Question: "what did the AI copy?")
- Screen: page image on the left, the extracted JSON on the right, one field at a time as
  the story advances; values appear **exactly as printed** (S$1,177.20, 15/10/2026).
- Proof artifact: `extractions.raw_output` + parsed JSON; technical toggle shows model
  `gemma4:12b`, digest, prompt version, tokens, seconds.

### Step 3 — Understand (Question: "how does the system turn printing into numbers?")
- Screen: printed-vs-normalized table (S$1,090.00 → 1090.00; 15/10/2026 → 2026-10-15;
  M2-1234567-8 → M212345678) and the located value boxes colored by match quality.
- Proof artifact: `fields.value_raw` / `value_norm`, `fields.bbox`, match type + score.

### Step 4 — Check (Question: "what did the system catch?")
- Screen: the slide-3 twin — lines sum to 1,080.00 but the printed total is 1,090.00; both
  numbers boxed red/amber on the page; the R02 card with evidence
  `{"lines_sum": "1080.00", "subtotal": "1090.00"}`; a compliance card citing IRAS/GST math.
- Then two holds: bank account ≠ vendor master (R08, SPF advisory card) and the hidden
  white-text instruction (R09: text the audience can't see, boxed where it sits).
- Proof artifact: `findings` rows (rule_id, severity, evidence, rule_version), confidences
  per field.

### Step 5 — Review (Question: "who is in control?")
- Screen: a person corrects 1,090.00 → 1,080.00 (and the GST/total that follow it); checks
  rerun live and R02 clears; the reviewer approves.
- Proof artifact: `reviews` rows (reviewer, action, old → new, source = reviewer), the
  cleared findings, status APPROVED.

### Step 6 — Export (Question: "what does SAP receive?")
- Screen: the hypothetical SAP CSV, one row per coding line (GL 610200, cost center KG1100,
  tax TX), with the row → page-box trace drill-down; second run exports nothing (export-once).
- Proof artifact: the CSV + manifest (`export_batches`, sha256, row count), the
  "hypothetical layout" label.

### Step 7 — Accuracy (Question: "how good is it, honestly?")
- Screen: the evaluation dashboard, **labeled synthetic**: accuracy, per-rule precision/
  recall, seconds per invoice, corrections by field/vendor.
- Proof artifact: `reports/latest.json` (CR-003) written by WS8's evaluator.

## 4. The 10-minute script (reuses build plan §2)

| # | Screen | Time |
|---|---|---|
| 1 | Recorded: drop the 50 into the inbox → Airflow takes them oldest first (sped up, labeled) → dashboard colored by outcome | 1:00 |
| 2 | Live: drop the 4 from `live-demo/` → two digital PDFs read from the text layer (pdfplumber), two scans read by Tesseract OCR → all AUTO_PASSED | 2:00 |
| 3 | The 1,080/1,090 twin: check step → correction → R02 clears → approve | 2:00 |
| 4 | Two holds: bank-account swap (R08) and hidden instructions (R09) | 1:30 |
| 5 | Export → CSV appears → row traced to the page box → second run exports nothing | 1:30 |
| 6 | Trace: one CSV cell → file → page → box → model + rule versions | 1:00 |
| 7 | Accuracy dashboard, labeled synthetic | 0:30 |

### Recording the run (decided 2026-11-13)

> **Superseded 2026-11-17.** The database now holds all 57 generated invoices (one folder,
> `data/generated/invoices/`, including the 4 below and 3 over the auto-pass limit), and the
> live demo uses the 6 new invoices in `data/live-demo/`. See `docs/windows-setup.md`.

The demo has two parts: a recorded full run of 50 documents, then 4 uploaded live.

- **Full run (recorded).** The 50 in `data/generated/invoices/` take about 25 minutes at
  ~26 s each on gemma4:12b. That is too long to watch, so this part is recorded and the
  processing stretch is sped up, with the speed-up labeled on screen (for example "sped up
  20×, real time 25 min"). Every number on screen still comes from the run itself.
- **Live demo.** The 4 in `data/generated/live-demo/` are clean invoices: two digital PDFs
  (VTR-2026-9001, PWS-2026-9002) and two image-only scans (MEL-2026-9003, GSH-2026-9004), so
  the only difference on screen is how the words were read. They are kept out of the full
  run on purpose: once processed, the same file is skipped at intake and a new copy with the
  same number is held by R05, so they could not be shown fresh afterward.

Steps:

1. `make data`: writes both folders and stamps each file's time with its arrival order (the
   4 after the 50). A repeated invoice number gets ` (2)` on the later arrival.
2. `make up`, then `make reset`: empty database, empty `data/inbox`.
3. Start recording. `make drop-all` copies the 50 into `data/inbox` (keeping the times), then
   `make intake` starts the run instead of waiting for the 5-minute schedule. Intake reads
   the inbox oldest first, so each re-send comes after its original and R05 catches it.
4. When all 50 are done, stop the speed-up. Live: `make drop-live`, then `make intake`.

While the model reads an invoice, the Queue shows it as a "Processing…" card (the page
refreshes every 3 s), so both parts show work in progress, not only finished invoices.

`make demo-data RESET=1` rehearses both parts without Airflow, in the same order, scores
each folder against the answer key in `data/generated/answer-key/`, and records the replay
cache.

### Rehearsal and demo day with Airflow (2026-11-19)

The six in `data/live-demo/` are uploaded on stage and run through Airflow with the live model.
A live run with too little free memory took 33 minutes and froze the Mac (2026-11-19), so:

Rehearse without the model (about 15 s for the six, measured 2026-11-19):

1. `make erase-live STACK=1 KEEP_ANSWERS=1`: takes the six out of the stack's database and
   keeps their recorded model answers.
2. `LLM_MODE=replay make up`: the stack replays recorded answers; Ollama loads nothing.
3. Upload the six on the Upload page (or `make drop-live`, then `make intake`) and watch the
   Airflow tab. Repeat from step 1 for another rehearsal.

Demo day, with the live model:

1. Quit apps you don't need, restart Docker Desktop, and open Activity Monitor → Memory: the
   memory pressure graph should be green before you start.
2. `make erase-live STACK=1`: takes the six out and deletes their recorded answers, so the
   model reads them fresh on stage.
3. `make up`: live mode, from `.env`.
4. Upload the six on stage with the Airflow tab open.

## 5. How it is built (work breakdown)

1. **Demo page + flow strip + technical toggle** (`app/pages/story.py`, `app/flow.py`,
   `app/ui.py`): read-only against the dev/full-stack DB; every card's data is a SQL query
   through `app/queries.py` or the `Repository` protocol. (Integrator + one WS7-style agent.)
2. **Inbox batch view** in `app/pages/queue.py` (thumbnail grid from `pages.image_path`);
   WS1 adds the optional display-only `batch-overview.pdf`.
3. **Compliance cards**: a small `app/compliance.py` mapping rule IDs to IRAS/SPF/OWASP/
   PINT SG citations (text already in the build plan §6/§12).
4. **CSV trace drill-down**: extend `app/pages/trace.py` to join `export_rows →
   documents → fields` and draw the box.
5. **Demo-state tooling** (exists, verify): `make demo-data`, `make snapshot`/`restore`,
   `LLM_MODE=replay` for repeatability; rehearse twice with `make restore` between runs
   (plan §8).
6. **Definition of done** (mirrors plan §8): the 10-minute story runs twice in a row; every
   screen's numbers come from the DB/eval report; replay mode runs the whole story with
   Ollama stopped; a non-technical reviewer (e.g. a finance colleague) can retell the story
   from the screens alone.

## 6. Requirement traceability (shown in the demo itself)

| Demo step | Proves | Requirement |
|---|---|---|
| Read (OCR, hidden text) | R07, R09 | OWASP LLM01:2025 (hidden instructions); R07 is a PTC control (the IRAS page sets no readability rule) |
| Extract (copies as printed) | grounding | IRAS field list; PINT SG field IDs |
| Understand (normalize + locate) | R01 | "every value must appear on the page" |
| Check (totals, GST, vendor, duplicates, dates, PO) | R02–R06, R10–R12 | IRAS invoicing rules; plan §6 |
| Check (bank account) | R08 | SPF 20 May 2026 advisory |
| Review (human correction + approve) | the human gate | "finance stays in control" (technical notes) |
| Export (CSV + manifest + export-once) | SAP contract | hypothetical layout labeled as such |
| Accuracy (synthetic eval) | honesty | plan §12 accuracy-figure note |

## 7. What this plan deliberately does NOT do

- No new backend services or databases; no slide deck (the app is the deck).
- No multi-invoice PDF splitting (out of scope per plan §13; the 20-invoice batch is shown
  as a grid, with an optional display-only overview PDF).
- No real Kallang data anywhere; everything stays synthetic and labeled.
