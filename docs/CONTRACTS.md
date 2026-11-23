# Contracts v1 (Phase 0)

The shared agreements every workstream builds against. Frozen at git tag **`contracts-v1`**.
The build plan is `Track 10 Local Demo Build Plan.md` in the Obsidian vault; this file is the
short version you keep open while coding.

Phase 0 is finished: the contracts, the schema, the config, the golden fixtures, and a
skeleton pipeline that runs both fixtures through every stub stage.

---

## 1. Ground rules

1. **Only the integrator changes contract files.** They are:
   `src/invoiceflow/contracts/**`, `db/migrations/**`, `config/company.yaml`,
   `tests/fixtures/golden/**`, `tests/unit/contracts/**`, this document, and `pyproject.toml`.
   A workstream may change the *values* in the config file it owns (WS3 `models.yaml`, WS5
   `rules.yaml`, WS8 `sap_mapping.yaml`) but must not rename or remove keys. Anything else
   goes in [`contract-requests.md`](contract-requests.md), and the workstream keeps building
   against the current contract.
2. **Edit only your own paths.** Workstream ownership is in section 9.
3. **Tests first.** `make test` must pass; your paths need at least 80% coverage.
4. **No new dependencies.** Everything is declared in `pyproject.toml`. Ask if you need more.
5. **No secrets in code or config.** Read `.env` and `config/` at runtime.
6. **Frozen models, pure functions.** Return new objects instead of mutating inputs. No rule
   touches the database or the filesystem.
7. **Synthetic data only.** Never commit a real invoice.
8. **Python 3.12, type hints, `ruff format` + `ruff check`.**

## 2. Data agreements

| Agreement | Detail |
|---|---|
| File identity | SHA-256 of the bytes. `bronze_files.sha256` is unique; storing the same bytes twice is a no-op. |
| Document identity | `doc_id: UUID` identifies one invoice. In the demo one file holds one invoice. |
| Boxes | Fractions of the page, 0–1, measured from the **top-left**. Works for PDF text, OCR, and the review screen at any resolution. |
| Printed vs normalized | `InvoiceExtraction` holds strings **exactly as printed**. Python converts them into `NormalizedInvoice`. |
| Money | `Decimal` only, two places, half-up. `money()` refuses floats. |
| Dates | `date` in normalized models. The model copies the printed string; the vendor locale decides day-first vs month-first. |
| Sequences | Tuples, so a built model cannot be appended to. `extra="forbid"`, `frozen=True`. |
| Hidden words | `Word.hidden = True`. Kept as evidence, removed from prompt text and from on-page search. |
| Statuses | `RECEIVED → PARSED → EXTRACTED → AUTO_PASSED \| NEEDS_REVIEW \| ON_HOLD \| MANUAL_ENTRY \| NOT_INVOICE → APPROVED \| REJECTED → EXPORTED` |
| XCom | IDs only. State lives in Postgres and `data/`. |
| Model calls | Record model name + digest, prompt version, schema version, params, tokens, latency, and mode (live/replay). |

## 3. Enums (`contracts/enums.py`)

| Enum | Values |
|---|---|
| `FileKind` | `PDF`, `IMAGE`, `PEPPOL_XML`, `XLSX`, `UNKNOWN` |
| `TextSource` | `PDF_TEXT`, `OCR`, `EINVOICE` |
| `DocType` | `TAX_INVOICE`, `SIMPLIFIED_TAX_INVOICE`, `INVOICE`, `CREDIT_NOTE`, `DEBIT_NOTE`, `STATEMENT`, `QUOTATION`, `DELIVERY_ORDER`, `OTHER` |
| `DocStatus` | see the flow above |
| `Severity` | `INFO` (0), `FLAG` (1), `HOLD` (2), `MANUAL` (3); `.rank` orders them |
| `Scope` | `FIELD`, `DOCUMENT` |
| `Stage` | `INTAKE`, `REVIEW`, `EXPORT` |
| `MatchType` | `EXACT`, `NUMERIC`, `FUZZY`, `NONE` |
| `Confidence` | `HIGH`, `MEDIUM`, `LOW` |
| `ValueSource` | `MODEL`, `REVIEWER`, `EINVOICE` |
| `CodingSource` | `PO`, `VENUE`, `VENDOR_DEFAULT`, `REVIEWER`, `NONE` |
| `LLMMode` | `LIVE`, `REPLAY` |
| `ReviewAction` | `CONFIRM`, `CORRECT`, `RECODE`, `APPROVE`, `REJECT`, `RELEASE_HOLD` |

