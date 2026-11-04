#!/usr/bin/env python
"""Load the golden fixtures into the dev database. Run: make db-dev && make fixtures."""

from __future__ import annotations

import sys

import psycopg

from invoiceflow.devdb.connection import connect, database_url, safe_url
from invoiceflow.devdb.fixtures import load_fixtures
from invoiceflow.devdb.migrate import apply_migrations


def main() -> int:
    try:
        with connect() as conn, conn.transaction():
            apply_migrations(conn)
            report = load_fixtures(conn)
    except psycopg.OperationalError as exc:
        print(f"cannot reach Postgres at {safe_url(database_url())}:", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        print("start it with `make db-dev`, or set AP_DATABASE_URL.", file=sys.stderr)
        return 1
    print(report.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
