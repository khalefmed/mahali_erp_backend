#!/bin/sh
# Runs once, when the Postgres volume is created.
# The app connects as APP_DB_USER: NOT a superuser and NOBYPASSRLS, so row-level
# security applies to every query it makes (tables use FORCE ROW LEVEL SECURITY).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}' NOSUPERUSER NOBYPASSRLS CREATEDB;
CREATE DATABASE ${APP_DB_NAME} OWNER ${APP_DB_USER};
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${APP_DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS unaccent; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
