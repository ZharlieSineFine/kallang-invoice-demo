#!/usr/bin/env bash
# Wipe the demo state: truncate the ap tables and clear data/.
# Requires the full stack (`make up`).
set -euo pipefail

COMPOSE="${COMPOSE:-docker-compose}"
AP_USER="${AP_DB_USER:-ap}"
AP_DB="${AP_DB_NAME:-ap}"

TABLES="events, notifications, export_rows, export_batches, reviews, findings, coding_lines, \
line_items, fields, extractions, pages, documents, bronze_files, venue_cost_centers, \
purchase_orders, vendors, tax_codes, cost_centers, gl_accounts"

echo "reset: truncating the ap database..."
"$COMPOSE" exec -T postgres psql -v ON_ERROR_STOP=1 -U "$AP_USER" -d "$AP_DB" \
  -c "TRUNCATE TABLE $TABLES RESTART IDENTITY CASCADE"

echo "reset: clearing data/ ..."
rm -rf data/bronze data/silver data/gold data/inbox data/processed
mkdir -p data/inbox

echo "reset done"
