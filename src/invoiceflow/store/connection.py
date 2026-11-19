"""Postgres connection handling for the ``ap`` database (WS6 production store).

Reads ``AP_DATABASE_URL`` or the ``AP_DB_*`` parts from the environment/``.env``. The dev
database defaults to the ``compose.dev.yaml`` service on 127.0.0.1:5433; the full stack sets
``AP_DATABASE_URL`` to point at the ``postgres`` service inside the Docker network.
"""

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
STACK_PORT_ENV = "AP_STACK_DB_PORT"
DEFAULT_STACK_PORT = "5434"  # where `make up` publishes the stack's Postgres on the Mac


def database_url() -> str:
    """``AP_DATABASE_URL`` if set, otherwise the parts ``compose.dev.yaml`` uses."""
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


def stack_database_url(url: str) -> str:
    """``url`` with its host and port moved to the full stack's Postgres on the Mac."""
    parts = urlsplit(url)
    credentials = parts.netloc.rpartition("@")[0]
    port = os.environ.get(STACK_PORT_ENV, DEFAULT_STACK_PORT)
    return urlunsplit(parts._replace(netloc=f"{credentials}@{DEFAULT_HOST}:{port}"))


def use_stack_database() -> str:
    """Point ``connect`` at the full stack's database instead of the dev one (``STACK=1``)."""
    url = stack_database_url(database_url())
    os.environ["AP_DATABASE_URL"] = url
    return url


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
