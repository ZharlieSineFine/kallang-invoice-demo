#!/usr/bin/env python
"""Apply pending migrations to the dev database. Run: make db-dev."""

from __future__ import annotations

import sys

import psycopg

from invoiceflow.store.connection import connect, database_url, safe_url
from invoiceflow.store.migrate import apply_migrations


def main() -> int:
    try:
        with connect() as conn:
            applied = apply_migrations(conn)
    except psycopg.OperationalError as exc:
        print(f"cannot reach Postgres at {safe_url(database_url())}:", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        print("start it with `make db-dev`, or set AP_DATABASE_URL.", file=sys.stderr)
        return 1
    if applied:
        print(f"applied: {', '.join(applied)}")
    else:
        print("database already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
