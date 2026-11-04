#!/usr/bin/env bash
# Snapshot the demo state: pg_dump the ``ap`` database and tar ``data/``.
# Requires the full stack (`make up`). Usage: scripts/snapshot.sh [name]
set -euo pipefail

COMPOSE="${COMPOSE:-docker-compose}"
NAME="${1:-demo}"
SNAP_DIR="${SNAPSHOT_DIR:-snapshots}"
AP_USER="${AP_DB_USER:-ap}"
AP_DB="${AP_DB_NAME:-ap}"

mkdir -p "$SNAP_DIR"

echo "snapshot: dumping the ap database..."
"$COMPOSE" exec -T postgres pg_dump -U "$AP_USER" -d "$AP_DB" --no-owner --no-privileges \
  > "$SNAP_DIR/$NAME.sql"

echo "snapshot: archiving data/ ..."
tar -czf "$SNAP_DIR/$NAME.data.tgz" data/

echo "snapshot saved: $SNAP_DIR/$NAME.sql + $SNAP_DIR/$NAME.data.tgz"
