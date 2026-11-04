"""Fixtures for the WS7 unit tests: in-memory bundles built from the golden contracts.

No database and no Ollama. The fake backend mirrors the review actions so AppTest can drive
the real page functions without Postgres.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backend import _validate_coding  # noqa: E402
from app.formatting import normalize_field_value  # noqa: E402
from app.models import (  # noqa: E402
    BatchSummary,
    CodingRow,
    CountRow,
    DashboardData,
    DocumentBundle,
    DocumentSummary,
    EventRow,
    ExtractionInfo,
    FieldRow,
    FindingRow,
    LineItemRow,
    PageRow,
    ReviewOutcome,
    ReviewRow,
    TraceData,
)
from app.recheck import RecheckInput, recheck  # noqa: E402
from invoiceflow.contracts import (  # noqa: E402
    HEADER_FIELDS,
    CodingSource,
    Confidence,
    DocStatus,
    LLMMode,
    MatchType,
    ReviewAction,
    Scope,
    Severity,
    ValueSource,
)
from invoiceflow.pipeline.golden import GoldenFixture, load_golden  # noqa: E402
from invoiceflow.settings import load_config  # noqa: E402

_NORMALIZED_NAME = {"gst_rate": "gst_rate_percent"}


def _normalized(invoice, name: str, raw: Any) -> str:
    value = getattr(invoice, _NORMALIZED_NAME.get(name, name), None)
    if value is None:
        return str(raw)
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def make_bundle(fixture: GoldenFixture) -> DocumentBundle:
    truth = fixture.truth
    locations = {loc.field: loc for loc in fixture.locations if "[" not in loc.field}
    extraction = fixture.extraction.extraction
    fields: list[FieldRow] = []
    for name in HEADER_FIELDS:
        raw = getattr(extraction, name) if extraction is not None else None
        if raw is None:
            continue
        loc = locations.get(name)
        confidence = (
            Confidence.HIGH
            if loc is not None and loc.match_type in {MatchType.EXACT, MatchType.NUMERIC}
            else Confidence.LOW
        )
        fields.append(
            FieldRow(
                name=name,
                value_raw=str(raw),
                value_norm=_normalized(truth.invoice, name, raw),
                page_no=loc.page_no if loc else None,
                bbox=loc.bbox if loc else None,
                match_type=loc.match_type if loc else MatchType.NONE,
                match_score=loc.score if loc else 0.0,
                confidence=confidence,
                source=ValueSource.MODEL,
            )
        )
    line_items = tuple(
        LineItemRow(
            line_no=item.line_no,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
            days=item.days,
            unit_price=item.unit_price,
            amount=item.amount,
            source=ValueSource.MODEL,
        )
        for item in truth.invoice.line_items
    )
    coding = tuple(
        CodingRow(
            line_no=line.line_no,
            gl_account=line.gl_account,
            cost_center=line.cost_center,
            tax_code=line.tax_code,
            net_amount=line.net_amount,
            tax_amount=line.tax_amount,
            description=line.description,
            source_line_nos=line.source_line_nos,
            coding_source=line.coding_source,
        )
        for line in truth.expected_coding
    )
    findings = tuple(
        FindingRow(
            rule_id=finding.rule_id,
            field=finding.field,
            severity=finding.severity,
            scope=finding.scope,
            message=finding.message,
            evidence=dict(finding.evidence),
            stage=finding.stage,
            run_id="fixtures",
        )
        for finding in fixture.expected_findings
    )
    worst = max((finding.severity for finding in findings), key=lambda s: s.rank, default=None)
    summary = DocumentSummary(
        doc_id=fixture.doc_id,
        status=fixture.expected_status,
        status_reason="; ".join(f"{f.rule_id}: {f.message}" for f in findings) or None,
        doc_type=truth.doc_type,
        vendor_id=truth.vendor_id,
        vendor_name="Stagecraft AV Rentals Pte. Ltd.",
        invoice_number=truth.invoice.invoice_number,
        supplier_name=truth.invoice.supplier_name,
        total=truth.invoice.total,
        received_at=datetime(2026, 11, 4, 0, 0, tzinfo=UTC),
        is_replay=True,
        finding_count=len(findings),
        highest_severity=worst,
    )
    page = PageRow(
        page_no=fixture.page.page_no,
        image_path=fixture.page.image_path,
        words_path=str(fixture.directory / f"page-{fixture.page.page_no}.words.json"),
        width_pt=fixture.page.width_pt,
        height_pt=fixture.page.height_pt,
    )
    info = ExtractionInfo(
        extraction_id=fixture.extraction.extraction_id,
        model=fixture.extraction.model,
        model_digest=fixture.extraction.model_digest,
        prompt_version=fixture.extraction.prompt_version,
        schema_version=fixture.extraction.schema_version,
        mode=LLMMode.REPLAY,
        valid=fixture.extraction.valid,
        error=fixture.extraction.error,
        latency_ms=fixture.extraction.latency_ms,
        created_at=fixture.extraction.created_at,
    )
    return DocumentBundle(
        document=summary,
        fields=tuple(fields),
        line_items=line_items,
        coding_lines=coding,
        findings=findings,
        pages=(page,),
        extraction=info,
    )


class FakeBackend:
    def __init__(self, bundles, master, rules_config, evaluation=None):
        self.bundles = {bundle.document.doc_id: bundle for bundle in bundles}
        self._master = master
        self.rules_config = rules_config
        self.evaluation = evaluation
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    # reads -----------------------------------------------------------------
    def list_documents(self, statuses: Sequence[DocStatus] = ()):
        docs = [bundle.document for bundle in self.bundles.values()]
        if statuses:
            docs = [doc for doc in docs if doc.status in statuses]
        return tuple(docs)

    def document(self, doc_id: UUID):
        return self.bundles.get(doc_id)

    def master(self):
        return self._master

    def trace(self, doc_id: UUID):
        bundle = self.bundles.get(doc_id)
        if bundle is None:
            return None
        runs = (
            "fixtures",
            *(
                str(event.payload.get("run_id"))
                for event in bundle.events
                if event.type == "recheck.completed"
            ),
        )
        return TraceData(bundle=bundle, finding_history=bundle.findings, runs=runs)

    def dashboard(self):
        docs = [bundle.document for bundle in self.bundles.values()]
        return DashboardData(
            total_documents=len(docs),
            auto_passed=sum(d.status is DocStatus.AUTO_PASSED for d in docs),
            needs_review=sum(d.status is DocStatus.NEEDS_REVIEW for d in docs),
            approved=sum(d.status is DocStatus.APPROVED for d in docs),
            auto_pass_rate=100.0
            * sum(d.status is DocStatus.AUTO_PASSED for d in docs)
            / max(1, len(docs)),
            corrections_by_field=(CountRow(key="subtotal", count=1),),
            corrections_by_vendor=(CountRow(key="Stagecraft AV Rentals Pte. Ltd.", count=1),),
            findings_by_check=(),
            latest_evaluation=self.evaluation,
        )

    def batches(self):
        return (
            BatchSummary(
                batch_id="B-001",
                created_at=datetime(2026, 11, 4, 1, 0, tzinfo=UTC),
                csv_path="data/gold/B-001.csv",
                row_count=1,
                total=Decimal("1177.20"),
                layout="hypothetical",
                mapping_version="sap-v1",
            ),
        )

    def export_status(self):
        return {"exported": 1, "approved_not_exported": 0}

    # writes ----------------------------------------------------------------
    def _store(self, bundle: DocumentBundle, **updates) -> DocumentBundle:
        changed = replace(bundle, **updates)
        self.bundles[bundle.document.doc_id] = changed
        return changed

    def _review(self, bundle, action, reviewer, field=None, old=None, new=None, comment=None):
        review = ReviewRow(
            action=action,
            reviewer=reviewer,
            field=field,
            old_value=old,
            new_value=new,
            comment=comment,
            created_at=datetime(2026, 11, 4, 2, 0, tzinfo=UTC),
        )
        return self._store(bundle, reviews=(*bundle.reviews, review))

    def _rerun(self, bundle: DocumentBundle, reviewer: str) -> ReviewOutcome:
        state = RecheckInput.from_bundle(bundle, self.rules_config)
        result = recheck(state)
        findings = tuple(
            FindingRow(
                rule_id=finding.rule_id,
                field=finding.field,
                severity=finding.severity,
                scope=finding.scope,
                message=finding.message,
                evidence=dict(finding.evidence),
                stage=finding.stage,
                run_id="fake-run",
            )
            for finding in result.findings
        )
        worst = max((f.severity for f in findings), key=lambda s: s.rank, default=None)
        document = replace(
            bundle.document,
            status=result.status,
            status_reason="; ".join(result.reasons) or None,
            finding_count=len(findings),
            highest_severity=worst,
        )
        event = EventRow(
            event_id=len(bundle.events) + 1,
            ts=datetime(2026, 11, 4, 2, 0, tzinfo=UTC),
            actor=reviewer,
            type="recheck.completed",
            payload={"run_id": "fake-run", "status": result.status.value},
        )
        self._store(
            bundle,
            document=document,
            findings=findings,
            events=(*bundle.events, event),
        )
        return ReviewOutcome(
            doc_id=document.doc_id,
            status=result.status,
            message=f"Checks rerun: {result.status.value}",
            findings=findings,
            run_id="fake-run",
        )

    def confirm(self, doc_id, field, reviewer):
        bundle = self.bundles[doc_id]
        row = bundle.field(field)
        if row is None:
            raise ValueError(f"{field} is not a header field")
        self.calls.append(("confirm", (doc_id, field, reviewer)))
        self._review(bundle, ReviewAction.CONFIRM, reviewer, field, row.value_raw, row.value_raw)
        return ReviewOutcome(doc_id=doc_id, status=bundle.document.status, message="Confirmed")

    def correct(self, doc_id, field, raw_value, reviewer):
        bundle = self.bundles[doc_id]
        row = bundle.field(field)
        if row is None:
            raise ValueError(f"{field} is not a header field")
        normalized = normalize_field_value(field, raw_value)
        if normalized is None:
            raise ValueError(f"{field} cannot be empty")
        self.calls.append(("correct", (doc_id, field, raw_value, reviewer)))
        changed = replace(
            row,
            value_raw=raw_value,
            value_norm=normalized,
            source=ValueSource.REVIEWER,
            confidence=Confidence.HIGH,
            match_type=MatchType.EXACT,
        )
        fields = tuple(changed if item.name == field else item for item in bundle.fields)
        bundle = self._store(bundle, fields=fields)
        bundle = self._review(
            bundle, ReviewAction.CORRECT, reviewer, field, row.value_raw, raw_value
        )
        outcome = self._rerun(bundle, reviewer)
        return replace(outcome, message=f"Corrected {field}. {outcome.message}")

    def edit_line_items(self, doc_id, items, reviewer):
        bundle = self.bundles[doc_id]
        self.calls.append(("edit_line_items", (doc_id, tuple(items), reviewer)))
        rows = tuple(
            LineItemRow(
                line_no=item.line_no,
                description=item.description,
                quantity=item.quantity,
                unit=item.unit,
                days=item.days,
                unit_price=item.unit_price,
                amount=item.amount,
                source=ValueSource.REVIEWER,
            )
            for item in items
        )
        bundle = self._store(bundle, line_items=rows)
        bundle = self._review(
            bundle,
            ReviewAction.CORRECT,
            reviewer,
            "line_items",
            str(len(bundle.line_items)),
            str(len(rows)),
        )
        return self._rerun(bundle, reviewer)

    def recode(self, doc_id, updates, reviewer):
        bundle = self.bundles[doc_id]
        self.calls.append(("recode", (doc_id, tuple(updates), reviewer)))
        current = {line.line_no: line for line in bundle.coding_lines}
        merged = []
        for line in bundle.coding_lines:
            update = next((u for u in updates if u.line_no == line.line_no), None)
            if update is None:
                merged.append(line)
                continue
            _validate_coding(self._master, update)
            merged.append(
                replace(
                    line,
                    gl_account=update.gl_account,
                    cost_center=update.cost_center,
                    tax_code=update.tax_code,
                    coding_source=CodingSource.REVIEWER,
                )
            )
        bundle = self._store(bundle, coding_lines=tuple(merged))
        for update in updates:
            bundle = self._review(
                bundle,
                ReviewAction.RECODE,
                reviewer,
                f"coding_lines[{update.line_no}]",
                None,
                None,
            )
        del current
        return self._rerun(bundle, reviewer)

    def approve(self, doc_id, reviewer, comment=None):
        bundle = self.bundles[doc_id]
        self.calls.append(("approve", (doc_id, reviewer, comment)))
        bundle = self._review(bundle, ReviewAction.APPROVE, reviewer, comment=comment)
        document = replace(bundle.document, status=DocStatus.APPROVED)
        self._store(bundle, document=document)
        return ReviewOutcome(doc_id=doc_id, status=DocStatus.APPROVED, message="Approved")

    def reject(self, doc_id, reviewer, comment=None):
        bundle = self.bundles[doc_id]
        self.calls.append(("reject", (doc_id, reviewer, comment)))
        bundle = self._review(bundle, ReviewAction.REJECT, reviewer, comment=comment)
        document = replace(bundle.document, status=DocStatus.REJECTED)
        self._store(bundle, document=document)
        return ReviewOutcome(doc_id=doc_id, status=DocStatus.REJECTED, message="Rejected")

    def release_hold(self, doc_id, reviewer, comment):
        if not comment.strip():
            raise ValueError("releasing a hold needs a comment")
        bundle = self.bundles[doc_id]
        self.calls.append(("release_hold", (doc_id, reviewer, comment)))
        bundle = self._review(bundle, ReviewAction.RELEASE_HOLD, reviewer, comment=comment)
        return self._rerun(bundle, reviewer)


@pytest.fixture(scope="session")
def golden():
    return load_golden()


@pytest.fixture(scope="session")
def rules_config():
    return load_config("rules")


@pytest.fixture(scope="session")
def clean_bundle(golden):
    return make_bundle(golden.fixtures[0])


@pytest.fixture(scope="session")
def mismatch_bundle(golden):
    return make_bundle(next(f for f in golden.fixtures if "mismatch" in f.fixture_id))


@pytest.fixture()
def fake_backend(golden, clean_bundle, mismatch_bundle, rules_config):
    return FakeBackend((clean_bundle, mismatch_bundle), golden.master, rules_config)


@pytest.fixture()
def on_hold_backend(golden, mismatch_bundle, rules_config):
    hold = replace(
        mismatch_bundle,
        document=replace(mismatch_bundle.document, status=DocStatus.ON_HOLD, finding_count=1),
        findings=(
            FindingRow(
                rule_id="R08",
                field=None,
                severity=Severity.HOLD,
                scope=Scope.DOCUMENT,
                message="The bank account differs from the vendor master.",
                run_id="fixtures",
            ),
        ),
    )
    return FakeBackend((hold,), golden.master, rules_config)


@pytest.fixture()
def evaluation():
    from app.models import EvaluationSummary

    return EvaluationSummary(
        path="reports/latest.json",
        generated_at="2026-11-04T00:00:00Z",
        set_name="synthetic",
        document_count=2,
        metrics={"auto_pass_rate": 0.5, "accuracy": 0.99},
        raw={"set_name": "synthetic", "accuracy": 0.99},
        synthetic=True,
    )
