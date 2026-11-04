"""make skeleton: run the golden fixtures through every stage and check the outcome."""

from __future__ import annotations

from datetime import date

from invoiceflow.pipeline.golden import load_golden
from invoiceflow.pipeline.stages import process_document
from invoiceflow.pipeline.stubs import golden_deps
from invoiceflow.settings import load_config

# Golden runs use a fixed "today" so date checks give the same answer every day.
GOLDEN_TODAY = date(2026, 11, 4)


def main() -> int:
    golden = load_golden()
    deps = golden_deps(
        golden, auto_approve_clean=load_config("rules")["routing"]["auto_approve_clean"]
    )
    rules_config = load_config("rules")
    failures = 0
    print(f"{'fixture':<26} {'invoice':<15} {'status':<13} {'expected':<13} findings")
    for fixture in golden.fixtures:
        result = process_document(
            fixture.pdf_path,
            file_id=fixture.file_id,
            doc_id=fixture.doc_id,
            deps=deps,
            master=golden.master,
            today=GOLDEN_TODAY,
            run_id="skeleton",
            rules_config=rules_config,
        )
        status = result.decision.status
        found = [f.rule_id for f in result.findings]
        ok = status is fixture.expected_status and found == list(fixture.truth.expected_rules)
        failures += 0 if ok else 1
        findings = ", ".join(f"{f.rule_id} on {f.field}" for f in result.findings) or "none"
        print(
            f"{fixture.fixture_id:<26} {fixture.invoice_number:<15} {status.value:<13} "
            f"{fixture.expected_status.value:<13} {findings}{'' if ok else '  <-- MISMATCH'}"
        )
    print("skeleton OK" if failures == 0 else f"skeleton FAILED: {failures} mismatch(es)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
