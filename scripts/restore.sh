#!/usr/bin/env bash
# Restore a snapshot taken by scripts/snapshot.sh. Usage: scripts/restore.sh [name]
set -euo pipefail

COMPOSE="${COMPOSE:-docker-compose}"
NAME="${1:-demo}"
SNAP_DIR="${SNAPSHOT_DIR:-snapshots}"
AP_USER="${AP_DB_USER:-ap}"
AP_DB="${AP_DB_NAME:-ap}"

[ -f "$SNAP_DIR/$NAME.sql" ] || { echo "no snapshot at $SNAP_DIR/$NAME.sql"; exit 1; }

echo "restore: loading the ap database..."
"$COMPOSE" exec -T postgres psql -v ON_ERROR_STOP=1 -U "$AP_USER" -d "$AP_DB" \
  < "$SNAP_DIR/$NAME.sql"

if [ -f "$SNAP_DIR/$NAME.data.tgz" ]; then
  echo "restore: extracting data/ ..."
  tar -xzf "$SNAP_DIR/$NAME.data.tgz"
fi

echo "restored from snapshot '$NAME'"
