# HANDOFF — WS1: Synthetic invoices

Branch `ws1-generator`, based on `contracts-v1`. Everything is synthetic: UENs use the fictional
year 2099, GST numbers equal UENs, bank accounts are invented, and no real invoice is committed.

## What is done

- **Seeds** in `seeds/`:
  - `vendors.csv` — 12 active fictional vendors plus `V999` (inactive, the unknown vendor).
    Each row carries the vendor's default GL account, cost centre, and tax code.
  - `purchase_orders.csv` — 14 POs, each with its own GL account and cost centre.
  - `cost_centers.csv`, `gl_accounts.csv`, `tax_codes.csv`, `venue_cost_centers.csv` — the
    hypothetical coding data from build-plan section 5.5, including short forms `Indoor
    Stadium` and `SIS`.
- **Templates** in `generator/templates/`: Jinja2 HTML for A1, A2 (simplified, GST-inclusive),
  B1, B2, C1, credit note, and statement. Rendered with WeasyPrint.
- **Fonts** in `fonts/`: Fira Sans (body) and IBM Plex Mono (amounts), both SIL OFL. The two
  licence files are next to the TTFs and the `@font-face` URLs are relative to the repo root,
  so PDFs render the same on every machine.
- **Type C scans**: each C1 page is rasterised at 150 DPI, given a small rotation and a light
  Gaussian blur, then run through Augraphy for paper noise and JPEG artefacts. It is saved as
  both a JPG and a deterministic one-page image PDF. (Augraphy's geometric rotator crops and
  resamples the A4 canvas, so the rotation uses PIL to keep the page size and make the scan
  metadata readable; Augraphy still supplies the paper damage.)
- **Amounts** use `Decimal` everywhere. Standard invoices calculate GST on the net subtotal;
  simplified invoices print GST-inclusive prices and back the net/GST split out of the gross.
- **Truth and manifest**: every document gets `truth.json` (`InvoiceTruth`, including expected
  coding lines) and a row in `manifest.json` with `id`, `set`, `doc_type`, `template`,
  `anomalies`, `expected_checks`, file paths, SHA-256, and whether it has a text layer.
- **CLI**: `generator/build.py` / `python -m generator.build`.

## Dataset (seed 42)

Total **50** documents: `pre` = 36 ("yesterday"), `live` = 4, `benchmark` = 10.

| Set | Contents |
|---|---|
| `pre` | 12 A, 12 B, 8 C, 2 credit notes, 1 statement, 1 USD invoice |
| `live` | `live-01` clean A, `live-02` the 1,080 / 1,090 invoice, `live-03` bank-account change, `live-04` hidden instructions |
| `benchmark` | 4 A, 3 B, 3 C, all clean |

All 14 anomalies from the brief are present at least once:

| Anomaly | Documents | Rule |
|---|---|---|
| `total_edited` | `pre-a-03`, `live-02` | R02 |
| `gst_wrong_rate` | `pre-a-04` | R03 |
| `gst_reg_missing` | `pre-a-05` | R03 |
| `resend` | `pre-c-02` (image re-scan of `pre-a-01`) | R05 |
| `duplicate_file` | `pre-b-02` (byte-identical copy of `pre-b-01`) | R05 |
| `unknown_vendor` | `pre-c-04` | R04 |
| `bank_account_changed` | `pre-a-08`, `pre-b-06`, `live-03` | R08 |
| `hidden_instructions` | `pre-b-07`, `live-04` | R09 |
| `visible_instructions` | `pre-a-09`, `pre-b-10` | R09 |
| `us_date_month_first` | `pre-a-06` (printed `03/04/2026`, normalized `2026-03-04`) | R11 |
| `po_exceeded` | `pre-a-07` | R12 |
| `statement` | `pre-soa-01` | R10 |
| `credit_note` | `pre-cn-01`, `pre-cn-02` | R10 |
| `venue_no_cost_center` | `pre-b-03` (`Kallang Tennis Centre`, vendor `V011` has no default cost centre) | R06 |

`live-02` is the exact slide-3 story: lines total **S$1,080.00**, printed total
**S$1,090.00**, GST **S$97.20** on the subtotal, so only R02 should fire.

`pre-a-10` is a clean type A simplified invoice with no PO and no venue: its coding comes from
the vendor default (`VENDOR_DEFAULT`, `KG2100`).

The unknown vendor is `V999` (inactive) in `vendors.csv`. Generated `master.json` contains only
the 12 active vendors. `pre-c-04` still uses a PO, so its coding lines are complete and R04 is
the only expected finding (not R06).

## How to run

