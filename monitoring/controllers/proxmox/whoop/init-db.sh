#!/bin/sh
set -eu
# This file is sourced by the official image on first initialization only.
# Read the password inside psql; never put it in command arguments or logs.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv reader_password WHOOP_READER_PASSWORD
CREATE ROLE whoop_grafana LOGIN PASSWORD :'reader_password';
ALTER ROLE whoop_grafana SET default_transaction_read_only = on;
REVOKE ALL ON DATABASE whoop FROM PUBLIC;
GRANT CONNECT ON DATABASE whoop TO whoop_grafana;
SQL
