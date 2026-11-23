"""The SQL schema must agree with the Python enums, or saving a record fails at runtime."""

import re

import pytest

from invoiceflow.contracts import (
    CodingSource,
    Confidence,
    DocStatus,
    DocType,
    LLMMode,
    MatchType,
    ReviewAction,
    Scope,
    Severity,
    Stage,
    TextSource,
    ValueSource,
)
from invoiceflow.settings import repo_root

MIGRATIONS = repo_root() / "db" / "migrations"
SQL = (MIGRATIONS / "001_init.sql").read_text()

ENUM_CHECKS = {
    "ck_documents_status": DocStatus,
    "ck_documents_doc_type": DocType,
    "ck_pages_text_source": TextSource,
    "ck_extractions_mode": LLMMode,
    "ck_fields_match_type": MatchType,
    "ck_fields_confidence": Confidence,
    "ck_fields_source": ValueSource,
    "ck_line_items_source": ValueSource,
    "ck_coding_lines_coding_source": CodingSource,
    "ck_findings_severity": Severity,
    "ck_findings_scope": Scope,
    "ck_findings_stage": Stage,
    "ck_reviews_action": ReviewAction,
}

TABLES = [
    "schema_migrations",
    "gl_accounts",
    "cost_centers",
    "tax_codes",
    "venue_cost_centers",
    "vendors",
    "purchase_orders",
    "bronze_files",
    "documents",
    "pages",
    "extractions",
    "fields",
    "line_items",
    "coding_lines",
    "findings",
    "reviews",
    "export_batches",
    "export_rows",
    "notifications",
    "events",
]


def _check_values(name: str) -> set[str]:
    match = re.search(rf"CONSTRAINT {name} CHECK \(\w+ IN \(([^)]*)\)\)", SQL)
    assert match, f"constraint {name} not found"
    return {v.strip().strip("'") for v in match.group(1).split(",")}


@pytest.mark.parametrize(("constraint", "enum"), ENUM_CHECKS.items())
def test_check_constraint_matches_enum(constraint, enum):
    assert _check_values(constraint) == {e.value for e in enum}


@pytest.mark.parametrize("table", TABLES)
def test_table_exists(table):
    assert re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{table} \(", SQL), table


def test_an_invoice_can_be_exported_again_but_once_per_batch():
    # 001 made doc_id unique (one export per invoice); 003 drops that so an invoice can be
    # sent again (user's request, 2026-11-20). The primary key still allows one row per batch.
    later = (MIGRATIONS / "003_export_history.sql").read_text(encoding="utf-8")
    assert "DROP CONSTRAINT IF EXISTS export_rows_doc_id_key" in later
    assert "PRIMARY KEY (batch_id, doc_id)" in SQL


def test_events_are_append_only():
    assert "BEFORE UPDATE OR DELETE ON events" in SQL
