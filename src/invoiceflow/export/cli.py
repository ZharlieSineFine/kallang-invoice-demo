"""Export CLI: render the SAP CSV for the golden fixtures that pass the batch checks.

The production DAG (WS6) selects ``approved_not_exported()`` documents and calls the same
:func:`export_documents` function; this CLI exists so ``python -m invoiceflow.export`` can
demonstrate the CSV and manifest without the full stack. Documents that fail a check
(e.g. the total-mismatch fixture) are reported and left out.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from invoiceflow.coding.assign import assign
from invoiceflow.export.checks import check_batch
from invoiceflow.export.exporter import build_rows, export_documents
from invoiceflow.export.mapping import load_sap_mapping
from invoiceflow.export.models import ExportDocument
from invoiceflow.pipeline.golden import load_golden
from invoiceflow.settings import load_config, repo_root

GOLDEN_TODAY = date(2026, 11, 4)


def _versions() -> tuple[str, str, str]:
    models = load_config("models")
    rules = load_config("rules")
    return (
        str(models.get("model", "")),
        str(models.get("prompt", "")),
        str(rules.get("version", "1")),
    )


def _documents() -> tuple[ExportDocument, ...]:
    golden = load_golden()
    documents: list[ExportDocument] = []
    for fixture in golden.fixtures:
        truth = fixture.truth
        vendor = golden.master.vendor(truth.vendor_id) if truth.vendor_id else None
        po = (
            golden.master.purchase_order(truth.invoice.po_number)
            if truth.invoice.po_number
            else None
        )
        coding = assign(truth.invoice, vendor, po, golden.master.coding)
        documents.append(ExportDocument(fixture.doc_id, truth.invoice, vendor, coding))
    return tuple(documents)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the SAP export CSV for the demo.")
    parser.add_argument("--out", default=str(repo_root() / "data" / "export"))
    args = parser.parse_args(argv)

    mapping = load_sap_mapping(load_config("sap_mapping"))
    model, prompt_version, rule_version = _versions()
    golden = load_golden()
    master = golden.master.coding
    out_dir = Path(args.out)

    exportable: list[ExportDocument] = []
    for doc in _documents():
        problems = check_batch(mapping, build_rows(mapping, (doc,), GOLDEN_TODAY), (doc,), master)
        if problems:
            print(f"skipping {doc.invoice.invoice_number or doc.doc_id}: {problems[0]}")
        else:
            exportable.append(doc)

    if not exportable:
        print("nothing exportable; all documents failed a batch check", file=sys.stderr)
        return 1

    batch_id = f"sap-{GOLDEN_TODAY.isoformat()}"
    result = export_documents(
        mapping,
        tuple(exportable),
        master,
        export_date=GOLDEN_TODAY,
        batch_id=batch_id,
        out_dir=out_dir,
        model=model,
        prompt_version=prompt_version,
        rule_version=rule_version,
    )
    print(f"wrote {result.csv_path} ({result.manifest.row_count} row(s))")
    print(f"wrote {result.manifest_path}")
    print(f"csv_sha256 {result.manifest.csv_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
