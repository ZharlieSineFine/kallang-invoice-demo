"""Loads the golden fixtures in tests/fixtures/golden (built by scripts/build_golden.py)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from invoiceflow.contracts import (
    DocStatus,
    ExtractionResult,
    FieldLocation,
    Finding,
    InvoiceTruth,
    MasterData,
    PageText,
)
from invoiceflow.settings import golden_dir, repo_root


class GoldenFixtureNotFound(LookupError):
    """The stubs only know the golden fixtures; anything else is a test or wiring error."""


@dataclass(frozen=True)
class GoldenFixture:
    fixture_id: str
    directory: Path
    pdf_path: Path
    sha256: str
    doc_id: UUID
    file_id: UUID
    page: PageText
    extraction: ExtractionResult
    locations: tuple[FieldLocation, ...]
    truth: InvoiceTruth
    expected_findings: tuple[Finding, ...]
    expected_status: DocStatus

    @property
    def invoice_number(self) -> str:
        number = self.truth.invoice.invoice_number
        if number is None:
            raise ValueError(f"{self.fixture_id} has no invoice number")
        return number

    @property
    def page_image_path(self) -> Path:
        if self.page.image_path is None:
            raise ValueError(f"{self.fixture_id} has no page image")
        return repo_root() / self.page.image_path


@dataclass(frozen=True)
class GoldenSet:
    fixtures: tuple[GoldenFixture, ...]
    master: MasterData

    def by_sha(self, sha256: str) -> GoldenFixture:
        return self._first(lambda f: f.sha256 == sha256, f"no golden fixture with sha256 {sha256}")

    def by_invoice_number(self, number: str | None) -> GoldenFixture:
        return self._first(
            lambda f: f.invoice_number == number, f"no golden fixture for invoice {number!r}"
        )

    def matching_text(self, text: str) -> GoldenFixture:
        return self._first(
            lambda f: f.invoice_number in text, "no golden invoice number found in the text"
        )

    def _first(self, predicate, message: str) -> GoldenFixture:
        found = next((f for f in self.fixtures if predicate(f)), None)
        if found is None:
            raise GoldenFixtureNotFound(message)
        return found


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_golden(root: Path | None = None) -> GoldenSet:
    base = root or golden_dir()
    fixtures = []
    for entry in _read(base / "manifest.json"):
        folder = base / entry["fixture_id"]
        fixtures.append(
            GoldenFixture(
                fixture_id=entry["fixture_id"],
                directory=folder,
                pdf_path=folder / "invoice.pdf",
                sha256=entry["sha256"],
                doc_id=UUID(entry["doc_id"]),
                file_id=UUID(entry["file_id"]),
                page=PageText.model_validate(_read(folder / "page-1.words.json")),
                extraction=ExtractionResult.model_validate(_read(folder / "extraction.json")),
                locations=tuple(
                    FieldLocation.model_validate(x) for x in _read(folder / "locations.json")
                ),
                truth=InvoiceTruth.model_validate(_read(folder / "truth.json")),
                expected_findings=tuple(
                    Finding.model_validate(x) for x in _read(folder / "expected_findings.json")
                ),
                expected_status=DocStatus(entry["expected_status"]),
            )
        )
    return GoldenSet(
        fixtures=tuple(fixtures), master=MasterData.model_validate(_read(base / "master.json"))
    )
