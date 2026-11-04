"""Integration: export-once is enforced by ``export_rows.doc_id`` through one transaction."""

from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest

from invoiceflow.devdb.connection import connect, database_url, safe_url
from invoiceflow.devdb.fixtures import load_fixtures
from invoiceflow.devdb.migrate import apply_migrations
from invoiceflow.export.checks import BatchError
from invoiceflow.export.exporter import record_export
from invoiceflow.export.models import ExportRowPlan

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def conn():
    try:
        connection = connect(connect_timeout=2)
    except psycopg.OperationalError as exc:
        pytest.skip(f"dev Postgres not reachable at {safe_url(database_url())}: {exc}")
    yield connection
    connection.close()


@pytest.fixture()
def loaded(conn):
    with conn.transaction(force_rollback=True):
        apply_migrations(conn)
        yield load_fixtures(conn)


def _doc_id(loaded, invoice_number: str):
    return next(d.doc_id for d in loaded.documents if d.invoice_number == invoice_number)


def _args(doc_id, batch_id: str = "b1"):
    return dict(
        created_at=datetime.now(UTC),
        csv_path=f"data/export/{batch_id}.csv",
        csv_sha256="0" * 64,
        row_count=1,
        total=Decimal("1177.20"),
        layout="hypothetical",
        mapping_version="1",
        manifest={"batch_id": batch_id, "model": "gemma4:12b", "row_count": 1, "total": "1177.20"},
    )


def test_record_export_writes_batch_and_rows(conn, loaded):
    doc_id = _doc_id(loaded, "SAV-2026-0412")
    record_export(
        conn,
        "b1",
        row_plans=(ExportRowPlan(doc_id=doc_id, first_row_no=1, row_count=1),),
        **_args(doc_id),
    )

    with conn.cursor() as cur:
        cur.execute("SELECT batch_id, doc_id, first_row_no, row_count FROM export_rows")
        assert cur.fetchall() == [("b1", doc_id, 1, 1)]
        cur.execute("SELECT row_count, total, manifest FROM export_batches WHERE batch_id = 'b1'")
        row_count, total, manifest = cur.fetchone()
        assert (row_count, total) == (1, Decimal("1177.20"))
        assert manifest["batch_id"] == "b1"


def test_record_export_blocks_a_second_export(conn, loaded):
    doc_id = _doc_id(loaded, "SAV-2026-0412")
    record_export(
        conn,
        "b1",
        row_plans=(ExportRowPlan(doc_id=doc_id, first_row_no=1, row_count=1),),
        **_args(doc_id),
    )

    with pytest.raises(BatchError, match="already exported"):
        record_export(
            conn,
            "b2",
            row_plans=(ExportRowPlan(doc_id=doc_id, first_row_no=1, row_count=1),),
            **_args(doc_id, batch_id="b2"),
        )
