"""The weekly audit monitor (``audit_monitor`` DAG).

The same numbers as Demo Step 8, kept as a dated report every Monday, and marked when the
auto-pass error rate is above the limit in ``config/rules.yaml`` (2%, user 2026-11-19).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from invoiceflow.evaluate.audit_monitor import (
    AuditSummary,
    MonitorReport,
    error_limit_percent,
    write_report,
)
from invoiceflow.settings import load_config

MONDAY = datetime(2026, 11, 23, 8, 0, 5, tzinfo=ZoneInfo("Asia/Singapore"))
LIMIT = Decimal("2")


def _report(*, checked=0, with_error=0, fields=(), auto_passed=31, picked=3, limit=LIMIT):
    summary = AuditSummary(
        percent=Decimal("10"),
        picked=picked,
        checked=checked,
        with_error=with_error,
        error_fields=fields,
    )
    return MonitorReport(
        generated_at=MONDAY, auto_passed=auto_passed, summary=summary, limit_percent=limit
    )


def test_the_limit_comes_from_the_audit_config():
    assert error_limit_percent(load_config("rules")) == LIMIT
    assert error_limit_percent({}) is None


def test_too_few_checks_give_no_rate_and_no_warning():
    data = _report(checked=3).to_json()
    assert (data["auto_passed"], data["picked"], data["checked"], data["with_error"]) == (
        31,
        3,
        3,
        0,
    )
    assert data["error_rate_percent"] == "0.0"
    assert data["upper_bound_percent"] is None
    assert data["over_limit"] is False
    assert "Too few checked to estimate a rate yet (needs 30 or more)." in data["summary"]


def test_nothing_checked_yet_has_no_rate():
    assert _report(checked=0).to_json()["error_rate_percent"] is None


def test_thirty_clean_checks_give_the_rule_of_three_bound():
    data = _report(picked=40, checked=30).to_json()
    assert data["upper_bound_percent"] == "10.0"  # 0 errors in 30: below 3/30 at 95%
    assert data["over_limit"] is False


def test_an_error_rate_above_the_limit_is_marked():
    data = _report(picked=40, checked=30, with_error=1, fields=(("total", 1),)).to_json()
    assert data["error_rate_percent"] == "3.3"
    assert data["over_limit"] is True
    assert data["error_fields"] == {"total": 1}
    assert "Above the 2% limit" in data["summary"]


def test_exactly_the_limit_is_not_over_it():
    # 1 wrong in 50 is 2.0%: the user's rule is "more than 1 wrong in 50".
    data = _report(picked=60, checked=50, with_error=1, fields=(("total", 1),)).to_json()
    assert data["error_rate_percent"] == "2.0"
    assert data["over_limit"] is False


def test_no_limit_configured_never_warns():
    data = _report(checked=30, with_error=5, fields=(("total", 5),), limit=None).to_json()
    assert data["limit_percent"] is None and data["over_limit"] is False


def test_the_report_is_written_as_monitor_date_json(tmp_path):
    path = write_report(_report(checked=3), tmp_path)
    assert path == tmp_path / "monitor_2026-11-23.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["report"] == "audit_monitor"
    assert data["limit_percent"] == "2"
    write_report(_report(checked=4), tmp_path)  # a second run that day replaces it
    assert [p.name for p in tmp_path.iterdir()] == ["monitor_2026-11-23.json"]


def test_the_file_date_is_singapore_time(tmp_path):
    # 17:00 UTC on Sunday is 01:00 on Monday in Singapore.
    sunday_utc = datetime(2026, 11, 22, 17, 0, tzinfo=UTC)
    report = MonitorReport(
        generated_at=sunday_utc,
        auto_passed=0,
        summary=AuditSummary(percent=None),
        limit_percent=LIMIT,
    )
    assert write_report(report, tmp_path).name == "monitor_2026-11-23.json"


class _Repo:
    """The two Repo reads the report needs."""

    def audit_counts(self):
        return (3, 2, 1, (("total", 1),))

    def auto_passed_count(self):
        return 31


def test_the_report_is_built_from_the_repo_and_the_rules_config():
    from invoiceflow.evaluate.audit_monitor import monitor_report, read_summary

    report = monitor_report(_Repo(), load_config("rules"), MONDAY)
    assert report.auto_passed == 31
    assert report.summary == read_summary(_Repo(), Decimal("10"))
    assert (report.summary.picked, report.summary.checked, report.summary.with_error) == (3, 2, 1)
    assert report.limit_percent == LIMIT
    assert report.over_limit  # 1 of 2 checked is 50%
