#!/bin/bash
# entrypoint.sh — run migrations then start the server
set -e

export WORKBENCH_LOG_DIR=${WORKBENCH_LOG_DIR:-/app/logs}
mkdir -p "$WORKBENCH_LOG_DIR"

if [ -f alembic.ini ]; then
    echo "Running Alembic migrations..."
    alembic upgrade head
fi

echo "Starting Workbench server (logs: $WORKBENCH_LOG_DIR)..."
exec uvicorn workbench.main:app --host 0.0.0.0 --port 8421
