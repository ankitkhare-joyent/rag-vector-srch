#!/bin/sh
# docker-entrypoint-initdb.d hook: create the `rag` database and apply the schema.
set -eu
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE rag"
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d rag \
     -v bao_admin_password="$BAO_ADMIN_INITIAL_PASSWORD" -f /sql/001_schema.sql
