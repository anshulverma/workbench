#!/bin/bash
# init-db.sh — creates workbench and zep databases on first PG start
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER workbench WITH PASSWORD 'workbench';
    CREATE DATABASE workbench OWNER workbench;

    CREATE USER zep WITH PASSWORD 'zep';
    CREATE DATABASE zep OWNER zep;

    -- Grant connect permissions
    GRANT ALL PRIVILEGES ON DATABASE workbench TO workbench;
    GRANT ALL PRIVILEGES ON DATABASE zep TO zep;
EOSQL
