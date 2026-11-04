#!/usr/bin/env bash
# DAG import test: list the DAGs and fail if any of them has an import error.
# Requires the full stack (`make up`).
set -euo pipefail

COMPOSE="${COMPOSE:-docker-compose}"

echo "DAGs the scheduler sees:"
"$COMPOSE" exec -T airflow-scheduler airflow dags list || true

echo
echo "Import errors (must be empty):"
errors=$("$COMPOSE" exec -T airflow-scheduler airflow dags list-import-errors 2>&1) || true
printf '%s\n' "$errors"

if printf '%s\n' "$errors" | grep -qiE 'error|traceback|exception|cannot import|no module'; then
  echo "check_dags: import errors found" >&2
  exit 1
fi

echo "check_dags: clean"
