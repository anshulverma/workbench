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
# Launch via `python -m workbench` so host/port/reload come from config
# (config.server.host defaults to loopback; reached via the SSH tunnel).
exec "$PROJECT_DIR/.venv/bin/python" -m workbench \
    2>&1 | tee -a "$PROJECT_DIR/logs/workbench.log"
