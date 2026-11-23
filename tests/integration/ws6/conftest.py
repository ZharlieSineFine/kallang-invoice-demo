"""Shared fixtures for WS6 integration tests (real Postgres, skipped when not reachable)."""

import psycopg
import pytest

from invoiceflow.storage import LocalBlobStore
from invoiceflow.store.connection import connect, database_url, safe_url
from invoiceflow.store.fixtures import load_fixtures, truncate
from invoiceflow.store.migrate import apply_migrations

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
def migrated(conn):
    """Schema applied on a clean slate, inside a transaction that always rolls back."""
    with conn.transaction(force_rollback=True):
        apply_migrations(conn)
        truncate(conn)
        yield conn


@pytest.fixture()
def loaded(migrated, tmp_path):
    """The two golden invoices, their files in a scratch folder (erase and delete tests)."""
    store = LocalBlobStore(tmp_path)
    load_fixtures(migrated, store)
    return migrated, store


@pytest.fixture(autouse=True)
def replay_recorded_answers(monkeypatch):
    """Use the recorded model answers. Live mode (the .env default) would call the model and
    rewrite the tracked files in data/llm_cache/ on every test run."""
    monkeypatch.setenv("LLM_MODE", "replay")
