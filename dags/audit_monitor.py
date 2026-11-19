"""audit_monitor: the weekly report on the random audit of auto-passed invoices (CR-012).

Every Monday at 08:00 Singapore time, or by hand. It reads the audit results logged so far
(Demo Step 8 shows the same numbers live) and writes ``reports/monitor_<date>.json``:
auto-passed invoices, picked for audit, checked by a person, errors found, the error rate
(or its 95% upper limit once 30 are checked with no error), and the fields found wrong. The
report is marked ``over_limit`` when the rate is above ``audit.error_limit_percent`` in
``config/rules.yaml`` (2%), and the task log says so as a warning.

It replaces the ``evaluate`` placeholder, which only counted invoices per status. Accuracy
against the synthetic answer keys (the Dashboard) comes from ``make demo-data``; real invoices
have no answer keys, so in real use this report is how accuracy is watched.

Starting the stack after a missed Monday writes that week's report at once. It only reads, so
that is harmless (unlike ``sap_export``, which skips a late run).
"""

from __future__ import annotations

import logging

import pendulum
from airflow.sdk import dag, task

from invoiceflow.settings import company_timezone, load_config, repo_root

log = logging.getLogger(__name__)


@dag(
    dag_id="audit_monitor",
    schedule="0 8 * * 1",  # Mondays at 08:00, in the start date's time zone
    start_date=pendulum.datetime(2026, 1, 1, tz=company_timezone()),
    catchup=False,
    tags=["audit", "monitor"],
)
def audit_monitor():
    @task(task_id="write_report")
    def write() -> dict[str, str | int | bool]:
        # Imported here, not at the top: Airflow reads this file within 30 s at every start.
        from invoiceflow.evaluate.audit_monitor import monitor_report, write_report
        from invoiceflow.store.connection import connect
        from invoiceflow.store.repo import Repo

        with connect() as conn:
            report = monitor_report(
                Repo(conn), load_config("rules"), pendulum.now(company_timezone())
            )
        path = write_report(report, repo_root() / "reports")
        log.info("%s", report.text)
        if report.over_limit:
            log.warning(
                "The auto-pass error rate is above the %s%% limit; see %s",
                report.limit_percent,
                path.name,
            )
        return {
            "report": path.name,
            "checked": report.summary.checked,
            "with_error": report.summary.with_error,
            "over_limit": report.over_limit,
        }

    write()


audit_monitor()
