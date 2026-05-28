#!/bin/bash
# Start script for the Workbench server. Called by systemd.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

source "$SCRIPT_DIR/workbench-env.sh"

# Get a fresh Anthropic API key (rotated automatically)
export WORKBENCH_ANTHROPIC_API_KEY=$(/usr/local/bin/claude_code/api-key-helper)

# Ensure data directory exists
mkdir -p "$PROJECT_DIR/data"

mkdir -p "$PROJECT_DIR/logs"
exec "$PROJECT_DIR/.venv/bin/python" -m uvicorn workbench.main:app \
    --host 0.0.0.0 \
    --port "$WORKBENCH_PORT" \
    2>&1 | tee -a "$PROJECT_DIR/logs/workbench.log"
