#!/bin/bash
# entrypoint.sh — run migrations then start the server
set -e

if [ -f alembic.ini ]; then
    echo "Running Alembic migrations..."
    alembic upgrade head
else
    echo "No alembic.ini found, skipping migrations"
fi

echo "Starting Workbench server..."
exec uvicorn workbench.main:app --host 0.0.0.0 --port 8421
