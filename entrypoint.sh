#!/bin/bash
# entrypoint.sh — run migrations then start the server
set -e

mkdir -p /app/logs

if [ -f alembic.ini ]; then
    echo "Running Alembic migrations..."
    alembic upgrade head
fi

echo "Starting Workbench server..."
exec uvicorn workbench.main:app --host 0.0.0.0 --port 8421
