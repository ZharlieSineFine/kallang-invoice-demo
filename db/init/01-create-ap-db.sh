#!/bin/bash
# Creates the second database (``ap``) and its role inside the full-stack Postgres.
# Runs once, when the postgres-db-volume is first initialised. The ``airflow`` database
# itself is created by the official image's POSTGRES_DB setting.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${AP_DB_USER}') THEN
            CREATE ROLE "${AP_DB_USER}" LOGIN PASSWORD '${AP_DB_PASSWORD}';
        END IF;
    END
    \$\$;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE "${AP_DB_NAME}" OWNER "${AP_DB_USER}"'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${AP_DB_NAME}')\gexec
EOSQL
