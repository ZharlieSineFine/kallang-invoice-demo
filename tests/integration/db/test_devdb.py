"""Integration: apply the schema and load the golden fixtures into the dev Postgres.

Marked ``db``. Skips when the dev database is not running. Every test runs inside a
transaction that is rolled back, so this never leaves rows behind for the review app.
"""

from decimal import Decimal

import psycopg
import pytest

from invoiceflow.devdb.connection import connect, database_url, safe_url
from invoiceflow.devdb.fixtures import load_fixtures
from invoiceflow.devdb.migrate import apply_migrations

pytestmark = pytest.mark.db

REQUIRED_TABLES = {
    "schema_migrations",
    "gl_accounts",
    "cost_centers",
    "tax_codes",
    "venue_cost_centers",
    "vendors",
    "purchase_orders",
    "bronze_files",
    "documents",
    "pages",
    "extractions",
    "fields",
    "line_items",
    "coding_lines",
    "findings",
    "reviews",
    "export_batches",
    "export_rows",
    "notifications",
    "events",
}


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


def _doc_ids(report) -> dict[str, object]:
    return {doc.invoice_number: doc.doc_id for doc in report.documents}


def test_schema_has_every_contract_table(conn):
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        assert {row[0] for row in cur.fetchall()} >= REQUIRED_TABLES


def test_migrations_are_idempotent(conn):
    with conn.transaction(force_rollback=True):
        apply_migrations(conn)
        assert apply_migrations(conn) == ()


def test_two_documents_with_the_expected_statuses(loaded):
    assert len(loaded.documents) == 2
    statuses = {doc.fixture_id: doc.status for doc in loaded.documents}
    assert statuses == {
        "golden-a-clean": "AUTO_PASSED",
        "golden-a-total-mismatch": "NEEDS_REVIEW",
    }
    assert loaded.fields == 42
    assert loaded.line_items == 8
    assert loaded.coding_lines == 2
    assert loaded.findings == 1


def test_document_rows_and_master_data(conn, loaded):
    doc_id = _doc_ids(loaded)["SAV-2026-0412"]
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.doc_type, d.status, d.vendor_id, b.source, b.mime_type, p.page_no
            FROM documents d
            JOIN bronze_files b USING (file_id)
            JOIN pages p USING (doc_id)
            WHERE d.doc_id = %s
            """,
            (doc_id,),
        )
        assert cur.fetchone() == (
            "TAX_INVOICE",
            "AUTO_PASSED",
            "V001",
            "golden",
            "application/pdf",
            1,
        )
        cur.execute("SELECT count(*) FROM vendors")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM purchase_orders")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM venue_cost_centers")
        assert cur.fetchone()[0] == 7
        cur.execute("SELECT count(*) FROM extractions WHERE valid")
        assert cur.fetchone()[0] == 2


def test_fields_keep_the_printed_value_and_the_box(conn, loaded):
    docs = _doc_ids(loaded)
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        cur.execute(
            """
            SELECT value_raw, value_norm, confidence, page_no, x0, y0, x1, y1
            FROM fields WHERE doc_id = %s AND name = 'invoice_number'
            """,
            (docs["SAV-2026-0412"],),
        )
        raw, norm, confidence, page_no, x0, y0, x1, y1 = cur.fetchone()
        assert (raw, norm, confidence, page_no) == ("SAV-2026-0412", "SAV-2026-0412", "HIGH", 1)
        assert Decimal("0") <= x0 < x1 <= Decimal("1")
        assert Decimal("0") <= y0 < y1 <= Decimal("1")

        cur.execute(
            "SELECT confidence FROM fields WHERE doc_id = %s AND name = 'subtotal'",
            (docs["SAV-2026-0413"],),
        )
        assert cur.fetchone()[0] == "LOW", "R02 flags the subtotal, so its confidence drops"


def test_line_items_and_coding(conn, loaded):
    docs = _doc_ids(loaded)
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        for number, tax in (("SAV-2026-0412", "97.20"), ("SAV-2026-0413", "98.10")):
            cur.execute(
                "SELECT count(*), sum(amount) FROM line_items WHERE doc_id = %s",
                (docs[number],),
            )
            count, total = cur.fetchone()
            assert count == 4
            assert total == Decimal("1080.00")
            cur.execute(
                """
                SELECT gl_account, cost_center, tax_code, net_amount, tax_amount, coding_source
                FROM coding_lines WHERE doc_id = %s
                """,
                (docs[number],),
            )
            gl, center, code, net, tax_amount, source = cur.fetchone()
            assert (gl, center, code, source) == ("610200", "KG1100", "TX", "PO")
            assert net == Decimal("1080.00")
            assert tax_amount == Decimal(tax)


def test_only_the_twin_has_a_finding(conn, loaded):
    docs = _doc_ids(loaded)
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        cur.execute(
            "SELECT doc_id, rule_id, field, severity, evidence FROM findings ORDER BY rule_id"
        )
        rows = cur.fetchall()
        assert len(rows) == 1
        doc_id, rule_id, field, severity, evidence = rows[0]
        assert doc_id == docs["SAV-2026-0413"]
        assert (rule_id, field, severity) == ("R02", "subtotal", "FLAG")
        assert evidence == {"lines_sum": "1080.00", "subtotal": "1090.00"}


def test_reloading_replaces_instead_of_duplicating(conn):
    with conn.transaction(force_rollback=True):
        first = load_fixtures(conn)
        second = load_fixtures(conn)
        assert second == first
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM documents")
            assert cur.fetchone()[0] == 2


def test_audit_events_are_written(conn, loaded):
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), count(DISTINCT actor) FROM events WHERE type = 'fixture.loaded'"
        )
        assert cur.fetchone() == (2, 1)


def test_nothing_is_exported_yet(conn, loaded):
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM export_rows")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM export_batches")
        assert cur.fetchone()[0] == 0
