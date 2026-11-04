"""Integration fixtures for WS7: the dev Postgres, rolled back after every test."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backend import PostgresBackend  # noqa: E402
from invoiceflow.devdb.connection import connect, database_url, safe_url  # noqa: E402
from invoiceflow.devdb.fixtures import load_fixtures  # noqa: E402
from invoiceflow.devdb.migrate import apply_migrations  # noqa: E402


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


@pytest.fixture()
def backend(conn, loaded):
    return PostgresBackend(conn)


@pytest.fixture()
def docs(backend):
    return {doc.invoice_number: doc for doc in backend.list_documents()}
