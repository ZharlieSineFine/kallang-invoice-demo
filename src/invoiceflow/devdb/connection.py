"""Connecting to the dev Postgres (compose.dev.yaml) from ``.env`` or the environment."""

from __future__ import annotations

import os
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg

from invoiceflow.settings import load_env_file

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "5433"
DEFAULT_USER = "ap"
DEFAULT_PASSWORD = "change-me"
DEFAULT_NAME = "ap"


def database_url() -> str:
    """``AP_DATABASE_URL`` if set, otherwise the parts that compose.dev.yaml uses."""
    load_env_file()
    explicit = os.environ.get("AP_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    user = os.environ.get("AP_DB_USER", DEFAULT_USER)
    password = os.environ.get("AP_DB_PASSWORD", DEFAULT_PASSWORD)
    host = os.environ.get("AP_DB_HOST", DEFAULT_HOST)
    port = os.environ.get("AP_DB_PORT", DEFAULT_PORT)
    name = os.environ.get("AP_DB_NAME", DEFAULT_NAME)
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{name}"


def safe_url(url: str) -> str:
    """The URL with any password replaced by ``***``, for logs and error messages."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    user = f"{parts.username}:***@" if parts.username else ""
    return urlunsplit((parts.scheme, f"{user}{host}", parts.path, parts.query, parts.fragment))


def connect(connect_timeout: int = 3, autocommit: bool = False) -> psycopg.Connection:
    """Open a connection. A short timeout keeps a missing database from hanging a test run."""
    return psycopg.connect(database_url(), connect_timeout=connect_timeout, autocommit=autocommit)