Enum values are stored verbatim in Postgres. The SQL `CHECK` constraints are generated from
these lists at review time and are enforced by `tests/unit/contracts/test_sql_contract.py`.

## 4. Models (`contracts/models.py`)

| Area | Models |
|---|---|
| Parsing | `Word`, `PageText`, `ParsedDocument` (`visible_words`, `hidden_words`) |
| Model output | `ExtractedLineItem`, `InvoiceExtraction`, `ExtractionRequest`, `ExtractionResult`, `HEADER_FIELDS`, `PINT_SG_TERMS` |
| Standardizing | `NormalizedLineItem`, `NormalizedInvoice`, `NormalizationResult`, `FieldLocation`, `FieldValue` |
| Master data | `Vendor`, `PurchaseOrder`, `GLAccount`, `CostCenter`, `TaxCode`, `VenueAlias`, `CodingMaster`, `CompanyProfile`, `MasterData`, `PriorInvoice` |
| Coding | `CodingLine` (`gross_amount` = net + tax) |
| Checks | `Finding`, `FieldConfidence`, `RoutingDecision`, `CheckContext` |
| Records | `BronzeFile`, `DocumentRecord`, `Review`, `ExportBatch` |
| Evaluation | `InvoiceTruth` (printed extraction + normalized invoice + expected coding + anomalies) |

`InvoiceExtraction`'s JSON schema is the structured-output schema sent to the model. Its
`SCHEMA_VERSION` is `extraction-v1`.

`CheckContext` is everything a rule may read: the document, the extraction result, the
normalized invoice, vendor, PO, coding lines, locations, master data, prior invoices, and
`rules_config`. Rules never reach outside it.

## 5. Protocols (`contracts/interfaces.py`)

| Protocol | Methods | Implemented by |
|---|---|---|
| `TextExtractor` | `parse(path, file_id=, doc_id=)`, `page_texts(document)` | WS2 `parse/` |
| `LLMClient` | `extract(request)` | WS3 `extract/` (Ollama, replay, Azure later) |
| `VendorMatcher` | `match(extraction, vendors)` | WS4 `normalize/` |
| `Normalizer` | `to_normalized(extraction, vendor)` | WS4 `normalize/` |
| `Locator` | `locate(document, extraction)` | WS4 `locate/` |
| `Coder` | `assign(invoice, vendor, po, master)` | WS8 `coding/` |
| `Rule` | `id`, `check(ctx)` | WS5 `rules/` |
| `Router` | `route(ctx, findings)` | WS5 `rules/` |
| `BlobStore` | `put_bronze`, `read`, `put_silver`, `put_gold` | WS6 `storage/` |
| `Repository` | all Postgres reads/writes listed in the protocol | WS6 `store/` |

The pipeline (section 6) only calls these. Swapping a stub for the real implementation is a
one-line change in `pipeline/stages.py`'s `PipelineDeps`.

## 6. Pipeline order and stubs

`pipeline/stages.py` is plain Python (no Airflow imports), so an Azure Function can call the
same functions later:

```
parse → extract → match vendor → normalize → find PO → assign coding → locate fields
      → run rules → route
```

Coding happens **before** the checks, so R06 and the review screen see the coding lines.
`process_document()` runs every stage without persisting anything. The Airflow DAG (WS6) and
the review app call these functions; they never contain business logic.

