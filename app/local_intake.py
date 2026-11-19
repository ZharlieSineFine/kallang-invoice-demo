"""Read data/inbox from the review app when Airflow is not running (the light setup).

The Upload page starts a run as soon as files are saved. One run at a time; it keeps going
until the inbox is empty, so files dropped mid-run are read too. The reading itself happens
in a child process (``python -m invoiceflow.pipeline.local_intake``, the steps
``make intake-local`` runs): PDF rendering (pdfium) is not thread-safe, so it must never run
beside the app's own page rendering in one process. A thread here only waits for the child
and turns its JSON lines into progress.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import streamlit as st

from invoiceflow.pipeline.steps import list_inbox
from invoiceflow.settings import repo_root

SKIPPED = "skipped"
CHILD_COMMAND = (sys.executable, "-m", "invoiceflow.pipeline.local_intake")
# (one, several) for each outcome, in the order the summary lists them.
_OUTCOME_WORDS = {
    "AUTO_PASSED": ("passed", "passed"),
    "NEEDS_REVIEW": ("needs a person", "need a person"),
    "MANUAL_ENTRY": ("needs a person", "need a person"),
    "ON_HOLD": ("on hold", "on hold"),
    "NOT_INVOICE": ("not an invoice", "not invoices"),
    SKIPPED: ("seen before", "seen before"),
}

OnStart = Callable[[str], None]
OnDone = Callable[[str, str], None]
Drain = Callable[[OnStart, OnDone], None]  # reads everything waiting once


@dataclass(frozen=True)
class InboxProgress:
    running: bool = False
    done: tuple[tuple[str, str], ...] = ()  # (file name, status or "skipped"), in read order
    current: str | None = None
    error: str | None = None


def summary(progress: InboxProgress) -> str:
    counts: Counter[tuple[str, str]] = Counter()
    for _, outcome in progress.done:
        counts[_OUTCOME_WORDS.get(outcome, (outcome.lower(), outcome.lower()))] += 1
    parts = [f"{len(progress.done)} read"]
    for words in dict.fromkeys(_OUTCOME_WORDS.values()):
        if counts[words]:
            parts.append(f"{counts[words]} {words[0] if counts[words] == 1 else words[1]}")
    return " · ".join(parts)


def child_process_drain(command: Sequence[str] = CHILD_COMMAND) -> Drain:
    """Run the intake child once and report each file it starts and finishes."""

    def drain(on_start: OnStart, on_done: OnDone) -> None:
        with subprocess.Popen(
            list(command), stdout=subprocess.PIPE, text=True, cwd=repo_root()
        ) as child:
            assert child.stdout is not None
            for line in child.stdout:
                if not line.startswith("{"):
                    continue  # a library's own output; errors go to the terminal (stderr)
                event = json.loads(line)
                if event["event"] == "start":
                    on_start(event["file"])
                elif event["event"] == "done":
                    on_done(event["file"], event["outcome"])
            code = child.wait()
        if code != 0:
            raise RuntimeError(
                f"intake stopped (exit {code}); the terminal running the app shows why"
            )

    return drain


class InboxReader:
    """One background run at a time that reads the inbox until it is empty."""

    def __init__(self, drain: Drain, *, inbox: Path | None = None) -> None:
        self._drain = drain
        self._inbox = inbox
        self._lock = threading.Lock()
        self._progress = InboxProgress()
        self._thread: threading.Thread | None = None

    def progress(self) -> InboxProgress:
        with self._lock:
            return self._progress

    def start(self) -> bool:
        """Start a run; False when one is already running (it will read new files too)."""
        with self._lock:
            if self._progress.running:
                return False
            self._progress = InboxProgress(running=True)
        self._thread = threading.Thread(target=self._run, name="inbox-reader", daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _update(self, **changes: Any) -> None:
        with self._lock:
            self._progress = replace(self._progress, **changes)

    def _started(self, name: str) -> None:
        self._update(current=name)

    def _finished(self, name: str, outcome: str) -> None:
        with self._lock:
            done = (*self._progress.done, (name, outcome))
            self._progress = replace(self._progress, done=done, current=None)

    def _run(self) -> None:
        try:
            while True:
                # Checked under the lock, so a file saved before start() returns False is
                # always seen by this run.
                with self._lock:
                    if not list_inbox(self._inbox):
                        self._progress = replace(self._progress, running=False, current=None)
                        return
                self._drain(self._started, self._finished)
        except Exception as exc:  # shown on the Upload page; the file stays in the inbox
            self._update(running=False, current=None, error=f"{type(exc).__name__}: {exc}")


@st.cache_resource
def inbox_reader() -> InboxReader:
    """The app's one reader, shared by every browser tab."""
    return InboxReader(child_process_drain())
