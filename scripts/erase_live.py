"""`make erase-live`: remove the live-demo invoices, keep every other invoice.

Usage:
    uv run python scripts/erase_live.py                    # the 6 in data/live-demo/
    uv run python scripts/erase_live.py --dry-run          # only show what would go
    uv run python scripts/erase_live.py --folder data/hidden-text-samples
    uv run python scripts/erase_live.py --stack --keep-answers   # before a replay rehearsal

Run it after a live demo to be able to run the demo again. The database rows, the stored
and parsed files, inbox copies, and recorded model answers of those invoices go; an export
batch that included one is removed and its other invoices can be exported again.

``--stack`` erases from the full stack's database (`make up`) instead of the dev one.
``--keep-answers`` keeps the recorded model answers, so ``LLM_MODE=replay`` can rehearse the
same set; erase without it before the real demo, so the model reads them live.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from invoiceflow.extract import load_model_config
from invoiceflow.pipeline.demo_data import live_set_dir
from invoiceflow.settings import data_dir, load_config
from invoiceflow.store.connection import connect, use_stack_database
from invoiceflow.store.erase import apply_erase, plan_erase, remove_files, target_from_folder

ACTOR = "erase-live"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=None, help="the set to erase")
    parser.add_argument("--dry-run", action="store_true", help="show, change nothing")
    parser.add_argument("--stack", action="store_true", help="the full stack's database")
    parser.add_argument(
        "--keep-answers", action="store_true", help="keep the recorded model answers"
    )
    args = parser.parse_args()

    load_config("rules")  # also reads .env, so the database URL is ready
    if args.stack:
        use_stack_database()
    folder = args.folder or live_set_dir()
    if not folder.is_dir():
        raise SystemExit(f"{folder} does not exist")
    target = target_from_folder(folder)
    with connect() as conn, conn.transaction():
        plan = plan_erase(conn, target)
        print(f"Live-demo set: {folder} ({len(target.sha256s)} files)")
        if plan.doc_ids:
            print(
                f"In the database: {len(plan.doc_ids)} invoice(s): "
                f"{', '.join(plan.invoice_numbers) or '(no invoice number read)'}"
            )
        else:
            print("In the database: none of them.")
        if plan.batch_ids:
            print(f"Export batches that included one, to be removed: {', '.join(plan.batch_ids)}")
            print(f"Other invoices in those batches, back to ready to export: {len(plan.reverted)}")
        if args.dry_run:
            print("Dry run: nothing changed.")
            return 0
        apply_erase(conn, plan, actor=ACTOR)
    cache_dir = None if args.keep_answers else load_model_config().cache_dir
    removed = remove_files(plan, data_root=data_dir(), cache_dir=cache_dir)
    print(
        f"Removed {len(plan.doc_ids)} invoice(s) from the database and {len(removed)} "
        "file(s) or folder(s) from data/. Every other invoice is unchanged."
    )
    if args.keep_answers:
        print("Their recorded model answers are kept, for LLM_MODE=replay rehearsals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
