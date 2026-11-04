"""Phase 0 dev-database helpers: connect, migrate, and load the golden fixtures.

This is scaffolding, not the production repository. WS6 replaces it with
``invoiceflow.store`` and ``invoiceflow.storage`` behind the ``Repository`` protocol.
Keeping it here means WS6 and WS7 have a real database before the full stack exists.
"""

from invoiceflow.devdb.connection import connect, database_url, safe_url
from invoiceflow.devdb.fixtures import LoadReport, load_fixtures
from invoiceflow.devdb.migrate import apply_migrations, migration_files

__all__ = [
    "LoadReport",
    "apply_migrations",
    "connect",
    "database_url",
    "load_fixtures",
    "migration_files",
    "safe_url",
]
