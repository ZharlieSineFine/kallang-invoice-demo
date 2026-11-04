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

SQL = (repo_root() / "db" / "migrations" / "001_init.sql").read_text()

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


def test_export_once_is_enforced_by_the_database():
    assert re.search(r"doc_id\s+uuid NOT NULL UNIQUE REFERENCES documents", SQL)


def test_events_are_append_only():
    assert "BEFORE UPDATE OR DELETE ON events" in SQL
