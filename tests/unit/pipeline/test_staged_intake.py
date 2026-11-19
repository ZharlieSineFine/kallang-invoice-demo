"""invoice_intake with one Airflow box per stage (``pipeline.staged``).

Each stage runs as its own Airflow task, in its own process, so it may only use what the
earlier stage saved; these tests call the stages one by one with nothing passed in memory.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from test_steps import TODAY, FakeRepo, Transactions, _in_steps, _pipeline

from invoiceflow.contracts import DocStatus
from invoiceflow.pipeline import staged
from invoiceflow.pipeline.staged import (
    StagedFile,
    check_file,
    extract_file,
    finish_run,
    parse_file,
    register_inbox,
)
from invoiceflow.storage import LocalBlobStore


@dataclass
class _Setup:
    repo: FakeRepo
    transactions: Transactions
    store: LocalBlobStore
    pipeline: object
    inbox: Path
    processed: Path
    work: Path

    def register(self):
        return register_inbox(
            transaction=self.transactions,
            store=self.store,
            pipeline=self.pipeline,
            inbox=self.inbox,
            processed=self.processed,
        )

    def parse(self, item):
        return parse_file(item, pipeline=self.pipeline, work=self.work)

    def extract(self, item):
        return extract_file(item, pipeline=self.pipeline, work=self.work)

    def check(self, item):
        return check_file(
            item,
            transaction=self.transactions,
            store=self.store,
            pipeline=self.pipeline,
            today=TODAY,
            run_id="r",
            processed=self.processed,
            work=self.work,
        )

    def summarize(self, items):
        return finish_run(items, transaction=self.transactions, work=self.work)

    def run_all(self):
        """What one Airflow run does: every stage of every invoice, then the summary."""
        items = self.register().files
        for item in items:
            # A new StagedFile from its XCom dict, as the next task in a new process gets it.
            for stage in (self.parse, self.extract, self.check):
                stage(StagedFile.from_xcom(item.to_xcom()))
        return self.summarize(items)


def _setup(tmp_path, golden, *fixtures) -> _Setup:
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    for number, fixture in enumerate(fixtures):
        shutil.copy(fixture.pdf_path, inbox / f"{number}-{fixture.pdf_path.name}")
    repo = FakeRepo()
    return _Setup(
        repo=repo,
        transactions=Transactions(repo),
        store=LocalBlobStore(tmp_path / "data"),
        pipeline=_pipeline(golden),
        inbox=inbox,
        processed=tmp_path / "processed",
        work=tmp_path / "work",
    )


def test_register_saves_each_waiting_file_as_received_oldest_first(
    golden, clean, mismatch, tmp_path
):
    setup = _setup(tmp_path, golden, clean, mismatch)
    registered = setup.register()
    assert [item.name for item in registered.files] == [
        f"0-{clean.pdf_path.name}",
        f"1-{mismatch.pdf_path.name}",
    ]
    assert all(
        setup.repo.statuses[item.doc_uuid] is DocStatus.RECEIVED for item in registered.files
    )
    assert setup.repo.saved["parsed"] == []  # nothing read yet: the Queue shows them waiting
    assert len(list(setup.inbox.iterdir())) == 2  # files leave the inbox only once checked


def test_xcom_carries_only_ids_and_the_inbox_path(golden, clean, tmp_path):
    item = _setup(tmp_path, golden, clean).register().files[0]
    data = item.to_xcom()
    assert set(data) == {"doc_id", "file_id", "sha256", "path"}
    assert all(isinstance(value, str) for value in data.values())
    assert StagedFile.from_xcom(data) == item


def test_each_stage_reads_what_the_one_before_saved(golden, clean, tmp_path):
    setup = _setup(tmp_path, golden, clean)
    item = setup.register().files[0]
    setup.parse(item)
    assert (setup.work / item.doc_id / staged.PARSED).is_file()
    setup.extract(item)
    assert (setup.work / item.doc_id / staged.EXTRACTION).is_file()
    result = setup.check(item)
    assert result.status is DocStatus.AUTO_PASSED
    assert not (setup.work / item.doc_id).exists()  # the work files go once the outcome is saved
    assert not list(setup.inbox.iterdir())
    assert [path.name for path in setup.processed.iterdir()] == [item.name]


@pytest.mark.parametrize("fixture_name", ["clean", "mismatch"])
def test_the_staged_outcome_matches_the_one_step_intake(golden, tmp_path, request, fixture_name):
    fixture = request.getfixturevalue(fixture_name)
    setup = _setup(tmp_path / "staged", golden, fixture)
    setup.run_all()
    one_step_repo = FakeRepo()
    one_step = _in_steps(fixture.pdf_path, one_step_repo, tmp_path / "one-step", golden)

    assert list(setup.repo.statuses.values()) == [one_step.status]
    staged_rules = [f.rule_id for f in setup.repo.saved["findings"][0][2]]
    one_step_rules = [f.rule_id for f in one_step_repo.saved["findings"][0][2]]
    assert staged_rules == one_step_rules


def test_the_summary_counts_each_outcome(golden, clean, mismatch, tmp_path):
    counts = _setup(tmp_path, golden, clean, mismatch).run_all()
    assert counts == {"AUTO_PASSED": 1, "NEEDS_REVIEW": 1}


def test_a_byte_identical_copy_is_logged_and_moved_out_at_register(golden, clean, tmp_path):
    setup = _setup(tmp_path, golden, clean)
    shutil.copy(clean.pdf_path, setup.inbox / "9-copy.pdf")
    registered = setup.register()
    assert len(registered.files) == 1
    assert registered.duplicates == ("9-copy.pdf",)
    assert (setup.processed / "9-copy.pdf").is_file()
    assert any(event[1] == "intake.duplicate_file" for event in setup.repo.events)


def test_check_reads_earlier_invoices_when_it_runs_not_at_register(
    golden, clean, tmp_path, monkeypatch
):
    # Every file is registered before any is checked, so R05 must see the invoices saved by
    # earlier checks in the same run: the prior invoices are read at check time.
    setup = _setup(tmp_path, golden, clean)
    item = setup.register().files[0]
    setup.parse(item)
    setup.extract(item)
    earlier = ("saved by an earlier check",)
    monkeypatch.setattr(setup.repo, "prior_invoices", lambda vendor_id: earlier)
    seen = {}
    real = staged.check_stage

    def spy(**kwargs):
        seen["prior"] = kwargs["prior_invoices"]
        return real(**{**kwargs, "prior_invoices": ()})

    monkeypatch.setattr(staged, "check_stage", spy)
    setup.check(item)
    assert seen["prior"] == earlier


def test_a_stage_that_fails_leaves_its_file_for_the_next_run(golden, clean, tmp_path, monkeypatch):
    setup = _setup(tmp_path, golden, clean)

    def unavailable(document, deps):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(staged, "extract_stage", unavailable)
    item = setup.register().files[0]
    setup.parse(item)
    with pytest.raises(RuntimeError, match="model unavailable"):
        setup.extract(item)  # Airflow retries it, then gives up; summarize runs anyway
    counts = setup.summarize((item,))

    assert counts == {"failed": 1}
    assert setup.repo.documents == {}  # no "Processing…" card left behind
    failed = [event for event in setup.repo.events if event[1] == "intake.failed"]
    assert "extract: RuntimeError: model unavailable" in failed[0][3]["error"]
    assert [path.name for path in setup.inbox.iterdir()] == [item.name]
    assert not (setup.work / item.doc_id).exists()

    monkeypatch.undo()
    assert setup.run_all() == {"AUTO_PASSED": 1}  # the next run reads it again
