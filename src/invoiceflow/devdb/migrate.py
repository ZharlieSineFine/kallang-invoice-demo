"""Apply ``db/migrations/*.sql`` in order, once each, tracked in ``schema_migrations``.

The runner is deliberately small. WS6 owns the production version.
"""

from __future__ import annotations

from pathlib import Path

from psycopg import Connection, Cursor

from invoiceflow.settings import repo_root

# One migrator at a time, even if two shells run ``make db-dev`` together.
LOCK_ID = 727_001

TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     text PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


def migration_files() -> tuple[Path, ...]:
    return tuple(sorted((repo_root() / "db" / "migrations").glob("*.sql")))


def applied_versions(conn: Connection) -> tuple[str, ...]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        return tuple(row[0] for row in cur.fetchall())


def apply_migrations(conn: Connection) -> tuple[str, ...]:
    """Apply every pending migration in one transaction. Returns the versions applied.

    Calling this on an up-to-date database is a no-op. Nested inside a caller's
    transaction it becomes a savepoint, so a test can roll the whole thing back.
    """
    newly: list[str] = []
    with conn.transaction(), conn.cursor() as cur:
        _lock(cur)
        cur.execute(TRACKING_TABLE)
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
        for path in migration_files():
            version = path.stem
            if version in applied:
                continue
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            newly.append(version)
    return tuple(newly)


def _lock(cur: Cursor) -> None:
    """Session lock; released when the connection closes, even after an error."""
    cur.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
