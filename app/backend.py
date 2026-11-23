"""The review actions and the read API the pages use.

``PostgresBackend`` is the only class that touches the database. It reads through
``app/queries.py`` and writes through the temporary ``app/repo.py`` adapter. A future
``store.repo`` implementation can replace ``repo`` without changing a page.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg import Connection

from app import queries, repo
from app.coding_refresh import coding_changed, keep_reviewer_choices
from app.evaluation import latest_evaluation
from app.fields import printed_value
from app.formatting import RATE_FIELDS, display_value, normalize_field_value
from app.models import (
    PROCESSING_STATUSES,
    AuditSummary,
    BatchSummary,
    CodingRow,
    DeleteOutcome,
    DiscardedCopy,
    DocumentBundle,
    DocumentSummary,
    ExportedInvoice,
    FindingRow,
    ReviewOutcome,
    TraceData,
)
from app.recheck import RecheckInput, accepted_fields, carried_findings, recheck
from invoiceflow.contracts import (
    HEADER_FIELDS,
    CodingLine,
    CodingSource,
    Confidence,
    DocStatus,
    Finding,
    MasterData,
    MatchType,
    NormalizedLineItem,
    Review,
    ReviewAction,
    Severity,
    ValueSource,
)
from invoiceflow.rules.audit import AuditSample
from invoiceflow.settings import load_config


class Backend(Protocol):
    """Everything the six pages need from storage."""

    def list_documents(self, statuses: Sequence[DocStatus] = ()) -> tuple[DocumentSummary, ...]: ...

    def document(self, doc_id: UUID) -> DocumentBundle | None: ...

    def master(self) -> MasterData: ...

    def confirm(self, doc_id: UUID, field: str, reviewer: str) -> ReviewOutcome: ...

    def correct(self, doc_id: UUID, field: str, raw_value: str, reviewer: str) -> ReviewOutcome: ...

    def edit_line_items(
        self, doc_id: UUID, items: Sequence[NormalizedLineItem], reviewer: str
    ) -> ReviewOutcome: ...

    def recode(
        self, doc_id: UUID, updates: Sequence[CodingUpdate], reviewer: str
    ) -> ReviewOutcome: ...

    def approve(self, doc_id: UUID, reviewer: str, comment: str | None = None) -> ReviewOutcome: ...

    def reject(self, doc_id: UUID, reviewer: str, comment: str | None = None) -> ReviewOutcome: ...

    def release_hold(self, doc_id: UUID, reviewer: str, comment: str) -> ReviewOutcome: ...

    def trace(self, doc_id: UUID) -> TraceData | None: ...

    def dashboard(self): ...

    def batches(self) -> tuple[BatchSummary, ...]: ...

    def export_status(self) -> dict[str, int]: ...

    def discarded_duplicates(self) -> int: ...

    def discarded_copies(self) -> tuple[DiscardedCopy, ...]: ...

    def export_history(self) -> tuple[ExportedInvoice, ...]: ...

    def run_export(self, resend: Sequence[UUID] = ()) -> ExportOutcome: ...

    def audit_summary(self) -> AuditSummary: ...

    def record_audit(
        self, doc_id: UUID, reviewer: str, found_error: bool, fields: Sequence[str] = ()
    ) -> AuditOutcome: ...

    def delete_documents(self, doc_ids: Sequence[UUID], reviewer: str) -> DeleteOutcome: ...


@dataclass(frozen=True)
class AuditOutcome:
    message: str


_AUDIT_MESSAGES = {
    "passed": "Audit recorded: every field matched the page.",
    "error": "Audit recorded: the error counts toward the auto-pass error rate.",
}


@dataclass(frozen=True)
class ExportOutcome:
    """What one run of the SAP export wrote. ``problems`` names invoices held back."""

    batch_id: str
    invoices: int
    row_count: int
    problems: tuple[str, ...] = ()
    resent: tuple[str, ...] = ()  # invoice numbers of the ones sent to SAP before

    @property
    def blocked(self) -> bool:
        return bool(self.problems) or self.invoices == 0

    @property
    def resent_note(self) -> str:
        """Which of them SAP already had, e.g. "1 was sent before: SAV-2026-0412"."""
        if not self.resent:
            return ""
        verb = "was" if len(self.resent) == 1 else "were"
        return f"{len(self.resent)} {verb} sent before: {', '.join(self.resent)}."

    @property
    def message(self) -> str:
        if self.invoices == 0:
            written = f"Nothing new to export: batch {self.batch_id} has no rows."
        else:
            noun = "invoice" if self.invoices == 1 else "invoices"
            written = (
                f"Exported {self.invoices} {noun} ({self.row_count} CSV rows) in batch "
                f"{self.batch_id}."
            )
            if self.resent:
                written = f"{written} {self.resent_note}"
        if not self.problems:
            return written
        return f"{written} Held back: " + "; ".join(self.problems)


@dataclass(frozen=True)
class CodingUpdate:
    line_no: int
    gl_account: str | None
    cost_center: str | None
    tax_code: str | None


_AWAITING_APPROVAL = "checks clear after a reviewer's change; waiting for approval"

_APPROVABLE = frozenset(
    {
        DocStatus.AUTO_PASSED,
        DocStatus.NEEDS_REVIEW,
        DocStatus.ON_HOLD,
        DocStatus.MANUAL_ENTRY,
        DocStatus.APPROVED,
    }
)


def _finding_row(finding: Finding, run_id: str | None = None) -> FindingRow:
    return FindingRow(
        rule_id=finding.rule_id,
        field=finding.field,
        severity=finding.severity,
        scope=finding.scope,
        message=finding.message,
        evidence=dict(finding.evidence),
        stage=finding.stage,
        run_id=run_id,
    )


class PostgresBackend:
    """Concrete backend. Pass a connection in tests to keep everything in one transaction."""

    def __init__(
        self,
        conn: Connection | None = None,
        *,
        rules_config: dict[str, Any] | None = None,
        reports_dir=None,
        files_root: Path | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._conn = conn
        self._rules_config = rules_config or load_config("rules")
        self._reports_dir = reports_dir
        # Where Delete removes files: data/ and the recorded model answers, unless a test
        # passes scratch folders.
        self._files_root = files_root
        self._cache_dir = cache_dir

    # ------------------------------------------------------------------ plumbing
    @contextmanager
    def _read(self) -> Iterator[Connection]:
        if self._conn is not None:
            yield self._conn
            return
        from invoiceflow.devdb.connection import connect

        with connect() as conn:
            yield conn

    @contextmanager
    def _write(self) -> Iterator[Connection]:
        if self._conn is not None:
            with self._conn.transaction():
                yield self._conn
            return
        from invoiceflow.devdb.connection import connect

        with connect() as conn, conn.transaction():
            yield conn

    # -------------------------------------------------------------------- reads
    def list_documents(self, statuses: Sequence[DocStatus] = ()) -> tuple[DocumentSummary, ...]:
        with self._read() as conn:
            return queries.list_documents(conn, statuses)

    def document(self, doc_id: UUID) -> DocumentBundle | None:
        with self._read() as conn:
            return queries.document_bundle(conn, doc_id)

    def master(self) -> MasterData:
        with self._read() as conn:
            return queries.master_data(conn)

    def trace(self, doc_id: UUID) -> TraceData | None:
        with self._read() as conn:
            return queries.trace(conn, doc_id)

    def dashboard(self):
        with self._read() as conn:
            return queries.dashboard(conn, latest_evaluation(reports_dir=self._reports_dir))

    def batches(self) -> tuple[BatchSummary, ...]:
        with self._read() as conn:
            return queries.batches(conn)

    def export_status(self) -> dict[str, int]:
        with self._read() as conn:
            return queries.export_status(conn)

    def discarded_duplicates(self) -> int:
        with self._read() as conn:
            return queries.discarded_duplicates(conn)

    def discarded_copies(self) -> tuple[DiscardedCopy, ...]:
        with self._read() as conn:
            return queries.discarded_copies(conn)

    def export_history(self) -> tuple[ExportedInvoice, ...]:
        with self._read() as conn:
            return queries.export_history(conn)

    def audit_summary(self) -> AuditSummary:
        sample = AuditSample.from_config(self._rules_config)
        with self._read() as conn:
            return queries.audit_summary(conn, sample.percent if sample else None)

    def record_audit(
        self, doc_id: UUID, reviewer: str, found_error: bool, fields: Sequence[str] = ()
    ) -> AuditOutcome:
        """CR-012: a person's check of an invoice picked for the random audit. It is saved
        in the history only; the invoice's status and export do not change."""
        chosen = list(dict.fromkeys(fields))
        if found_error and not chosen:
            raise ValueError("Choose the fields that were wrong, then record the error.")
        result = "error" if found_error else "passed"
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            if not bundle.document.is_audit_sample:
                raise ValueError("This invoice was not picked for the random audit.")
            payload = {"result": result, "fields": chosen}
            repo.log_event(conn, reviewer, "audit.completed", doc_id, payload)
        return AuditOutcome(_AUDIT_MESSAGES[result])

    def delete_documents(self, doc_ids: Sequence[UUID], reviewer: str) -> DeleteOutcome:
        """The Queue's Delete: the documents, their files and recorded answers go; the log
        keeps a ``document.deleted`` event each. An exported invoice's SAP batch stays."""
        from invoiceflow.extract import load_model_config
        from invoiceflow.settings import data_dir
        from invoiceflow.store.delete import apply_delete, plan_delete, remove_deleted_files

        with self._write() as conn:
            plan = plan_delete(conn, doc_ids)
            if not plan:
                raise LookupError("Those documents are already gone.")
            busy = [item.label for item in plan if item.status in PROCESSING_STATUSES]
            if busy:
                raise ValueError(
                    f"{', '.join(busy)} is still being read. Delete it once it has an outcome."
                )
            apply_delete(conn, plan, actor=reviewer)
        remove_deleted_files(
            plan,
            data_root=self._files_root or data_dir(),
            cache_dir=self._cache_dir or load_model_config().cache_dir,
        )
        return DeleteOutcome(
            deleted=tuple(item.label for item in plan),
            exported=sum(item.was_exported for item in plan),
        )

    def run_export(self, resend: Sequence[UUID] = ()) -> ExportOutcome:
        """The same export the Airflow ``sap_export`` DAG runs, from the app.

        ``resend``: invoices sent before that the person ticked to send again (2026-11-20).
        """
        from invoiceflow.pipeline.steps import export_approved
        from invoiceflow.settings import data_dir
        from invoiceflow.storage import LocalBlobStore
        from invoiceflow.store.repo import Repo

        with self._write() as conn:
            summary = export_approved(
                repo=Repo(conn), store=LocalBlobStore(data_dir()), resend=tuple(resend)
            )
            names = {item.doc_id: item.label for item in queries.export_history(conn)}
        return ExportOutcome(
            batch_id=summary.batch.batch_id,
            invoices=len(summary.doc_ids),
            row_count=summary.batch.row_count,
            problems=summary.problems,
            resent=tuple(names.get(doc_id, str(doc_id)) for doc_id in summary.resent),
        )

    # ------------------------------------------------------------------- writes
    def _review(
        self,
        conn: Connection,
        *,
        doc_id: UUID,
        reviewer: str,
        action: ReviewAction,
        field: str | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
        comment: str | None = None,
    ) -> None:
        repo.add_review(
            conn,
            Review(
                doc_id=doc_id,
                reviewer=reviewer.strip() or "demo.reviewer",
                action=action,
                field=field,
                old_value=old_value,
                new_value=new_value,
                comment=comment,
                created_at=repo.now(),
            ),
        )

    def _rerun(
        self,
        conn: Connection,
        doc_id: UUID,
        reviewer: str,
        *,
        resolved_fields: frozenset[str] = frozenset(),
        release_holds: bool = False,
    ) -> ReviewOutcome:
        bundle = queries.document_bundle(conn, doc_id)
        if bundle is None:
            raise LookupError(f"document {doc_id} not found")
        state = RecheckInput.from_bundle(bundle, self._rules_config)
        carried = carried_findings(
            bundle.findings, resolved_fields=resolved_fields, release_holds=release_holds
        )
        result = recheck(state, carried=carried, accepted=accepted_fields(bundle.reviews))
        # A person changed this invoice, so a clean recheck waits for their approval. Only an
        # invoice nobody touched may pass, and reach the export, on its own.
        is_clean = result.status is DocStatus.AUTO_PASSED
        status = DocStatus.NEEDS_REVIEW if is_clean else result.status
        run_id = f"review-{uuid4().hex[:12]}"
        repo.save_findings(conn, doc_id, run_id, result.findings)
        reason = "; ".join(result.reasons) or (_AWAITING_APPROVAL if is_clean else None)
        repo.set_status(conn, doc_id, status, reason)
        repo.log_event(
            conn,
            reviewer,
            "recheck.completed",
            doc_id,
            {
                "run_id": run_id,
                "status": status.value,
                "findings": [f.rule_id for f in result.findings],
            },
        )
        findings = tuple(_finding_row(f, run_id) for f in result.findings)
        open_rules = ", ".join(f.rule_id for f in result.findings)
        checks = (
            "Checks rerun: nothing open. Approve the invoice to send it to export."
            if is_clean
            else f"Checks rerun: {status.value}" + (f" ({open_rules})" if open_rules else "")
        )
        return ReviewOutcome(
            doc_id=doc_id,
            status=status,
            message=checks,
            findings=findings,
            run_id=run_id,
            checks=checks,
        )

    def _refresh_coding(self, conn: Connection, doc_id: UUID, reviewer: str) -> None:
        """Recompute the coding amounts from the corrected values, as intake does."""
        from invoiceflow.coding.assign import assign
        from invoiceflow.pipeline.stages import find_purchase_order
        from invoiceflow.store.repo import Repo

        store = Repo(conn)
        invoice = store.stored_invoice(doc_id)
        record = store.get_document(doc_id)
        if invoice is None or record is None:
            return
        master = store.load_master()
        vendor = master.vendor(record.vendor_id) if record.vendor_id else None
        fresh = assign(invoice, vendor, find_purchase_order(invoice, master), master.coding)
        current = queries.document_bundle(conn, doc_id).coding_lines
        lines = keep_reviewer_choices(fresh, current)
        if not coding_changed(lines, current):
            return
        repo.save_coding_lines(conn, doc_id, lines)
        repo.log_event(
            conn,
            reviewer,
            "coding.recomputed",
            doc_id,
            {
                "net": [str(line.net_amount) for line in lines],
                "tax": [str(line.tax_amount) for line in lines],
            },
        )

    def _bundle_or_raise(self, conn: Connection, doc_id: UUID) -> DocumentBundle:
        bundle = queries.document_bundle(conn, doc_id)
        if bundle is None:
            raise LookupError(f"document {doc_id} not found")
        return bundle

    def confirm(self, doc_id: UUID, field: str, reviewer: str) -> ReviewOutcome:
        """ "Correct as printed": the reviewer checked the value against the invoice and it is
        right. A flag on the field clears and stays cleared on later rechecks; a hold does not
        (it needs a release with a comment)."""
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            value = printed_value(bundle, field)
            self._review(
                conn,
                doc_id=doc_id,
                reviewer=reviewer,
                action=ReviewAction.CONFIRM,
                field=field,
                old_value=value,
                new_value=value,
            )
            repo.log_event(conn, reviewer, "review.confirmed", doc_id, {"field": field})
            flagged = any(
                finding.field == field and finding.severity is Severity.FLAG
                for finding in bundle.findings
            )
            if not flagged:
                return ReviewOutcome(
                    doc_id=doc_id,
                    status=bundle.document.status,
                    message=f"Marked {field} as checked.",
                    findings=bundle.findings,
                )
            outcome = self._rerun(conn, doc_id, reviewer)
            return ReviewOutcome(
                doc_id=outcome.doc_id,
                status=outcome.status,
                message=f"Accepted {field} as printed; its flag is cleared. {outcome.message}",
                findings=outcome.findings,
                run_id=outcome.run_id,
                checks=outcome.checks,
            )

    def correct(self, doc_id: UUID, field: str, raw_value: str, reviewer: str) -> ReviewOutcome:
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            row = bundle.field(field)
            if row is None and field not in HEADER_FIELDS:
                raise ValueError(f"{field} is not a header field on this document")
            # No row: the model did not read this value, and the reviewer types it in.
            old_value = row.value_raw if row is not None else None
            normalized = normalize_field_value(field, raw_value)
            if normalized is None:
                raise ValueError(f"{field} cannot be empty")
            # A rate typed as 9, 9.00 or 9 % is saved, logged and shown as "9%".
            typed = display_value(field, normalized) if field in RATE_FIELDS else raw_value
            if row is not None and normalized == row.value_norm:
                return ReviewOutcome(
                    doc_id=doc_id,
                    status=bundle.document.status,
                    message=f"{field} already has that value",
                    findings=bundle.findings,
                    changed=False,
                )
            repo.save_field_value(
                conn,
                doc_id,
                name=field,
                value_raw=typed,
                value_norm=normalized,
                page_no=row.page_no if row is not None else None,
                bbox=row.bbox if row is not None else None,
                match_type=MatchType.EXACT,
                match_score=100.0,
                confidence=Confidence.HIGH,
                source=ValueSource.REVIEWER,
            )
            self._review(
                conn,
                doc_id=doc_id,
                reviewer=reviewer,
                action=ReviewAction.CORRECT,
                field=field,
                old_value=old_value,
                new_value=typed,
            )
            repo.log_event(
                conn,
                reviewer,
                "review.corrected",
                doc_id,
                {"field": field, "old": old_value, "new": typed},
            )
            self._refresh_coding(conn, doc_id, reviewer)
            outcome = self._rerun(conn, doc_id, reviewer, resolved_fields=frozenset({field}))
            return ReviewOutcome(
                doc_id=outcome.doc_id,
                status=outcome.status,
                message=f"Corrected {field}. {outcome.message}",
                findings=outcome.findings,
                run_id=outcome.run_id,
                checks=outcome.checks,
            )

    def edit_line_items(
        self, doc_id: UUID, items: Sequence[NormalizedLineItem], reviewer: str
    ) -> ReviewOutcome:
        if not items:
            raise ValueError("an invoice needs at least one line item")
        line_nos = [item.line_no for item in items]
        if len(line_nos) != len(set(line_nos)):
            raise ValueError("line numbers must be unique")
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            repo.save_line_items(conn, doc_id, items)
            self._review(
                conn,
                doc_id=doc_id,
                reviewer=reviewer,
                action=ReviewAction.CORRECT,
                field="line_items",
                old_value=str(len(bundle.line_items)),
                new_value=str(len(items)),
            )
            repo.log_event(
                conn,
                reviewer,
                "review.line_items_saved",
                doc_id,
                {"count": len(items)},
            )
            self._refresh_coding(conn, doc_id, reviewer)
            outcome = self._rerun(conn, doc_id, reviewer, resolved_fields=frozenset({"line_items"}))
            return ReviewOutcome(
                doc_id=outcome.doc_id,
                status=outcome.status,
                message=f"Saved {len(items)} line item(s). {outcome.message}",
                findings=outcome.findings,
                run_id=outcome.run_id,
                checks=outcome.checks,
            )

    def recode(self, doc_id: UUID, updates: Sequence[CodingUpdate], reviewer: str) -> ReviewOutcome:
        if not updates:
            raise ValueError("choose at least one coding line to change")
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            master = queries.master_data(conn)
            current = {line.line_no: line for line in bundle.coding_lines}
            changed: list[CodingLine] = []
            old_labels: dict[int, str] = {}
            for update in updates:
                line = current.get(update.line_no)
                if line is None:
                    raise ValueError(f"coding line {update.line_no} does not exist")
                _validate_coding(master, update)
                old_labels[update.line_no] = _coding_label(line)
                changed.append(
                    CodingLine(
                        line_no=line.line_no,
                        gl_account=update.gl_account,
                        cost_center=update.cost_center,
                        tax_code=update.tax_code,
                        net_amount=line.net_amount,
                        tax_amount=line.tax_amount,
                        description=line.description,
                        source_line_nos=line.source_line_nos,
                        coding_source=CodingSource.REVIEWER,
                    )
                )
            by_line = {line.line_no: line for line in changed}
            merged = tuple(by_line.get(line.line_no, line) for line in bundle.coding_lines)
            repo.save_coding_lines(conn, doc_id, merged)
            for line in changed:
                self._review(
                    conn,
                    doc_id=doc_id,
                    reviewer=reviewer,
                    action=ReviewAction.RECODE,
                    field=f"coding_lines[{line.line_no}]",
                    old_value=old_labels[line.line_no],
                    new_value=_coding_label(line),
                )
            repo.log_event(
                conn,
                reviewer,
                "review.recoded",
                doc_id,
                {"lines": [line.line_no for line in changed]},
            )
            outcome = self._rerun(
                conn, doc_id, reviewer, resolved_fields=frozenset({"coding_lines"})
            )
            return ReviewOutcome(
                doc_id=outcome.doc_id,
                status=outcome.status,
                message=f"Recoded {len(changed)} line(s) as reviewer. {outcome.message}",
                findings=outcome.findings,
                run_id=outcome.run_id,
                checks=outcome.checks,
            )

    def approve(self, doc_id: UUID, reviewer: str, comment: str | None = None) -> ReviewOutcome:
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            if bundle.document.status not in _APPROVABLE:
                raise ValueError(f"cannot approve a document in {bundle.document.status.value}")
            if bundle.document.status is DocStatus.ON_HOLD:
                raise ValueError("release the hold, with a comment, before approving")
            self._review(
                conn,
                doc_id=doc_id,
                reviewer=reviewer,
                action=ReviewAction.APPROVE,
                comment=comment,
            )
            repo.set_status(conn, doc_id, DocStatus.APPROVED, comment or "approved by reviewer")
            repo.log_event(conn, reviewer, "review.approved", doc_id, {"comment": comment})
            return ReviewOutcome(
                doc_id=doc_id,
                status=DocStatus.APPROVED,
                message="Approved",
                findings=bundle.findings,
            )

    def reject(self, doc_id: UUID, reviewer: str, comment: str | None = None) -> ReviewOutcome:
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            if bundle.document.status not in _APPROVABLE:
                raise ValueError(f"cannot reject a document in {bundle.document.status.value}")
            self._review(
                conn,
                doc_id=doc_id,
                reviewer=reviewer,
                action=ReviewAction.REJECT,
                comment=comment,
            )
            repo.set_status(conn, doc_id, DocStatus.REJECTED, comment or "rejected by reviewer")
            repo.log_event(conn, reviewer, "review.rejected", doc_id, {"comment": comment})
            return ReviewOutcome(
                doc_id=doc_id,
                status=DocStatus.REJECTED,
                message="Rejected",
                findings=bundle.findings,
            )

    def release_hold(self, doc_id: UUID, reviewer: str, comment: str) -> ReviewOutcome:
        if not (comment or "").strip():
            raise ValueError("releasing a hold needs a comment")
        with self._write() as conn:
            self._bundle_or_raise(conn, doc_id)
            self._review(
                conn,
                doc_id=doc_id,
                reviewer=reviewer,
                action=ReviewAction.RELEASE_HOLD,
                comment=comment,
            )
            repo.log_event(conn, reviewer, "review.hold_released", doc_id, {"comment": comment})
            outcome = self._rerun(conn, doc_id, reviewer, release_holds=True)
            if outcome.status is DocStatus.ON_HOLD:
                repo.set_status(conn, doc_id, DocStatus.NEEDS_REVIEW, "hold released")
                outcome = ReviewOutcome(
                    doc_id=outcome.doc_id,
                    status=DocStatus.NEEDS_REVIEW,
                    message="Hold released; the invoice still needs review. " + outcome.message,
                    findings=outcome.findings,
                    run_id=outcome.run_id,
                    checks="The invoice still needs review. " + outcome.checks,
                )
            return outcome


def _validate_coding(master: MasterData, update: CodingUpdate) -> None:
    if update.gl_account is not None and not master.coding.has_gl(update.gl_account):
        raise ValueError(f"{update.gl_account!r} is not an active GL account")
    if update.cost_center is not None and not master.coding.has_cost_center(update.cost_center):
        raise ValueError(f"{update.cost_center!r} is not an active cost center")
    if update.tax_code is not None and master.coding.tax_rate(update.tax_code) is None:
        raise ValueError(f"{update.tax_code!r} is not a tax code")


def _coding_label(line: CodingLine | CodingRow) -> str:
    return f"{line.gl_account or '-'} / {line.cost_center or '-'} / {line.tax_code or '-'}"


def subtotal_hint(bundle: DocumentBundle) -> Decimal | None:
    amounts = [item.amount for item in bundle.line_items if item.amount is not None]
    return sum(amounts, Decimal("0")) if amounts else None
