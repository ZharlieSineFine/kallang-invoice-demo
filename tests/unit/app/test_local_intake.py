"""Reading data/inbox inside the review app when Airflow is not running (the light setup)."""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass

import pytest

from app.local_intake import InboxProgress, InboxReader, child_process_drain, summary
from invoiceflow.contracts import DocStatus
from invoiceflow.pipeline.steps import drain_inbox


@dataclass(frozen=True)
class _Result:
    status: DocStatus
    skipped: bool = False


def _reader(tmp_path, process):
    """The reader with the child process replaced by the same steps run in this process."""
    inbox, processed = tmp_path / "inbox", tmp_path / "processed"
    inbox.mkdir()

    def drain(on_start, on_done):
        def one(path):
            on_start(path.name)
            result = process(path)
            on_done(path.name, "skipped" if result.skipped else result.status.value)

        drain_inbox(one, inbox, processed)

    return InboxReader(drain, inbox=inbox), inbox, processed


def test_it_reads_every_waiting_file_and_moves_it_out(tmp_path):
    reader, inbox, processed = _reader(tmp_path, lambda path: _Result(DocStatus.AUTO_PASSED))
    for name in ("a.pdf", "b.pdf"):
        (inbox / name).write_bytes(b"x")
    assert reader.start()
    reader.wait(5)
    progress = reader.progress()
    assert not progress.running and progress.error is None
    assert progress.done == (("a.pdf", "AUTO_PASSED"), ("b.pdf", "AUTO_PASSED"))
    assert not list(inbox.iterdir())
    assert sorted(p.name for p in processed.iterdir()) == ["a.pdf", "b.pdf"]


def test_only_one_run_at_a_time_and_a_file_dropped_mid_run_is_read(tmp_path):
    release = threading.Event()
    seen = []

    def slow(path):
        seen.append(path.name)
        release.wait(5)
        return _Result(DocStatus.NEEDS_REVIEW)

    reader, inbox, _ = _reader(tmp_path, slow)
    (inbox / "a.pdf").write_bytes(b"x")
    assert reader.start()
    (inbox / "b.pdf").write_bytes(b"y")  # uploaded while a.pdf is being read
    assert reader.start() is False
    release.set()
    reader.wait(5)
    assert seen == ["a.pdf", "b.pdf"]
    assert not reader.progress().running


def test_an_error_stops_the_run_and_leaves_the_file_waiting(tmp_path):
    def broken(path):
        raise LookupError("model unavailable")

    reader, inbox, _ = _reader(tmp_path, broken)
    (inbox / "a.pdf").write_bytes(b"x")
    reader.start()
    reader.wait(5)
    progress = reader.progress()
    assert progress.error == "LookupError: model unavailable"
    assert not progress.running
    assert (inbox / "a.pdf").is_file()


def test_an_empty_inbox_finishes_at_once(tmp_path):
    reader, _, _ = _reader(tmp_path, lambda path: _Result(DocStatus.AUTO_PASSED))
    assert reader.start()
    reader.wait(5)
    assert reader.progress() == InboxProgress(running=False)


def test_the_summary_counts_outcomes_in_plain_words():
    progress = InboxProgress(
        done=(
            ("a", "AUTO_PASSED"),
            ("b", "AUTO_PASSED"),
            ("c", "NEEDS_REVIEW"),
            ("d", "ON_HOLD"),
            ("e", "skipped"),
        )
    )
    assert summary(progress) == "5 read · 2 passed · 1 needs a person · 1 on hold · 1 seen before"


_CHILD = """
import json
print(json.dumps({"event": "start", "file": "a.pdf", "outcome": None}))
print("a stray library warning")
print(json.dumps({"event": "done", "file": "a.pdf", "outcome": "AUTO_PASSED"}))
"""


def test_the_child_process_reports_each_file():
    events = []
    child_process_drain([sys.executable, "-c", _CHILD])(
        lambda name: events.append(("start", name)),
        lambda name, outcome: events.append(("done", name, outcome)),
    )
    assert events == [("start", "a.pdf"), ("done", "a.pdf", "AUTO_PASSED")]


def test_a_failed_child_process_is_reported():
    with pytest.raises(RuntimeError, match="exit 3"):
        child_process_drain([sys.executable, "-c", "raise SystemExit(3)"])(
            lambda name: None, lambda name, outcome: None
        )
