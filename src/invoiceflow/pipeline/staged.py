"""invoice_intake with one Airflow box per stage: register, parse, extract, check, summarize.

``intake_in_steps`` runs every stage in one process (the light setup's Upload page and
``make intake-local``). Airflow runs each stage as its own task, in its own process, so a stage
hands the next one its result in files under ``data/work/<doc_id>/``; XCom carries only IDs
and the inbox path (:class:`StagedFile`). The stage functions are the same ones
(``parse_stage``, ``extract_stage``, ``check_stage``, ``_save_outcome``), so the outcome is the
one ``intake_in_steps`` gives.

- register: each waiting file, oldest first, is saved with a RECEIVED document, so the Queue
  shows it at once. A byte-identical copy is logged and moved out. Files stay in the inbox
  until they are checked.
- parse, then extract: save ``parsed.json``, then ``extraction.json``.
- check: reads the earlier invoices when it runs (every file is registered before any is
  checked, so R05 must see what earlier checks in the same run saved), saves the outcome,
  moves the file out, and removes the work files.
- summarize: counts the outcomes. A document still RECEIVED failed a stage after its retries:
  it is removed, so no "Processing…" card is left, and its file, still in the inbox, is read
  again by the next run, as ``intake_in_steps`` does.
"""

from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from invoiceflow.contracts import DocStatus, ExtractionResult, ParsedDocument
from invoiceflow.pipeline.stages import (
    ProcessResult,
    check_stage,
    extract_stage,
    parse_stage,
    sha256_file,
)
from invoiceflow.pipeline.steps import (
    ACTOR,
    IntakeResult,
    Pipeline,
    Received,
    _save_outcome,
    inbox_dir,
    list_inbox,
    move_processed,
    receive_document,
)
from invoiceflow.settings import data_dir
from invoiceflow.storage import LocalBlobStore

PARSED = "parsed.json"
EXTRACTION = "extraction.json"
ERROR = "error.txt"
FAILED = "failed"  # summary count for invoices whose stage failed after its retries
_NO_ERROR_SAVED = "a stage failed; the Airflow task log shows why"

Transaction = Callable[[], AbstractContextManager[Any]]


