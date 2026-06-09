#!/bin/bash
# entrypoint.sh — run migrations then start the server
set -e

export WORKBENCH_LOG_DIR=${WORKBENCH_LOG_DIR:-/app/logs}
mkdir -p "$WORKBENCH_LOG_DIR"

if [ -f alembic.ini ]; then
    echo "Running Alembic migrations..."
    alembic upgrade head
fi

# Bind loopback by default (reached via SSH tunnel); override WORKBENCH_HOST for LAN access.
echo "Starting Workbench server (logs: $WORKBENCH_LOG_DIR)..."
exec uvicorn workbench.runtime.app:app --host "${WORKBENCH_HOST:-127.0.0.1}" --port "${WORKBENCH_PORT:-8421}"
