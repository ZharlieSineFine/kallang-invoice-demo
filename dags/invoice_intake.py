"""invoice_intake: read ``data/inbox`` every 5 minutes, or when the Upload page asks.

    register_files → invoice[n]: parse → extract (pool llm) → check → summarize

- ``register_files`` saves each waiting file with a RECEIVED document, oldest first, so the
  Queue shows them all at once; a byte-identical copy is logged and moved out.
- The ``invoice`` group runs once per file, one box per stage, each box labeled with the file
  name. ``parse`` reads the text layer or runs OCR. ``extract`` asks the model, in the one-slot
  ``llm`` pool, with 2 retries. ``check`` standardizes the values, assigns the coding, finds each
  value on the page, runs R01 to R12, routes the invoice, saves the outcome, and moves the file
  out.
- ``summarize`` counts the outcomes. It also removes the placeholder of an invoice whose stage
  failed after its retries; that file is still in the inbox, so the next run reads it again.

Order: files are mapped oldest first, ``parse`` and ``check`` run one invoice at a time,
``extract`` has one slot, and Airflow starts ready boxes in map-index order. So invoices are
checked in the order they arrived, and a re-sent invoice is checked after its original (R05
needs the original saved first). A box that fails and retries can lose its place.

The steps live in ``invoiceflow.pipeline.staged``; this file only wires them. Each stage saves
its result under ``data/work/<doc_id>/``, and XCom carries only IDs and the inbox path.

Imports: reading this file loads only ``airflow``, ``pendulum`` and ``invoiceflow.settings``;
each task imports the pipeline when it runs. Airflow reads the file again at the start of
every box, within 30 seconds; with the model using most of the Mac's memory, importing the
whole pipeline there took longer, and the boxes went to "up_for_reschedule" (2026-11-19).
"""

from __future__ import annotations

import logging

import pendulum
from airflow.sdk import dag, get_current_context, task, task_group

from invoiceflow.settings import company_timezone

log = logging.getLogger(__name__)

RUN_ID = "airflow-intake"
LABEL = "{{ invoice }}"  # each mapped box shows the file name, not [0], [1], ...
_READ_AS = {"PDF_TEXT": "text layer", "OCR": "OCR"}  # by TextSource value


def _invoice(data: dict[str, str]):
    from invoiceflow.pipeline.staged import StagedFile

    item = StagedFile.from_xcom(data)
    get_current_context()["invoice"] = item.name
    return item


def _pipeline():
    from invoiceflow.pipeline.steps import build_pipeline

    return build_pipeline()


def _store():
    from invoiceflow.settings import data_dir
    from invoiceflow.storage import LocalBlobStore

    return LocalBlobStore(data_dir())


@dag(
    dag_id="invoice_intake",
    schedule="*/5 * * * *",
    # Airflow reads the schedule in the start date's time zone: Kallang's, not UTC.
    start_date=pendulum.datetime(2026, 1, 1, tz=company_timezone()),
    catchup=False,
    max_active_runs=1,
    tags=["intake", "ws6"],
)
def invoice_intake():
    @task(task_id="register_files")
    def register() -> list[dict[str, str]]:
        from invoiceflow.pipeline.staged import register_inbox
        from invoiceflow.store.repo import repo_transaction

        conf = get_current_context()["dag_run"].conf or {}
        registered = register_inbox(
            transaction=repo_transaction,
            store=_store(),
            pipeline=_pipeline(),
            source=str(conf.get("source", "folder")),
        )
        for item in registered.files:
            log.info("registered %s", item.name)
        for name in registered.duplicates:
            log.info("%s: a byte-identical copy of an invoice already in; discarded", name)
        return [item.to_xcom() for item in registered.files]

    @task_group(group_id="invoice")
    def invoice(data: dict[str, str]):
        @task(task_id="parse", max_active_tis_per_dagrun=1, retries=1, map_index_template=LABEL)
        def parse(data: dict[str, str]) -> dict[str, str]:
            from invoiceflow.pipeline.staged import parse_file

            document = parse_file(_invoice(data), pipeline=_pipeline())
            for page in document.pages:
                hidden = sum(word.hidden for word in page.words)
                log.info(
                    "page %d: read from the %s, %d words%s",
                    page.page_no,
                    _READ_AS.get(page.source, page.source.value),
                    len(page.words),
                    f", {hidden} hidden kept out of the prompt" if hidden else "",
                )
            return data

        @task(task_id="extract", pool="llm", retries=2, map_index_template=LABEL)
        def extract(data: dict[str, str]) -> dict[str, str]:
            from invoiceflow.contracts import LLMMode
            from invoiceflow.pipeline.staged import extract_file

            result = extract_file(_invoice(data), pipeline=_pipeline())
            seconds = f"{result.latency_ms / 1000:.1f} s" if result.latency_ms else "no time"
            if result.mode is LLMMode.REPLAY:
                seconds = f"replayed at once; the recorded call took {seconds}"
            outcome = "valid output" if result.valid else f"invalid output: {result.error}"
            log.info("%s (%s): %s, %s", result.model, result.mode.value.lower(), outcome, seconds)
            return data

        @task(task_id="check", max_active_tis_per_dagrun=1, retries=1, map_index_template=LABEL)
        def check(data: dict[str, str]) -> dict[str, str]:
            from invoiceflow.pipeline.staged import check_file
            from invoiceflow.settings import singapore_today
            from invoiceflow.store.repo import repo_transaction

            item = _invoice(data)
            result = check_file(
                item,
                transaction=repo_transaction,
                store=_store(),
                pipeline=_pipeline(),
                today=singapore_today(),
                run_id=RUN_ID,
            )
            findings = result.process.findings if result.process else ()
            for finding in findings:
                log.info("%s %s: %s", finding.rule_id, finding.severity.value, finding.message)
            log.info("%s: %s", result.status.value, "see above" if findings else "no findings")
            return {"invoice": item.name, "status": result.status.value}

        check(extract(parse(data)))

    @task(task_id="summarize", trigger_rule="all_done")
    def summarize(files: list[dict[str, str]]) -> dict[str, int]:
        from invoiceflow.pipeline.staged import StagedFile, finish_run
        from invoiceflow.store.repo import repo_transaction

        counts = finish_run(
            [StagedFile.from_xcom(data) for data in files], transaction=repo_transaction
        )
        log.info("%d read: %s", len(files), counts or "the inbox was empty")
        return counts

    files = register()
    invoice.expand(data=files) >> summarize(files)


invoice_intake()
