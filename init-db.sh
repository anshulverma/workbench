#!/bin/bash
# init-db.sh — creates workbench and memory databases on first PG start
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER workbench WITH PASSWORD 'workbench';
    CREATE DATABASE workbench OWNER workbench;

    CREATE USER memory WITH PASSWORD 'memory';
    CREATE DATABASE memory OWNER memory;

    -- Grant connect permissions
    GRANT ALL PRIVILEGES ON DATABASE workbench TO workbench;
    GRANT ALL PRIVILEGES ON DATABASE memory TO memory;
EOSQL
