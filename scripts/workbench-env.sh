#!/bin/bash
# Environment variables for the Workbench server.
# Sourced by the systemd service and the management script.

export WORKBENCH_API_TOKEN="${WORKBENCH_API_TOKEN:-dev-token}"
export WORKBENCH_STORAGE_BACKEND=sqlite
export WORKBENCH_SQLITE_PATH=/home/anshulverma/workspace/workbench/data/workbench.db
export WORKBENCH_ANTHROPIC_BASE_URL=https://plugboard.x2p.facebook.net
export WORKBENCH_GCHAT_SPACE_ID=AAQA-RI-cA4
export WORKBENCH_GOOGLE_API_SCRIPT=/home/anshulverma/workspace/workbench/server/lib/google_api.py
export WORKBENCH_PORT=8421
export PYTHONPATH=/home/anshulverma/workspace/workbench
