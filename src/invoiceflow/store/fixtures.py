"""Load the golden fixtures through the WS6 store + storage (replaces ``devdb/fixtures.py``).

Run ``make db-dev && make fixtures`` (or ``scripts/load_fixtures.py``). The loader truncates
the invoice tables first, inserts the master data, then runs each golden PDF through the stub
pipeline and persists bronze + silver with the ``Repository`` and ``LocalBlobStore``.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from psycopg import Connection

from invoiceflow.pipeline.golden import load_golden
from invoiceflow.pipeline.skeleton import GOLDEN_TODAY
from invoiceflow.pipeline.steps import Pipeline, golden_pipeline, intake_document
from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.repo import Repo

# Children first. RESTART IDENTITY keeps review-app URLs and ids stable between loads.
DATA_TABLES = (
    "events",
    "notifications",
    "export_rows",
    "export_batches",
    "reviews",
    "findings",
    "coding_lines",
    "line_items",
    "fields",
    "extractions",
    "pages",
    "documents",
    "bronze_files",
)
MASTER_TABLES = (
    "venue_cost_centers",
    "purchase_orders",
    "vendors",
    "tax_codes",
    "cost_centers",
    "gl_accounts",
)


@dataclass(frozen=True)
class LoadedDocument:
    fixture_id: str
    doc_id: UUID
    invoice_number: str | None
    status: str


@dataclass(frozen=True)
class LoadReport:
    documents: tuple[LoadedDocument, ...]

    def render(self) -> str:
        lines = [f"{len(self.documents)} document(s) loaded:"]
        width = max((len(d.fixture_id) for d in self.documents), default=0)
        for doc in self.documents:
            lines.append(
                f"  {doc.fixture_id:<{width}}  {doc.status:<13}  {doc.invoice_number or '-'}"
            )
        return "\n".join(lines)


def truncate(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE")
        cur.execute(f"TRUNCATE TABLE {', '.join(MASTER_TABLES)} RESTART IDENTITY CASCADE")


def load_fixtures(
    conn: Connection,
    store: LocalBlobStore,
    pipeline: Pipeline | None = None,
) -> LoadReport:
    """Replace the invoice tables with the golden documents. Does not commit."""
    pipeline = pipeline or golden_pipeline()
    repo = Repo(conn)
    truncate(conn)
    repo.save_master(pipeline.master)

    documents: list[LoadedDocument] = []
    for fixture in load_golden().fixtures:
        result = intake_document(
            fixture.pdf_path,
            repo=repo,
            store=store,
            pipeline=pipeline,
            today=GOLDEN_TODAY,
            run_id="fixtures",
            file_id=fixture.file_id,
            doc_id=fixture.doc_id,
            source="golden",
        )
        documents.append(
            LoadedDocument(
                fixture_id=fixture.fixture_id,
                doc_id=fixture.doc_id,
                invoice_number=fixture.invoice_number,
                status=result.status.value,
            )
        )
    return LoadReport(tuple(documents))
