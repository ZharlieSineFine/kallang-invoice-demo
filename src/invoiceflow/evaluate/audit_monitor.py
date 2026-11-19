"""How often auto-passed invoices are wrong, from the random audit (CR-012).

Auto-passed invoices reach SAP without a person, so there is no answer key for them in real
use. A random share is picked for a person to check against the page; the share with an
error is the auto-pass error rate. Demo Step 8 shows these numbers live; the ``audit_monitor``
DAG writes them every Monday as ``reports/monitor_<date>.json`` and marks the report when the
rate is above ``audit.error_limit_percent`` in ``config/rules.yaml``.

Until 30 invoices are checked the rate says little: with no error found, the rule of three
gives an upper limit (0 errors in n checks means a rate below 3/n, at 95% confidence) only
from 30 checks on. An error found is always reported, since one is already worth a look.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from invoiceflow.rules.audit import AuditSample
from invoiceflow.settings import company_timezone

MIN_FOR_ESTIMATE = 30  # the rule of three needs about this many checks to say anything
CONFIDENCE_FACTOR = 3  # rule of three: 0 errors in n checks -> rate < 3/n at 95%
REPORT_NAME = "audit_monitor"
_ONE_DECIMAL = Decimal("0.1")


@dataclass(frozen=True)
class AuditSummary:
    """The random audit of auto-passed invoices, counted from the audit events."""

    percent: Decimal | None  # the configured share; None when no audit is configured
    picked: int = 0
    checked: int = 0
    with_error: int = 0
    error_fields: tuple[tuple[str, int], ...] = ()  # (field, audits that found it wrong)

    @property
    def error_rate_percent(self) -> Decimal | None:
        if not self.checked:
            return None
        return Decimal(100 * self.with_error) / self.checked

    @property
    def upper_bound_percent(self) -> Decimal | None:
        """With no error found in 30 or more checks: the 95% upper limit on the rate."""
        if self.with_error or self.checked < MIN_FOR_ESTIMATE:
            return None
        return Decimal(100 * CONFIDENCE_FACTOR) / self.checked


def counts_line(summary: AuditSummary) -> str:
    return (
        f"Picked: {summary.picked} · Checked by a person: {summary.checked} · "
        f"With an error: {summary.with_error}"
    )


def rate_line(summary: AuditSummary) -> str:
    rate = summary.error_rate_percent
    if summary.with_error and rate is not None:
        fields = ", ".join(f"{name} ({count})" for name, count in summary.error_fields)
        return (
            f"{summary.with_error} of {summary.checked} checked had an error ({rate:.1f}%). "
            f"Fields: {fields}."
        )
    bound = summary.upper_bound_percent
    if bound is None:
        return f"Too few checked to estimate a rate yet (needs {MIN_FOR_ESTIMATE} or more)."
    return f"With 95% confidence, fewer than {bound:.1f}% of auto-passed invoices have an error."


def error_limit_percent(rules_config: Mapping[str, Any] | None) -> Decimal | None:
    limit = ((rules_config or {}).get("audit") or {}).get("error_limit_percent")
    return None if limit is None else Decimal(str(limit))


@dataclass(frozen=True)
class MonitorReport:
    generated_at: datetime  # time zone aware
    auto_passed: int
    summary: AuditSummary
    limit_percent: Decimal | None

    @property
    def over_limit(self) -> bool:
        rate = self.summary.error_rate_percent
        return rate is not None and self.limit_percent is not None and rate > self.limit_percent

    @property
    def text(self) -> str:
        parts = [f"{counts_line(self.summary)}.", rate_line(self.summary)]
        if self.over_limit:
            parts.append(
                f"Above the {self.limit_percent:g}% limit: review the auto-pass rules, such as "
                "the value limit or which vendors may auto-pass."
            )
        return " ".join(parts)

    def to_json(self) -> dict[str, Any]:
        summary = self.summary
        return {
            "report": REPORT_NAME,
            "generated_at": self.generated_at.isoformat(timespec="seconds"),
            "sample_percent": _text(summary.percent),
            "auto_passed": self.auto_passed,
            "picked": summary.picked,
            "checked": summary.checked,
            "with_error": summary.with_error,
            "error_rate_percent": _one_decimal(summary.error_rate_percent),
            "upper_bound_percent": _one_decimal(summary.upper_bound_percent),
            "min_checks_for_estimate": MIN_FOR_ESTIMATE,
            "limit_percent": _text(self.limit_percent),
            "over_limit": self.over_limit,
            "error_fields": dict(summary.error_fields),
            "summary": self.text,
        }


class AuditCounts(Protocol):
    """The reads the report needs; ``store.repo.Repo`` provides them."""

    def audit_counts(self) -> tuple[int, int, int, tuple[tuple[str, int], ...]]: ...

    def auto_passed_count(self) -> int: ...


def read_summary(repo: AuditCounts, percent: Decimal | None) -> AuditSummary:
    picked, checked, with_error, fields = repo.audit_counts()
    return AuditSummary(
        percent=percent,
        picked=picked,
        checked=checked,
        with_error=with_error,
        error_fields=fields,
    )


def monitor_report(
    repo: AuditCounts, rules_config: Mapping[str, Any], now: datetime
) -> MonitorReport:
    sample = AuditSample.from_config(rules_config)
    return MonitorReport(
        generated_at=now,
        auto_passed=repo.auto_passed_count(),
        summary=read_summary(repo, sample.percent if sample else None),
        limit_percent=error_limit_percent(rules_config),
    )


def write_report(report: MonitorReport, directory: Path) -> Path:
    """``monitor_<date>.json``, dated in Kallang's time zone; a second run that day replaces it."""
    local_date = report.generated_at.astimezone(ZoneInfo(company_timezone())).date()
    path = directory / f"monitor_{local_date.isoformat()}.json"
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_json(), indent=2) + "\n", encoding="utf-8")
    return path


def _one_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(_ONE_DECIMAL))


def _text(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:g}"
