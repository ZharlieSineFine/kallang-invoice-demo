"""Times from the database (UTC) are shown in the company's time zone, Singapore."""

from __future__ import annotations

from datetime import UTC, datetime

from test_pages import _run

from app.formatting import format_time
from app.pages import batches


def test_a_utc_time_is_shown_in_singapore_time():
    assert format_time(datetime(2026, 11, 17, 2, 37, 3, tzinfo=UTC)) == "2026-11-17 10:37:03 SGT"


def test_the_date_rolls_over_at_singapore_midnight():
    assert format_time(datetime(2026, 11, 17, 16, 30, tzinfo=UTC)) == "2026-11-18 00:30:00 SGT"


def test_no_time_is_a_dash():
    assert format_time(None) == "—"


def test_the_batches_page_shows_singapore_time(fake_backend):
    # The fake batch was created at 01:00 UTC.
    at = _run(batches, fake_backend)
    frame = at.dataframe[0].value
    assert frame["created"].tolist() == ["2026-11-04 09:00:00 SGT"]
