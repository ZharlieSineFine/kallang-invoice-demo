# Phase 2 merge runbook (integrator)

For the integrator session after the eight workstream branches land. Order and gates per
build plan section 8. All commands run in `~/Projects/kallang-invoice-demo` (main).

## 1. Collect the branches

```bash
git branch -a | grep ws   # expect ws1-generator .. ws8-export
# for each: check the handoff file and the last commit
git log --oneline -1 ws6-platform && cat ../kallang-ws6-platform/HANDOFF-ws6.md | head -50
```

Before merging a branch, confirm in its worktree:
- `make test` passes (at least 80% coverage on its paths),
- `ruff format --check . && ruff check .` passes,
- no edits outside its owned paths (`git diff --name-only contracts-v1..<branch>`),
- contract requests in `docs/contract-requests.md` are read and decided before merge,
- `HANDOFF-<ws>.md` exists.

## 2. Merge order

1. **WS6 first** (`git merge ws6-platform`), because it owns the Makefile, compose files,
   store/storage, and pipeline wiring that everything else hooks into.
2. Then, in any order: ws1-generator, ws2-parse, ws3-extract, ws4-locate, ws5-rules,
   ws7-app, ws8-export.
3. **After every merge:** `make test`. Fix failures in the branch (or on main for wiring),
   never silently drop a failing test.

Conflicts are expected only on shared config keys (models.yaml/rules.yaml/sap_mapping.yaml
values) and `docs/contract-requests.md`. Contract files themselves are frozen; if a branch
touched one, do not merge it — send the change back as a request.

## 3. Swap the stubs for the real stages

In `src/invoiceflow/pipeline/stubs.py` / `stages.py`, replace:

| Stub | Real implementation |
|---|---|
| `GoldenTextExtractor` | WS2 `parse/` |
| `GoldenLLMClient` | WS3 `extract/` (`LLM_MODE=replay` keeps the ReplayClient) |
| `GoldenVendorMatcher`, `GoldenNormalizer`, `GoldenLocator` | WS4 |
| `GoldenFindingsRule`, `SeverityRouter` | WS5 `rules/` registry + router |
| `GoldenCoder` | WS8 `coding/assign` |
| `devdb/` fixture loader role | WS6 `store/repo.py` + `storage/` |

After the swap, `make skeleton` must still route both golden fixtures exactly as the
manifest expects (`AUTO_PASSED` / `NEEDS_REVIEW` + R02). That is the integration gate before
anything else runs.

## 4. Phase 2 gates (build plan section 8)

1. `make test` green after each merge; `make skeleton` green after the stub swap.
2. WS5's perfect-extraction test over WS1's whole dataset (`make data SEED=42` first).
3. `make bench`, then `make eval-bench`; record the decision in `docs/model-choice.md`
   (measured accuracy, seconds per invoice, peak memory, fallback comparison).
4. `make demo-data` with the live model (records the replay cache), then `make e2e` in
   replay mode with Ollama stopped.
5. python-reviewer + security-reviewer passes over the merged code; fix CRITICAL/HIGH.
6. Rehearse the 10-minute story twice with `make restore` in between; watch memory pressure.
7. `make snapshot`; write the README (setup, runbook, troubleshooting, screenshots).

## 5. Done when (build plan section 8)

- Fresh clone: `make setup && make up && make demo-data` works.
- The 10-minute story runs twice in a row with `make restore` in between.
- Replay mode runs the story with Ollama stopped.
- `make test` passes with at least 80% coverage on `src/`.
- Every number on screen comes from the database or the evaluation report.
