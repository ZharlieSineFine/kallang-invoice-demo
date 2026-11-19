"""Tell a scheduled run that started on time from one Airflow started late.

With catchup off, Airflow still treats the most recent missed slot as due: start the stack the
morning after an 18:00 it was off for, and ``sap_export`` runs at once and exports every ready
invoice. The export task asks :func:`missed_slot` first and skips such a run (user's choice,
2026-11-18), so starting the stack never exports. Runs started by hand are never skipped.
"""

from __future__ import annotations

from datetime import datetime, timedelta

LATE_AFTER = timedelta(minutes=30)  # a scheduled run starting later than this is a catch-up
SCHEDULED = "scheduled"  # Airflow's DagRunType.SCHEDULED value


def missed_slot(
    run_type: str, slot: datetime, now: datetime, late_after: timedelta = LATE_AFTER
) -> bool:
    """True for a scheduled run that starts more than ``late_after`` after its slot."""
    return run_type == SCHEDULED and now - slot > late_after
