"""Reads the .env file and builds the ap database URL."""

import pytest

from invoiceflow.store.connection import (
    database_url,
    safe_url,
    stack_database_url,
    use_stack_database,
)


class TestDatabaseUrl:
    @pytest.fixture(autouse=True)
    def _ignore_the_repo_env_file(self, monkeypatch):
        monkeypatch.setattr("invoiceflow.store.connection.load_env_file", lambda: {})

    def test_explicit_url_wins(self, monkeypatch):
        monkeypatch.setenv("AP_DATABASE_URL", "postgresql://u:p@db:5432/x")
        assert database_url() == "postgresql://u:p@db:5432/x"

    def test_built_from_parts(self, monkeypatch):
        for key in ("AP_DATABASE_URL", "AP_DB_USER", "AP_DB_PASSWORD", "AP_DB_HOST", "AP_DB_PORT"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("AP_DB_NAME", "ap")
        monkeypatch.setenv("AP_DB_PORT", "5433")
        monkeypatch.setenv("AP_DB_PASSWORD", "p@ss word")

        assert database_url() == "postgresql://ap:p%40ss%20word@127.0.0.1:5433/ap"

    def test_defaults_match_compose_dev(self, monkeypatch):
        for key in (
            "AP_DATABASE_URL",
            "AP_DB_USER",
            "AP_DB_PASSWORD",
            "AP_DB_HOST",
            "AP_DB_PORT",
            "AP_DB_NAME",
        ):
            monkeypatch.delenv(key, raising=False)
        assert database_url() == "postgresql://ap:change-me@127.0.0.1:5433/ap"


class TestSafeUrl:
    def test_hides_the_password(self):
        assert safe_url("postgresql://ap:secret@127.0.0.1:5433/ap") == (
            "postgresql://ap:***@127.0.0.1:5433/ap"
        )

    def test_no_password_is_unchanged(self):
        assert safe_url("postgresql://127.0.0.1:5433/ap") == "postgresql://127.0.0.1:5433/ap"


class TestStackDatabaseUrl:
    """`make up` publishes the stack's Postgres on the Mac at 127.0.0.1:5434."""

    def test_same_credentials_and_database_on_the_stack_port(self, monkeypatch):
        monkeypatch.delenv("AP_STACK_DB_PORT", raising=False)
        url = stack_database_url("postgresql://ap:p%40ss@postgres:5432/ap")
        assert url == "postgresql://ap:p%40ss@127.0.0.1:5434/ap"

    def test_the_port_can_be_moved(self, monkeypatch):
        monkeypatch.setenv("AP_STACK_DB_PORT", "6000")
        assert stack_database_url("postgresql://ap:x@127.0.0.1:5433/ap") == (
            "postgresql://ap:x@127.0.0.1:6000/ap"
        )

    def test_use_stack_database_points_connect_at_it(self, monkeypatch):
        monkeypatch.setattr("invoiceflow.store.connection.load_env_file", lambda: {})
        monkeypatch.delenv("AP_STACK_DB_PORT", raising=False)
        monkeypatch.setenv("AP_DATABASE_URL", "postgresql://ap:x@127.0.0.1:5433/ap")
        assert use_stack_database() == "postgresql://ap:x@127.0.0.1:5434/ap"
        assert database_url() == "postgresql://ap:x@127.0.0.1:5434/ap"
