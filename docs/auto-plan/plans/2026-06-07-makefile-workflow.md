# Makefile Developer Workflow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `make` the single developer interface for workbench/ and remove the `workbench` console script (`serve` → `python -m workbench`, `triage` → `scripts/triage.py`), in lockstep with workbench-meta.

**Architecture:** Two thin Python entrypoints (`src/workbench/__main__.py`, `scripts/triage.py`) replace `cli.py`; the base `Makefile` exposes every action; the base `Dockerfile` UI path is fixed so `make build` serves `/ui`; workbench-meta aligns its host `ui-build` step and container launch.

**Tech Stack:** GNU Make, Python 3.12 (uvicorn, argparse, httpx), ruff, docker/podman compose, Vite/npm (UI), Alembic.

**Test commands:**
- Backend tests: `$(HOME)/.venv/workbench/bin/python -m pytest tests/ -q` (or `make test`)
- Single test: `.venv/bin/python -m pytest tests/test_config.py::test_x -q`
- UI build/test: `cd ui && npm run build` / `npm run test`
- Lint: `make lint`  ·  Migrations: `make migrate`
- Server smoke: `make serve` then `curl -s localhost:8421/health`

> Toolchain note: UI/npm targets need the real Node on PATH (`~/.local/nodejs/shim`) and `with-proxy` for registry installs; `npm run build`/`test` need no network. The project venv is `~/.venv/workbench` (per `make setup`); examples below use `.venv/bin/python` where a repo-local venv exists — use whichever your environment has and keep it consistent.

---

## File Structure

- **Create** `src/workbench/__main__.py` — `python -m workbench` server launcher.
- **Create** `scripts/triage.py` — terminal triage (moved from cli.py).
- **Modify** `Makefile`, `pyproject.toml`, `Dockerfile`, `scripts/workbench-start.sh`, `src/workbench/providers/messenger/console.py`, `README.md`, `CLAUDE.md`, `docs/adr/0001-messenger-as-notification-only.md`.
- **Delete** `src/workbench/cli.py`.
- **Modify (workbench-meta)** `Makefile`, `docker-compose.override.yml`.

---

## Task 1: Server launcher `python -m workbench`

**Files:**
- Create: `src/workbench/__main__.py`
- Test: `tests/test_entrypoint.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_entrypoint.py
import importlib
from unittest.mock import patch
import workbench.__main__ as wm


def test_main_binds_config_server_host(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        'version: "0.1.0"\n'
        "server: {host: 1.2.3.4, port: 9999}\n"
        "storage: {postgres_dsn: postgres://x}\n"
        "llm: {class: workbench.providers.llm.anthropic.AnthropicLLM, api_key: k, model: m}\n"
    )
    monkeypatch.setenv("WORKBENCH_CONFIG", str(cfg))
    monkeypatch.delenv("WORKBENCH_CONFIG_OVERRIDE", raising=False)
    with patch("uvicorn.run") as run:
        wm.main()
    kwargs = run.call_args.kwargs
    assert kwargs["host"] == "1.2.3.4"
    assert kwargs["port"] == 9999
```

- [ ] **Step 2: Run test to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_entrypoint.py -q`
Expected: `ModuleNotFoundError: No module named 'workbench.__main__'` (collection error).

- [ ] **Step 3: Write minimal implementation**
```python
# src/workbench/__main__.py
"""`python -m workbench` — start the Workbench server (replaces `workbench serve`)."""
from __future__ import annotations

import os

import uvicorn

from workbench.config import load_config


