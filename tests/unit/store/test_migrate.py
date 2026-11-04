"""Migration runner: file discovery and the tracking table, without a database."""

from invoiceflow.store.migrate import LOCK_ID, TRACKING_TABLE, migration_files


def test_migration_files_are_sorted_sql():
    files = migration_files()
    assert files
    assert [f.name for f in files] == sorted(f.name for f in files)
    assert all(f.suffix == ".sql" for f in files)
    assert "001_init.sql" in {f.name for f in files}


def test_tracking_table_creates_schema_migrations():
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in TRACKING_TABLE
    assert "version" in TRACKING_TABLE


def test_lock_id_is_positive():
    assert LOCK_ID > 0