Phase 0 stubs (`pipeline/stubs.py`) replay the golden fixtures:

| Stub | Replaced by |
|---|---|
| `GoldenTextExtractor` | WS2 |
| `GoldenLLMClient` | WS3 (`ReplayClient` keeps replay behaviour) |
| `GoldenVendorMatcher`, `GoldenNormalizer`, `GoldenLocator` | WS4 |
| `GoldenFindingsRule`, `SeverityRouter` | WS5 |
| `GoldenCoder` | WS8 |
| — (nothing yet) | WS6 `BlobStore` + `Repository` |
| `devdb/` loader | WS6 `store/repo.py` + migration runner in `airflow-init` |

`python -m invoiceflow.pipeline.skeleton` (or `make skeleton`) runs both fixtures and prints
where each was routed. It exits non-zero if a status or rule does not match the manifest.

## 7. Database (`db/migrations/001_init.sql`)

20 tables in four groups:

| Layer | Tables |
|---|---|
| Master data | `vendors`, `purchase_orders`, `gl_accounts`, `cost_centers`, `tax_codes`, `venue_cost_centers` |
| Bronze | `bronze_files` (sha256 unique) |
| Silver | `documents`, `pages`, `extractions`, `fields`, `line_items`, `coding_lines`, `findings`, `reviews` |
| Gold | `export_batches`, `export_rows` |
| All | `events`, `notifications`, `schema_migrations` |

Invariants the database enforces, not the application:

- `export_rows` has primary key `(batch_id, doc_id)`: an invoice appears at most once per
  batch. Since CR-013 (migration 003) `doc_id` alone is not unique, so a person can send an
  invoice again in a later batch and every send is kept. A run sends an invoice again only
  when it is named in `export_approved(resend=...)`.
- `events` is append-only (`BEFORE UPDATE OR DELETE` triggers an exception).
- `fields`, `line_items`, and `coding_lines` keep history: a partial unique index on
  `(doc_id, name)` / `(doc_id, line_no)` where `is_current` means at most one current row.
  Never update in place; insert a new version and clear the old `is_current`.
- `findings.rule_id` matches `^R[0-9]{2}$`; `reviews` refuse a `RELEASE_HOLD` without a comment.
- Enum `CHECK` lists match the Python enums (tested).
- Money columns are `numeric(14,2)`.

`devdb/` is Phase 0 scaffolding only: `connect`, `apply_migrations` (tracked in
`schema_migrations`), and `load_fixtures` (truncate + insert the golden set through the stubs).
WS6 replaces it with `store/` and `storage/`; do not build on it.

## 8. Config and environment

| File | Keys that matter |
|---|---|
| `config/company.yaml` | `company_code` (`KG01`), `currency`, `timezone`, `entity_names` (R04) |
| `config/rules.yaml` | `severities` R01–R12, `tolerances`, `gst_rates`, simplified-invoice limit, fuzzy score, invoice age, duplicate window, OCR thresholds, hidden-text limits, `instruction_phrases` |
| `config/models.yaml` | `provider: ollama`, `model: gemma4:12b`, fallback `qwen3-vl:4b`, `think: false`, temperature 0, seed 42, `num_ctx: 8192`, image mode, prompt path, Azure env-var names |
| `config/sap_mapping.yaml` | `layout: hypothetical`, one row per coding line, 16 columns with `source`, `required`, `max_len`, `format` |
| `.env` | `AP_DATABASE_URL` (or `AP_DB_*`), `OLLAMA_BASE_URL`, `LLM_MODE`, Azure names. `.env.example` is the template; never commit `.env`. |

Amounts in YAML are strings on purpose, so they load as `Decimal` and never as float.

## 9. Workstream ownership

