#!/usr/bin/env zsh
# E2E Setup — Pull images and start the stack
# Run this from your shell (not from Claude Code sandbox):
#   ! bash scripts/e2e-setup.sh
set -e

echo "=== Step 1: Pull PostgreSQL image ==="
export HTTPS_PROXY=http://fwdproxy:8080 HTTP_PROXY=http://fwdproxy:8080

# Try ghcr.io/getzep/postgres first (has pgvector), fall back to standard postgres
if ! podman image exists ghcr.io/getzep/postgres:latest 2>/dev/null; then
    echo "Pulling ghcr.io/getzep/postgres:latest..."
    if ! podman pull ghcr.io/getzep/postgres:latest 2>/dev/null; then
        echo "ghcr.io blocked. Pulling docker.io/postgres:16 instead..."
        podman pull docker.io/library/postgres:16
        # Tag it so docker-compose.yml reference works
        podman tag docker.io/library/postgres:16 ghcr.io/getzep/postgres:latest
    fi
fi
echo "Image ready: $(podman images ghcr.io/getzep/postgres:latest --format '{{.Repository}}:{{.Tag}}')"

echo ""
echo "=== Step 2: Start PostgreSQL ==="
podman compose up -d postgres

echo ""
echo "=== Step 3: Wait for PG to initialize ==="
sleep 5

echo ""
echo "=== Step 4: Verify databases ==="
podman exec $(podman ps -q --filter name=postgres) psql -U postgres -c "\l"

echo ""
echo "=== Step 5: Install Python deps in venv ==="
if [ ! -f /tmp/workbench-venv/bin/pip ]; then
    python3 -m venv /tmp/workbench-venv
fi
/tmp/workbench-venv/bin/pip install -e ".[dev]" -q

echo ""
echo "=== Step 6: Run Alembic migration ==="
/tmp/workbench-venv/bin/alembic upgrade head

echo ""
echo "=== Step 7: Verify tables ==="
podman exec $(podman ps -q --filter name=postgres) psql -U workbench -d workbench -c "\dt"

echo ""
echo "=== Step 8: Run tests ==="
/tmp/workbench-venv/bin/python3 -m pytest tests/ -v --tb=short

echo ""
echo "=== Setup complete! ==="
echo "PostgreSQL running, tables created, tests executed."
echo "To start the workbench server:"
echo "  /tmp/workbench-venv/bin/python3 -m uvicorn workbench.main:app --host 0.0.0.0 --port 8421"