```bash
uv sync --all-extras                       # generator extra: jinja2, weasyprint, faker, augraphy
uv run python generator/build.py --seed 42 # writes data/generated/ (git-ignored)
uv run pytest tests/unit/generator tests/integration/ws1 -q
make test                                  # full suite, including the existing db tests
```

`generator/build.py --only pre|live|benchmark` is available for debugging a single set.

On macOS, `generator/render.py` sets `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` before
importing WeasyPrint, so the CLI works without the Makefile wrapper. Fonts are bundled; the
output does not depend on installed system fonts.

### What WS6 should wire `make data` to

The Makefile is WS6-owned, so I did not edit it. Replace the `data` target body with:

```make
data: ## generate the synthetic invoice set (WS1)
	$(UV) run python generator/build.py --seed $(or $(SEED),42)
```

Then `make data SEED=42` writes `data/generated/`. The command does not need the `GOLDEN_ENV`
prefix; the Python entry point handles Pango on macOS.

### Output layout

```text
data/generated/
  manifest.json
  master.json                 # 12 active vendors, POs, coding data
  docs/<document_id>/
    <document_id>.pdf         # digital PDF or one-page image PDF for C
    <document_id>.jpg         # C scans only
    truth.json                # InvoiceTruth
```

`manifest.json` keys: `schema_version`, `seed`, `generated_at` (fixed 2026-11-04T00:00:00Z),
`master`, `fonts`, `counts`, `documents`. Each document row has `id`, `set`, `doc_type`,
`template`, `anomalies`, `expected_checks`, `doc_id`, `file_id`, `file`, `truth`, `files`,
`sha256`, `text_layer`, `vendor_id`, `invoice_number`, `currency`, and `total`.

## Acceptance evidence

- **50 documents under 2 minutes**: measured **~11 s** for a full build on this Mac.
- **Same seed is byte-identical**: two full builds into different directories compare equal with
  `diff -r`; `tests/integration/ws1/test_build.py` rebuilds all 50 and compares every file.
- **Clean documents add up**: unit tests walk the lines to subtotal, GST, and total, including
  the simplified GST-inclusive case and the negative credit notes.
- **Each anomaly fires only its intended rule**: the integration test derives a signature for
  every anomaly from the truth/manifest (amount mismatch, 8% rate, missing GST number, duplicate
  hash, re-sent invoice, unknown vendor, bank change, hidden/visible instruction sizes, US date,
  PO open amount, statement/credit-note type, missing venue cost centre) and asserts it equals
  that document's `anomalies` set exactly.
- **pdfplumber reads every digital PDF**: 39 digital PDFs are checked for a non-empty text layer;
  the 11 C scans are checked to be one-page image PDFs with no text layer.
- **Scans stay readable**: Tesseract 5.5.4 reads all 11 C scans at mean confidence 82–92 (the R07
  threshold is 60) and finds every invoice number, while the pages still carry rotation, blur,
  paper noise, and JPEG artefacts.

`make test` result on this branch: **201 passed**, coverage **96.37%** (the 80% gate passes).
The project's coverage config only measures `src/invoiceflow`, so `generator/` is covered by its
own tests rather than by the coverage number; `pyproject.toml` is contract-owned and I did not
change it.

## What is left / notes

- **`make data` wiring is WS6's** (see the snippet above). The WS1 CLI is complete.
- **PINT SG XML (type D) is not built.** It was listed as a stretch in the brief and the demo
  set contains no type D document.
- **Unknown vendor:** `V999` is deliberately inactive. Loading `seeds/vendors.csv` into Postgres
  is fine (the row is `active=false`); `master.json` excludes it, matching "not in the master".
- **Statement and credit notes** carry no `expected_coding` / no coding for the statement; both
  credit notes have negative net, GST, and total and quote the original invoice.
- **USD invoice** (`pre-usd-01`) is `DocType.INVOICE` with 0% GST, tax code `OP`, and an SGD
  equivalent of 1,620.00 at the fixed synthetic rate used in the truth/data.
- **No contract changes were needed**; `docs/contract-requests.md` was not touched.

## Commit status

The working tree is complete and `make test` passes. This session could not create the commit:
the worktree's git index and refs live outside the session sandbox at
`~/Projects/kallang-invoice-demo/.git/worktrees/kallang-ws1-generator/`, and no approval channel
was available for the write. From a normal shell on the branch, run:

```bash
git add generator seeds fonts tests/unit/generator tests/integration/ws1 HANDOFF-ws1.md
git commit -m "WS1: synthetic invoices, seeds, fonts, and truth data"
```