| WS | Owns |
|---|---|
| WS1 | `generator/`, `seeds/`, `fonts/` |
| WS2 | `src/invoiceflow/parse/` |
| WS3 | `src/invoiceflow/extract/`, `prompts/`, `config/models.yaml`, `scripts/bench_models.py` |
| WS4 | `src/invoiceflow/normalize/`, `src/invoiceflow/locate/` |
| WS5 | `src/invoiceflow/rules/`, `config/rules.yaml` |
| WS6 | `docker/`, `docker-compose.yaml`, `compose.dev.yaml`, `db/`, `src/invoiceflow/store/`, `src/invoiceflow/storage/`, `dags/`, `scripts/` (except `bench_models.py`), `Makefile` |
| WS7 | `app/` |
| WS8 | `src/invoiceflow/coding/`, `export/`, `evaluate/`, `config/sap_mapping.yaml` |

Each workstream also owns `tests/unit/<module>/` and `tests/integration/<ws>/`.

## 10. Golden fixtures (`tests/fixtures/golden/`)

Two type A invoices (event equipment rental), built by `scripts/build_golden.py`
(`make golden`; needs Pango, which the Makefile points at on macOS):

| Fixture | Invoice | Subtotal | GST 9% | Total | Expected |
|---|---|---|---|---|---|
| `golden-a-clean` | SAV-2026-0412 | 1,080.00 | 97.20 | 1,177.20 | `AUTO_PASSED`, no findings |
| `golden-a-total-mismatch` | SAV-2026-0413 | 1,090.00 | 98.10 | 1,188.10 | `NEEDS_REVIEW`, R02 on `subtotal` |

The twin's lines add up to 1,080.00 while the printed subtotal is 1,090.00; GST and total
follow the printed subtotal, so only R02 fires. That is the slide-3 story, runnable on day one.

Each fixture directory contains:

| File | Contents |
|---|---|
| `invoice.pdf` | The rendered invoice |
| `page-1.png` | 150 DPI page image for boxes and the review screen |
| `page-1.words.json` | `PageText` from pdfplumber, boxes as page fractions |
| `extraction.json` | Recorded `ExtractionResult` (mode `REPLAY`, model `golden-recorded`) |
| `locations.json` | `FieldLocation` for every value found on the page |
| `truth.json` | `InvoiceTruth` (printed + normalized + expected coding) |
| `expected_findings.json` | Findings the checks must produce |

`manifest.json` holds the fixed doc/file UUIDs and PDF hashes; `master.json` holds the
hypothetical vendor, PO, GL accounts, cost centers, tax codes, and venue aliases.
Golden runs use `today = 2026-11-04` (`GOLDEN_TODAY`) so date checks repeat exactly.
All names, UENs, account numbers, and codes are fictional.

## 11. Commands

```bash
make setup                  # uv sync --all-extras; creates .env from .env.example
make test                   # pytest with coverage (db tests skip when Postgres is down)
make skeleton               # both fixtures through every stub stage
make db-dev                 # Postgres 16 on 127.0.0.1:5433 + migrations
make fixtures               # load master data + both documents into the ap database
make golden                 # rebuild the fixture files
make lint / make fmt        # ruff
```

The dev database defaults to `postgresql://ap:change-me@127.0.0.1:5433/ap` and can be
overridden with `AP_DATABASE_URL`. `make down` stops it. Phase 1 targets (`up`, `data`,
`warm`, `demo-data`, `drop`, `export`, `eval`, `bench`, `snapshot`, `restore`, `e2e`, …)
exist in the Makefile but exit with the workstream that owns them.

## 12. Change process

1. Add a row to [`contract-requests.md`](contract-requests.md): what, why, which workstream,
   what breaks. Do not edit the contract on your branch.
2. The integrator applies the change on `main`, updates the contract tests, and re-tags
   (`contracts-v2`).
3. Worktrees rebase onto the new tag and re-run `make test`. Additive changes are preferred;
   renames need a migration and a note in the request.
4. If the model's output schema changes, bump `SCHEMA_VERSION` in `contracts/__init__.py` and
   keep old recorded responses readable.

Open contract questions belong in `contract-requests.md`, not in code comments.
