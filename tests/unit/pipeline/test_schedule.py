"""A scheduled export that starts long after its 18:00 slot is a catch-up, not the slot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from invoiceflow.pipeline.schedule import LATE_AFTER, missed_slot

SLOT = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)  # 18:00 in Singapore


def test_a_scheduled_run_on_time_is_the_slot():
    assert not missed_slot("scheduled", SLOT, SLOT + timedelta(seconds=40))


def test_a_scheduled_run_just_inside_the_window_still_counts():
    assert not missed_slot("scheduled", SLOT, SLOT + LATE_AFTER)


def test_a_scheduled_run_started_the_next_morning_is_a_missed_slot():
    # Airflow was off at 18:00; `make up` the next morning starts that slot at once.
    assert missed_slot("scheduled", SLOT, SLOT + timedelta(hours=15))


def test_a_run_someone_started_by_hand_is_never_skipped():
    assert not missed_slot("manual", SLOT, SLOT + timedelta(days=3))


def test_the_run_type_enum_airflow_hands_a_task_also_counts():
    # Inside a task, dag_run.run_type is a (str, Enum) whose str() is "DagRunType.SCHEDULED".
    # The DAG must pass the enum itself: passing str() of it let a 16-hour-late export run
    # (seen 2026-11-19). The enum compares equal to its value, so it counts.
    from enum import Enum

    class DagRunType(str, Enum):  # noqa: UP042 - the same shape as Airflow's own class
        SCHEDULED = "scheduled"
        MANUAL = "manual"

    assert missed_slot(DagRunType.SCHEDULED, SLOT, SLOT + timedelta(hours=16))
    assert not missed_slot(DagRunType.MANUAL, SLOT, SLOT + timedelta(hours=16))
