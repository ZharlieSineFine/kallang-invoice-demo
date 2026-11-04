# HANDOFF — WS4: standardizing values and finding them on the page

Branch: `ws4-locate` (based on `contracts-v1`). No contract files changed; no contract request
was needed. No Ollama call was made.

> **Commit status:** the source, tests, and this file are complete in the worktree. The commit
> itself was not created in this headless session: git writes its index/refs under
> `kallang-invoice-demo/.git/worktrees/kallang-ws4-locate`, outside the workspace sandbox, and
> no approval channel was available. Run the two commands under "How to run" once approval is
> available.

## Done

### `src/invoiceflow/normalize/`

- **Amounts** (`amounts.py`): `S$`, `SGD`, `$`, commas, spaces, apostrophes, `+`/`-`, unicode
  minus, and trailing signs. Parentheses mean negative. Money is `Decimal`, rounded half-up to
  two places through `contracts.money.money`; quantities/days keep their printed precision.
  `normalize_percent` handles `9%`, `9.00 %`, and rejects malformed grouping.
- **Dates** (`dates.py`): ISO (`2026-10-15`), `15/10/2026`, `15-10-2026`, `15.10.2026`,
  `12 Oct 2026`, `12 October 2026`, `12-Oct-2026`, `Oct 12, 2026`, two-digit years, and
  weekday prefixes. Day-first by default; `locale="US"` / `en_US` reads month-first.
  `normalize_date` returns `(date, ambiguous)`, where both first components <= 12 sets the
  ambiguity flag.
- **IDs** (`ids.py`): uppercase, spaces and hyphen-like characters removed
  (`M2-1234567-8` -> `M212345678`); leading `UEN:` / `GST Reg No:` labels are stripped.
- **Text** (`text.py`): NFKC, zero-width removal, whitespace collapse, and case folding for
  comparison keys. `clean_text` keeps printed case for stored names.
- **Currency** (`currency.py`): ISO 4217 mapping, `S$`/`SGD`/`US$`/`RM`/`RMB`/symbols, plus
  inference from an amount prefix.
- **Vendor matching** (`vendor.py`): exact GST registration number or UEN first (punctuation
  insensitive), then rapidfuzz `WRatio >= 90` on the supplier name.
- **`to_normalized(extraction, vendor)`** (`normalizer.py`): returns a frozen
  `NormalizationResult` with a `NormalizedInvoice` and deterministic conversion problems.
  Handles money, percentages, dates, currency, IDs, bank account digits, GST-inclusive notes,
  and line items. It never raises and never mutates the extraction.

### `src/invoiceflow/locate/`

- Builds an index of every run of **1–8 consecutive visible words**, allowing a run to cross at
  most **3 lines** (`MAX_RUN_WORDS`, `MAX_RUN_LINES`). Hidden words are excluded at token
  construction time.
- Match tiers: **EXACT** text, then **NUMERIC** equal value, then **FUZZY** rapidfuzz `WRatio
  >= 90` (with a length-ratio guard so a partial run cannot claim a longer value).
- Duplicate disambiguation: a candidate next to the field's label wins (`Total`,
  `Total Payable`, `GST`, `GST Reg No:`, `Invoice No:`, etc.). Line-item amounts additionally
  prefer the description's row and the rightmost column.
- Returns a `FieldLocation` for every evidence field, including `MatchType.NONE` for values
  that are missing or not found, so R01 can distinguish "not extracted" from "not on page".
- Locatable set matches the golden evidence vectors: 16 header fields plus line-item
  `description` and `amount` (`locate/fields.py`).

### Protocol implementations

`invoiceflow.normalize.VendorMatcher`, `invoiceflow.normalize.Normalizer`, and
`invoiceflow.locate.Locator` satisfy the frozen protocols (runtime `isinstance` tests).
Module-level `match_vendor`, `to_normalized`, and `locate` functions are available too.

```python
from invoiceflow.locate import Locator
from invoiceflow.normalize import Normalizer, VendorMatcher

vendor = VendorMatcher().match(extraction, vendors)
normalized = Normalizer().to_normalized(extraction, vendor)
locations = Locator().locate(document, extraction)
```

## Acceptance evidence

- `make test`: **206 passed**, overall coverage **96.6%**; WS4 files are 94–100% each.
- Golden digital PDFs, using the shipped `page-1.words.json` and `locations.json`:
  - `golden-a-clean`: **24/24** expected locations exact, 0 normalization problems.
  - `golden-a-total-mismatch`: **24/24** expected locations exact, 0 normalization problems.
  - **48/48 = 100%** of expected golden fields found (target was 98%).
- Both golden `truth.json` invoices normalize **exactly** to `truth.invoice`.
- `tests/integration/ws4/test_pipeline_swap.py` replaces only the three WS4 stubs inside
  `check_stage`; both golden documents keep their expected status and findings.
- `make skeleton` and `make lint` still pass.

## How to run

```bash
export UV_CACHE_DIR=/tmp/kallang-ws4-uv-cache   # only needed if the default uv cache is unwritable
uv sync --all-extras
make test
make lint
make skeleton

git add src/invoiceflow/normalize src/invoiceflow/locate \
  tests/unit/normalize tests/unit/locate tests/integration/ws4 HANDOFF-ws4.md
git commit -m "WS4: normalize printed values and locate them on the page"
```

Focused runs:

```bash
uv run pytest tests/unit/normalize tests/unit/locate tests/integration/ws4 -q
uv run pytest tests/unit/normalize tests/unit/locate tests/integration/ws4 \
  --cov=invoiceflow.normalize --cov=invoiceflow.locate --cov-report=term-missing
```

## What is left / notes for the integrator

1. **Wire the stubs.** Replace `GoldenVendorMatcher`, `GoldenNormalizer`, and `GoldenLocator`
   in `pipeline/stubs.py` / `PipelineDeps` with the three classes above. This file is owned by
   the integrator; WS4 did not edit it.
2. **WS1 generated corpus gap.** The 100% figure is against the two golden digital PDFs, the
   only corpus present in this worktree. There is no WS1 `generator/` output yet. When WS1
   lands, rerun `tests/integration/ws4/test_golden_locations.py` pattern against each truth
   `printed` + `locations.json`; the code is independent of the fixture set.
3. **Locatable field set.** Only the golden evidence fields are located. If WS5 R01 needs
   boxes for `amount_due`, `discount`, `contract_number`, `payment_terms`, `title`, or line
   quantities/unit prices, add them to `LOCATABLE_HEADER_FIELDS` / `LINE_ITEM_FIELDS` and add
   expected vectors. This is a scope decision, not a contract change.
4. **Date formats.** The parser covers the common Singapore formats in the brief plus ISO and
   month-name forms. If WS1 introduces another printed style, add a focused case to
   `tests/unit/normalize/test_dates.py` before extending the parser.
5. **OCR.** Locator tests use PDF-text boxes. OCR boxes use the same page-fraction contract, so
   no code change is expected; fuzzy matching is already the third tier.