@dataclass(frozen=True)
class StagedFile:
    """One registered invoice, as XCom carries it between the stage tasks."""

    doc_id: str
    file_id: str
    sha256: str
    path: str  # the file in the inbox

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def doc_uuid(self) -> UUID:
        return UUID(self.doc_id)

    @property
    def file_uuid(self) -> UUID:
        return UUID(self.file_id)

    def to_xcom(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_xcom(cls, data: Mapping[str, str]) -> StagedFile:
        return cls(**{key: str(data[key]) for key in ("doc_id", "file_id", "sha256", "path")})


@dataclass(frozen=True)
class Registered:
    files: tuple[StagedFile, ...]
    duplicates: tuple[str, ...] = ()  # names of byte-identical copies, moved out


def work_root() -> Path:
    return data_dir() / "work"


def register_inbox(
    *,
    transaction: Transaction,
    store: LocalBlobStore,
    pipeline: Pipeline,
    inbox: Path | None = None,
    processed: Path | None = None,
    source: str = "folder",
) -> Registered:
    files: list[StagedFile] = []
    duplicates: list[str] = []
    for path in list_inbox(inbox if inbox is not None else inbox_dir()):
        sha256 = sha256_file(path)
        if any(item.sha256 == sha256 for item in files):
            # A copy of a file registered moments ago in this run: its document is still
            # RECEIVED, which receive_document would take for a crashed run to resume.
            with transaction() as repo:
                payload = {"sha256": sha256, "name": path.name}
                repo.log_event(ACTOR, "intake.duplicate_file", None, payload)
            received = None
        else:
            with transaction() as repo:
                received = receive_document(
                    path, repo=repo, store=store, pipeline=pipeline, source=source
                )
        if received is None or received.duplicate:
            move_processed(path, processed)
            duplicates.append(path.name)
            continue
        files.append(
            StagedFile(str(received.doc_id), str(received.file_id), received.sha256, str(path))
        )
    return Registered(tuple(files), tuple(duplicates))


def parse_file(item: StagedFile, *, pipeline: Pipeline, work: Path | None = None) -> ParsedDocument:
    with _recorded(item, "parse", work):
        document = parse_stage(
            Path(item.path), file_id=item.file_uuid, doc_id=item.doc_uuid, deps=pipeline.deps
        )
        _save(item, PARSED, document, work)
    return document


def extract_file(
    item: StagedFile, *, pipeline: Pipeline, work: Path | None = None
) -> ExtractionResult:
    with _recorded(item, "extract", work):
        document = _load(item, PARSED, ParsedDocument, work)
        extraction = extract_stage(document, pipeline.deps)
        _save(item, EXTRACTION, extraction, work)
    return extraction


def check_file(
    item: StagedFile,
    *,
    transaction: Transaction,
    store: LocalBlobStore,
    pipeline: Pipeline,
    today: date,
    run_id: str,
    processed: Path | None = None,
    work: Path | None = None,
) -> IntakeResult:
    with _recorded(item, "check", work):
        document = _load(item, PARSED, ParsedDocument, work)
        extraction = _load(item, EXTRACTION, ExtractionResult, work)
        with transaction() as repo:
            prior = repo.prior_invoices(None)
            outcome = check_stage(
                document=document,
                extraction=extraction,
                master=pipeline.master,
                file_sha256=item.sha256,
                deps=pipeline.deps,
                today=today,
                run_id=run_id,
                rules_config=pipeline.rules_config,
                prior_invoices=prior,
            )
            result = ProcessResult(
                file_sha256=item.sha256,
                document=document,
                extraction=extraction,
                context=outcome.context,
                findings=outcome.findings,
                decision=outcome.decision,
            )
            received = Received(Path(item.path), item.doc_uuid, item.file_uuid, item.sha256, prior)
            intake = _save_outcome(repo, store, received, result, run_id)
    move_processed(Path(item.path), processed)
    shutil.rmtree(_work_dir(item, work), ignore_errors=True)
    return intake


def finish_run(
    items: Sequence[StagedFile], *, transaction: Transaction, work: Path | None = None
) -> dict[str, int]:
    """Count the outcomes, and remove the placeholder of every invoice that failed a stage."""
    counts: Counter[str] = Counter()
    with transaction() as repo:
        for item in items:
            record = repo.get_document(item.doc_uuid)
            if record is not None and record.status is not DocStatus.RECEIVED:
                counts[record.status.value] += 1
                continue
            counts[FAILED] += 1
            if record is not None:
                repo.discard_document(item.doc_uuid, item.file_uuid)
                payload = {"sha256": item.sha256, "name": item.name, "error": _error(item, work)}
                repo.log_event(ACTOR, "intake.failed", item.doc_uuid, payload)
            shutil.rmtree(_work_dir(item, work), ignore_errors=True)
    return dict(counts)


def _work_dir(item: StagedFile, work: Path | None) -> Path:
    return (work if work is not None else work_root()) / item.doc_id


def _save(item: StagedFile, name: str, model: BaseModel, work: Path | None) -> None:
    folder = _work_dir(item, work)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(model.model_dump_json(), encoding="utf-8")


def _load[M: BaseModel](item: StagedFile, name: str, model: type[M], work: Path | None) -> M:
    return model.model_validate_json((_work_dir(item, work) / name).read_text(encoding="utf-8"))


def _error(item: StagedFile, work: Path | None) -> str:
    path = _work_dir(item, work) / ERROR
    return path.read_text(encoding="utf-8") if path.is_file() else _NO_ERROR_SAVED


@contextmanager
def _recorded(item: StagedFile, stage: str, work: Path | None) -> Iterator[None]:
    """Keep the last error of a stage, so summarize can log why the invoice failed."""
    try:
        yield
    except Exception as error:
        folder = _work_dir(item, work)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ERROR).write_text(f"{stage}: {type(error).__name__}: {error}", encoding="utf-8")
        raise
