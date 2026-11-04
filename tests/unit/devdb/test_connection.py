"""Reads the .env file and builds the dev database URL."""

import os

import pytest

from invoiceflow.devdb.connection import database_url, safe_url
from invoiceflow.settings import load_env_file


class TestEnvFile:
    def test_reads_values_and_strips_comments(self, monkeypatch, tmp_path):
        path = tmp_path / ".env"
        path.write_text(
            "# a comment\n"
            "\n"
            "AP_DB_USER=ap\n"
            "export AP_DB_PASSWORD='s3cret # still the password'\n"
            "LLM_MODE=live   # live | replay\n",
            encoding="utf-8",
        )
        for key in ("AP_DB_USER", "AP_DB_PASSWORD", "LLM_MODE"):
            monkeypatch.delenv(key, raising=False)

        loaded = load_env_file(path)

        assert loaded == {
            "AP_DB_USER": "ap",
            "AP_DB_PASSWORD": "s3cret # still the password",
            "LLM_MODE": "live",
        }
        assert os.environ["LLM_MODE"] == "live"

    def test_real_environment_wins(self, monkeypatch, tmp_path):
        path = tmp_path / ".env"
        path.write_text("AP_DB_USER=fromfile\n", encoding="utf-8")
        monkeypatch.setenv("AP_DB_USER", "fromenv")

        assert load_env_file(path) == {}
        assert os.environ["AP_DB_USER"] == "fromenv"

    def test_missing_file_is_fine(self, tmp_path):
        assert load_env_file(tmp_path / ".env") == {}


class TestDatabaseUrl:
    @pytest.fixture(autouse=True)
    def _ignore_the_repo_env_file(self, monkeypatch):
        # A developer's real .env must not leak into these assertions.
        monkeypatch.setattr("invoiceflow.devdb.connection.load_env_file", lambda: {})

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

    def test_safe_url_hides_the_password(self):
        assert safe_url("postgresql://ap:secret@127.0.0.1:5433/ap") == (
            "postgresql://ap:***@127.0.0.1:5433/ap"
        )
        assert safe_url("postgresql://127.0.0.1:5433/ap") == "postgresql://127.0.0.1:5433/ap"