def main() -> None:
    config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")
    override_path = os.environ.get("WORKBENCH_CONFIG_OVERRIDE")
    config = load_config(config_path, override_path)
    uvicorn.run(
        "workbench.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.debug,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_entrypoint.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Commit**
`git add src/workbench/__main__.py tests/test_entrypoint.py && git commit -m "feat(serve): python -m workbench launcher honoring config.server.host"`

---

## Task 2: Terminal triage `scripts/triage.py`

**Files:**
- Create: `scripts/triage.py`
- Test: `tests/test_triage_script.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_triage_script.py
import runpy
import sys
from unittest.mock import patch
import httpx


def test_triage_lists_and_responds(monkeypatch, capsys):
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "triage_script", pathlib.Path("scripts/triage.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    cards = [{"id": "c1", "card_content": {"source_type": "github", "summary": "PR #1"},
              "options": [{"label": "Add todo", "action": "add_todo"}]}]
    with patch.object(httpx, "get", return_value=httpx.Response(200, json=cards)), \
         patch.object(httpx, "post", return_value=httpx.Response(200, json={"action": "add_todo"})), \
         patch("builtins.input", return_value="1"):
        mod.triage("http://localhost:8421", "tok")
    out = capsys.readouterr().out
    assert "PR #1" in out and "add_todo" in out
```

- [ ] **Step 2: Run test to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_triage_script.py -q`
Expected: `FileNotFoundError`/spec error for `scripts/triage.py`.

- [ ] **Step 3: Write minimal implementation** — move `triage()` from `cli.py` verbatim, add an argparse `main`:
```python
#!/usr/bin/env python3
"""Terminal triage (replaces `workbench triage`). Run via `make triage`."""
from __future__ import annotations

import argparse
import os
import sys

import httpx


def triage(server_url: str, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = httpx.get(f"{server_url}/api/triage/pending", headers=headers)
    if resp.status_code != 200:
        print(f"Error: {resp.status_code} {resp.text}")
        return
    cards = resp.json()
    if not cards:
        print("No pending triage cards.")
        return
    print(f"\n{len(cards)} card(s) pending triage.\n")
    for i, card in enumerate(cards):
        content = card.get("card_content", {})
        options = card.get("options", [])
        print(f"--- Card {i + 1}/{len(cards)} ---")
        print(f"[{content.get('source_type', 'unknown')}] {content.get('summary', 'Unknown item')}")
        print()
        for j, opt in enumerate(options, 1):
            print(f"  {j}. {opt['label']}")
        print("  s. Skip remaining\n")
        choice = input("Your choice: ").strip().lower()
        if choice == "s":
            print("Skipped remaining cards.")
            break
        try:
            n = int(choice)
            if 1 <= n <= len(options):
                r = httpx.post(f"{server_url}/api/triage/respond", headers=headers,
                               json={"card_id": card["id"], "choice": n})
                print(f"  -> {r.json().get('action', 'unknown')}\n" if r.status_code == 200
                      else f"  Error: {r.status_code}\n")
            else:
                print("  Invalid choice. Skipping.\n")
        except ValueError:
            print("  Invalid input. Skipping.\n")


def main() -> None:
    p = argparse.ArgumentParser(prog="triage", description="Interactive terminal triage")
    p.add_argument("--server", default="http://localhost:8421")
    p.add_argument("--token", default=None)
    args = p.parse_args()
    token = args.token or os.environ.get("WORKBENCH_API_TOKEN", "")
    if not token:
        print("Error: --token or WORKBENCH_API_TOKEN required", file=sys.stderr)
        sys.exit(1)
    triage(args.server, token)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_triage_script.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Commit**
`git add scripts/triage.py tests/test_triage_script.py && git commit -m "feat(triage): scripts/triage.py terminal triage (moved from cli.py)"`

---

## Task 3: Remove the `workbench` console script

**Files:**
- Delete: `src/workbench/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_no_console_script.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_no_console_script.py
import tomllib, pathlib


def test_no_console_script_declared():
    data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
    assert "scripts" not in data.get("project", {}), "remove [project.scripts]"


def test_cli_module_gone():
    assert not pathlib.Path("src/workbench/cli.py").exists()
```

- [ ] **Step 2: Run test to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_no_console_script.py -q`
Expected: both fail (`[project.scripts]` present, `cli.py` exists).

- [ ] **Step 3: Write minimal implementation**
Remove the `[project.scripts]` table (the two lines `[project.scripts]` and `workbench = "workbench.cli:main"`) from `pyproject.toml`, then `git rm src/workbench/cli.py`.

- [ ] **Step 4: Run test to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_no_console_script.py tests/ -q`
Expected: `test_no_console_script.py` passes; full suite shows no NEW failures (6 pre-existing unrelated failures remain; confirm count unchanged via `git stash` if unsure).

- [ ] **Step 5: Commit**
`git add pyproject.toml tests/test_no_console_script.py && git rm src/workbench/cli.py && git commit -m "refactor: remove workbench console script (cli.py + [project.scripts])"`

---

## Task 4: Add `ruff` + lint/format

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing test (validation)**
Run: `grep -q '"ruff' pyproject.toml && echo HAS || echo MISSING`
Expected: `MISSING`.

- [ ] **Step 2: Add ruff to dev deps**
In `pyproject.toml` `[project.optional-dependencies].dev`, add `"ruff>=0.6"`.

- [ ] **Step 3: Install + verify**
Run: `.venv/bin/pip install -e ".[dev]" -q && .venv/bin/python -m ruff --version`
Expected: prints a ruff version.

- [ ] **Step 4: Verify lint runs**
Run: `.venv/bin/python -m ruff check src/ tests/ scripts/ || true`
Expected: ruff runs (findings allowed; the target exists in Task 5).

- [ ] **Step 5: Commit**
`git add pyproject.toml && git commit -m "build: add ruff to dev deps for make lint/format"`

---

## Task 5: Rewrite the base `Makefile` (full target set)

**Files:**
- Modify: `Makefile`
- Test: `tests/test_makefile_targets.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_makefile_targets.py
import subprocess


def _targets():
    out = subprocess.run(["make", "-qp"], capture_output=True, text=True).stdout
    return {l.split(":")[0] for l in out.splitlines() if l and not l.startswith("\t") and ":" in l and "=" not in l.split(":")[0]}


def test_required_targets_present():
    required = {"setup", "ui-setup", "ui-build", "ui-test", "gen-api", "build", "up",
                "down", "serve", "test", "migrate", "lint", "format", "logs", "health",
                "triage", "clean"}
    assert required <= _targets(), required - _targets()
```

- [ ] **Step 2: Run test to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_makefile_targets.py -q`
Expected: fails — missing `serve`, `ui-build`, `ui-setup`, `ui-test`, `gen-api`, `lint`, `format`, `clean`.

- [ ] **Step 3: Write the Makefile**
```make
COMPOSE := docker compose
COMPOSE_FILES ?= -f docker-compose.yml
PYTHON ?= $(HOME)/.venv/workbench/bin/python
PIP ?= $(HOME)/.venv/workbench/bin/pip
EXCLUDE ?= dcat
WORKBENCH_API_TOKEN ?= change-me

.PHONY: setup ui-setup ui-build ui-test gen-api build up down serve test migrate lint format logs health triage clean

setup:
	python3 -m venv $(HOME)/.venv/workbench
	$(PIP) install -e ".[dev]"
	@echo "Activate with: source ~/.venv/workbench/bin/activate"

ui-setup:
	cd ui && npm install

ui-build:
	cd ui && npm run build

ui-test:
	cd ui && npm run test

gen-api:
	cd ui && npm run gen:api

build: ui-build
	$(COMPOSE) $(COMPOSE_FILES) build

up: build
	$(COMPOSE) $(COMPOSE_FILES) up -d

down:
	$(COMPOSE) $(COMPOSE_FILES) down

serve:
	$(PYTHON) -m workbench

test:
	$(PYTHON) -m pytest tests/ -v --tb=short

migrate:
	$(PYTHON) -m alembic upgrade head

lint:
	$(PYTHON) -m ruff check src/ tests/ scripts/

format:
	$(PYTHON) -m ruff format src/ tests/ scripts/

logs:
	$(PYTHON) scripts/logview.py data/logs $(if $(EXCLUDE),--exclude $(EXCLUDE))

health:
	@curl -s http://localhost:8421/health | python3 -m json.tool

triage:
	$(PYTHON) scripts/triage.py --token $(WORKBENCH_API_TOKEN)

clean:
	rm -rf ui/dist .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
```

- [ ] **Step 4: Run test to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_makefile_targets.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Commit**
`git add Makefile tests/test_makefile_targets.py && git commit -m "build(make): full developer target set (serve, ui-*, lint, format, clean, gen-api)"`

---

## Task 6: Fix Dockerfile UI path + systemd start script

**Files:**
- Modify: `Dockerfile`, `scripts/workbench-start.sh`

- [ ] **Step 1: Verify the bug**
Run: `grep -n 'ui-dist\|ui/dist' Dockerfile`
Expected: shows `COPY --from=ui-builder /ui/dist /app/ui-dist` (wrong target).

- [ ] **Step 2: Fix the Dockerfile copy path**
Change `COPY --from=ui-builder /ui/dist /app/ui-dist` → `COPY --from=ui-builder /ui/dist /app/ui/dist`.

- [ ] **Step 3: Align the systemd start script**
In `scripts/workbench-start.sh`, replace the `exec ... -m uvicorn workbench.main:app --host 0.0.0.0 --port "$WORKBENCH_PORT" ...` line with:
`exec "$PROJECT_DIR/.venv/bin/python" -m workbench 2>&1 | tee -a "$PROJECT_DIR/logs/workbench.log"`

- [ ] **Step 4: Verify**
Run: `grep -n '/app/ui/dist' Dockerfile && grep -n 'python -m workbench\|-m workbench' scripts/workbench-start.sh`
Expected: both present. (Full image build is validated in Task 8 / by `make build` where Docker is available.)

- [ ] **Step 5: Commit**
`git add Dockerfile scripts/workbench-start.sh && git commit -m "fix(docker): serve UI from /app/ui/dist; start.sh uses python -m workbench (loopback)"`

---

## Task 7: Update docs + console message + ADR 0001

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `src/workbench/providers/messenger/console.py`, `docs/adr/0001-messenger-as-notification-only.md`

- [ ] **Step 1: Verify stale references**
Run: `grep -rn 'workbench serve\|workbench triage' README.md CLAUDE.md src/workbench/providers/messenger/console.py docs/adr/0001-messenger-as-notification-only.md`
Expected: several hits.

- [ ] **Step 2: Update each**
- `README.md`: `workbench serve` → `make serve`; `workbench serve --config ...` → `make serve` (env `WORKBENCH_CONFIG`); `workbench triage --token TOKEN` → `make triage`; the bullet "CLI — `workbench triage`" → "CLI — `make triage` / `scripts/triage.py`".
- `CLAUDE.md`: Development Commands `workbench serve` → `make serve`.
- `console.py`: `print("Respond via: workbench triage")` → `print("Respond via the web UI Triage page or: make triage")`.
- ADR 0001: change "`workbench triage` CLI" → "`make triage` (scripts/triage.py) CLI".

- [ ] **Step 3: Verify no stale runtime references remain**
Run: `grep -rn 'workbench serve\|workbench triage' README.md CLAUDE.md src/ Makefile scripts/ | grep -v docs/specs`
Expected: no matches (historical `docs/specs/*` left as-is).

- [ ] **Step 4: Sanity test**
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: no new failures.

- [ ] **Step 5: Commit**
`git add README.md CLAUDE.md src/workbench/providers/messenger/console.py docs/adr/0001-messenger-as-notification-only.md && git commit -m "docs: workbench serve/triage -> make serve / make triage"`

---

## Task 8: End-to-end validation (base repo)

**Files:** none (validation only)

- [ ] **Step 1: Fresh-venv console-script check**
Run: `python3 -m venv /tmp/wbcheck && /tmp/wbcheck/bin/pip install -e . -q && ls /tmp/wbcheck/bin/workbench 2>&1`
Expected: `No such file or directory` (no console script installed).

- [ ] **Step 2: `make serve` binds loopback**
Run (with `ANTHROPIC_API_KEY` set or a dummy, DB up): `make serve & sleep 8; ss -ltn | grep 8421; curl -s -o /dev/null -w '%{http_code}\n' localhost:8421/ui/; pkill -f 'workbench.main'`
Expected: listener on `127.0.0.1:8421`; `/ui/` → `200`.

- [ ] **Step 3: `make triage` reachable** (server running)
Run: `make triage <<< "s"`
Expected: prints pending cards (or "No pending triage cards.").

- [ ] **Step 4: `make lint` + `make test`**
Run: `make lint; make test`
Expected: ruff runs; pytest shows only the 6 pre-existing unrelated failures.

- [ ] **Step 5: Commit** (only if validation required a fix; otherwise skip)

---

## Task 9: workbench-meta lockstep

**Files (workbench-meta repo):**
- Modify: `Makefile`, `docker-compose.override.yml`

- [ ] **Step 1: Verify current state**
Run: `grep -n 'uvicorn workbench.main:app' ~/workspace/workbench-meta/docker-compose.override.yml; grep -n 'ui/dist\|ui-build\|npm run build' ~/workspace/workbench-meta/Makefile`
Expected: override runs `uvicorn ... --host ::`; Makefile has no ui-build step.

- [ ] **Step 2: Host ui-build before `up`**
In `workbench-meta/Makefile`, add a `ui-build` target and make `up` depend on it:
```make
ui-build:
	cd $(WORKBENCH_DIR)/ui && npm run build
```
and change `up: build dcat-start` → `up: ui-build build dcat-start`.

- [ ] **Step 3: Align the container launch**
In `workbench-meta/docker-compose.override.yml`, change the workbench service command's final line from
`exec uvicorn workbench.main:app --host :: --port 8421 --loop asyncio` to
`exec python -m workbench` (it already sets `WORKBENCH_CONFIG_OVERRIDE`; loopback `config.server.host` now applies — set `server.host` in `config.meta.yml` if all-interfaces is intended).

- [ ] **Step 4: Verify**
Run: `grep -n 'python -m workbench' ~/workspace/workbench-meta/docker-compose.override.yml && grep -n 'ui-build' ~/workspace/workbench-meta/Makefile`
Expected: both present. (Full `make up` validated when the podman stack is available.)

- [ ] **Step 5: Commit (in workbench-meta)**
`cd ~/workspace/workbench-meta && git add Makefile docker-compose.override.yml && git commit -m "build: lockstep with workbench Make workflow (host ui-build; python -m workbench launch)"`

---

## Notes
- Tasks 1–8 are in workbench/ on `feat/dashboard-followups` (or a dedicated branch). Task 9 is in the separate workbench-meta repo.
- `--loop asyncio` was a meta-specific uvicorn flag; if needed, set it via uvicorn env or restore it in the launcher — verify meta still starts under `python -m workbench` (uvicorn picks a default loop; asyncio is fine).
- Keep `config.server.host` in `ServerConfig` — the launcher and the loopback ADR depend on it.
