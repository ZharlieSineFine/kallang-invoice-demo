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
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg import Connection

from app import queries, repo
from app.evaluation import latest_evaluation
from app.formatting import normalize_field_value
from app.models import (
    BatchSummary,
    CodingRow,
    DocumentBundle,
    DocumentSummary,
    FindingRow,
    ReviewOutcome,
    TraceData,
)
from app.recheck import RecheckInput, recheck
from invoiceflow.contracts import (
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
    ValueSource,
)
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


@dataclass(frozen=True)
class CodingUpdate:
    line_no: int
    gl_account: str | None
    cost_center: str | None
    tax_code: str | None


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
    ) -> None:
        self._conn = conn
        self._rules_config = rules_config or load_config("rules")
        self._reports_dir = reports_dir

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

    def _rerun(self, conn: Connection, doc_id: UUID, reviewer: str) -> ReviewOutcome:
        bundle = queries.document_bundle(conn, doc_id)
        if bundle is None:
            raise LookupError(f"document {doc_id} not found")
        state = RecheckInput.from_bundle(bundle, self._rules_config)
        result = recheck(state)
        run_id = f"review-{uuid4().hex[:12]}"
        repo.save_findings(conn, doc_id, run_id, result.findings)
        reason = "; ".join(result.reasons) or None
        repo.set_status(conn, doc_id, result.status, reason)
        repo.log_event(
            conn,
            reviewer,
            "recheck.completed",
            doc_id,
            {
                "run_id": run_id,
                "status": result.status.value,
                "findings": [f.rule_id for f in result.findings],
            },
        )
        findings = tuple(_finding_row(f, run_id) for f in result.findings)
        return ReviewOutcome(
            doc_id=doc_id,
            status=result.status,
            message=(
                f"Checks rerun: {result.status.value}"
                + (f" ({', '.join(f.rule_id for f in result.findings)})" if result.findings else "")
            ),
            findings=findings,
            run_id=run_id,
        )

    def _bundle_or_raise(self, conn: Connection, doc_id: UUID) -> DocumentBundle:
        bundle = queries.document_bundle(conn, doc_id)
        if bundle is None:
            raise LookupError(f"document {doc_id} not found")
        return bundle

    def confirm(self, doc_id: UUID, field: str, reviewer: str) -> ReviewOutcome:
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            row = bundle.field(field)
            if row is None:
                raise ValueError(f"{field} is not a header field on this document")
            self._review(
                conn,
                doc_id=doc_id,
                reviewer=reviewer,
                action=ReviewAction.CONFIRM,
                field=field,
                old_value=row.value_raw,
                new_value=row.value_raw,
            )
            repo.log_event(conn, reviewer, "review.confirmed", doc_id, {"field": field})
            return ReviewOutcome(
                doc_id=doc_id,
                status=bundle.document.status,
                message=f"Confirmed {field}",
                findings=bundle.findings,
            )

    def correct(self, doc_id: UUID, field: str, raw_value: str, reviewer: str) -> ReviewOutcome:
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            row = bundle.field(field)
            if row is None:
                raise ValueError(f"{field} is not a header field on this document")
            normalized = normalize_field_value(field, raw_value)
            if normalized is None:
                raise ValueError(f"{field} cannot be empty")
            if normalized == row.value_norm:
                return ReviewOutcome(
                    doc_id=doc_id,
                    status=bundle.document.status,
                    message=f"{field} already has that value",
                    findings=bundle.findings,
                )
            repo.save_field_value(
                conn,
                doc_id,
                name=field,
                value_raw=raw_value,
                value_norm=normalized,
                page_no=row.page_no,
                bbox=row.bbox,
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
                old_value=row.value_raw,
                new_value=raw_value,
            )
            repo.log_event(
                conn,
                reviewer,
                "review.corrected",
                doc_id,
                {"field": field, "old": row.value_raw, "new": raw_value},
            )
            outcome = self._rerun(conn, doc_id, reviewer)
            return ReviewOutcome(
                doc_id=outcome.doc_id,
                status=outcome.status,
                message=f"Corrected {field}. {outcome.message}",
                findings=outcome.findings,
                run_id=outcome.run_id,
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
            outcome = self._rerun(conn, doc_id, reviewer)
            return ReviewOutcome(
                doc_id=outcome.doc_id,
                status=outcome.status,
                message=f"Saved {len(items)} line item(s). {outcome.message}",
                findings=outcome.findings,
                run_id=outcome.run_id,
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
            outcome = self._rerun(conn, doc_id, reviewer)
            return ReviewOutcome(
                doc_id=outcome.doc_id,
                status=outcome.status,
                message=f"Recoded {len(changed)} line(s) as reviewer. {outcome.message}",
                findings=outcome.findings,
                run_id=outcome.run_id,
            )

    def approve(self, doc_id: UUID, reviewer: str, comment: str | None = None) -> ReviewOutcome:
        with self._write() as conn:
            bundle = self._bundle_or_raise(conn, doc_id)
            if bundle.document.status not in _APPROVABLE:
                raise ValueError(f"cannot approve a document in {bundle.document.status.value}")
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
            outcome = self._rerun(conn, doc_id, reviewer)
            if outcome.status is DocStatus.ON_HOLD:
                repo.set_status(conn, doc_id, DocStatus.NEEDS_REVIEW, "hold released")
                outcome = ReviewOutcome(
                    doc_id=outcome.doc_id,
                    status=DocStatus.NEEDS_REVIEW,
                    message="Hold released; the invoice still needs review. " + outcome.message,
                    findings=outcome.findings,
                    run_id=outcome.run_id,
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
