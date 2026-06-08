# Makefile Developer Workflow — Design Spec

## Context

Today workbench/ has a partial `Makefile` (build/up/down/logs/health/triage/setup/test/migrate) **and** a `workbench` console script (`src/workbench/cli.py` → `serve`/`triage`) declared in `[project.scripts]`. The two overlap and drift: `workbench serve` has no runtime callers (the container `entrypoint.sh` and the workbench-meta override both run `uvicorn` directly), while `workbench triage` is invoked by `make triage`. This makes Make the de-facto interface for everything except a redundant CLI. This change makes **Make the single developer interface** and removes the console script.

## Goals

1. **Single interface** — every developer action (setup, build, run, test, migrate, lint, UI build, triage) is a `make` target in workbench/.
2. **No console script** — delete `src/workbench/cli.py` and `[project.scripts]`; `serve` becomes `python -m workbench`, `triage` becomes `scripts/triage.py`.
3. **Preserve loopback bind** — the `serve` launcher honors `config.server.host` (default `127.0.0.1`, per ADR 0017) so the security boundary from T274646800 survives.
4. **Buildable UI** — `make build` builds the dashboard UI and the image serves it (fix the `/app/ui-dist` → `/app/ui/dist` path bug).
5. **Lockstep with workbench-meta** — meta's standalone Makefile and compose override are aligned to the new launch path and the host `ui-build` prerequisite.

## Architecture

```
Developer ──> make <target> ──┬── setup / ui-setup        (venv + deps; ui npm deps)
                              ├── ui-build / gen-api / ui-test
                              ├── build (→ ui-build) / up / down   (docker|podman compose)
                              ├── serve  ── python -m workbench ── uvicorn(host=config.server.host)
                              ├── test / migrate / lint / format
                              ├── logs / health
                              └── triage ── scripts/triage.py ── /api/triage/*

Container start (entrypoint.sh) ── uvicorn (WORKBENCH_HOST default 127.0.0.1)
workbench-meta/Makefile ── (host) ui-build ──> volume-mounts ui/dist ──> compose up ──> python -m workbench
```

Make is the only thing developers invoke. `python -m workbench` and `scripts/triage.py` are the two thin Python entrypoints that replace the console script; both are also reusable by scripts and the meta overlay.

## Design Section 1 — Base Makefile target set

`workbench/Makefile` exposes the full workflow. `PYTHON ?= $(HOME)/.venv/workbench/bin/python` (existing). UI targets prepend the registry toolchain note (see §5).

| Target | Action |
|--------|--------|
| `setup` | `python3 -m venv $(HOME)/.venv/workbench` + `pip install -e ".[dev]"` (existing) |
| `ui-setup` | `cd ui && npm install` (registry deps; via proxy where required) |
| `ui-build` | `cd ui && npm run build` → `ui/dist` |
| `ui-test` | `cd ui && npm run test` (vitest) |
| `gen-api` | `cd ui && npm run gen:api` (regenerate `src/lib/api-types.ts`; requires a running server) |
| `build` | **depends on `ui-build`**, then `$(COMPOSE) $(COMPOSE_FILES) build` |
| `up` | `build` then `$(COMPOSE) ... up -d` (existing) |
| `down` | `$(COMPOSE) ... down` (existing) |
| `serve` | `$(PYTHON) -m workbench` — local dev server, honors `config.server.host`/`port`/`debug` |
| `test` | `$(PYTHON) -m pytest tests/ -v --tb=short` (existing) |
| `migrate` | `$(PYTHON) -m alembic upgrade head` (existing; use `$(PYTHON) -m` for venv consistency) |
| `lint` | `$(PYTHON) -m ruff check src/ tests/ scripts/` |
| `format` | `$(PYTHON) -m ruff format src/ tests/ scripts/` |
| `logs` | `$(PYTHON) scripts/logview.py data/logs ...` (existing) |
| `health` | `curl -s http://localhost:8421/health | python3 -m json.tool` (existing) |
| `triage` | `$(PYTHON) scripts/triage.py --token $${WORKBENCH_API_TOKEN:-change-me}` |
| `clean` | remove `ui/dist`, `__pycache__`, `.pytest_cache`, build artifacts (not the venv) |

`.PHONY` lists every target. `ruff` is added to `[project.optional-dependencies].dev` (the one new tool; modern lint+format in one binary).

## Design Section 2 — Server launcher (`python -m workbench`)

Create `src/workbench/__main__.py` with the `serve` behavior moved verbatim from `cli.py`:

```python
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
        host=config.server.host,   # loopback default (ADR 0017 / T274646800)
        port=config.server.port,
        reload=config.server.debug,
    )

if __name__ == "__main__":
    main()
```

It reads `WORKBENCH_CONFIG`/`WORKBENCH_CONFIG_OVERRIDE` from the environment (no `--config`/`--override` flags — env is how the container + meta already pass them). `config.server.host` keeps the loopback default meaningful; `ServerConfig.host` is retained.

## Design Section 3 — Terminal triage (`scripts/triage.py`)

Move the `triage()` function from `cli.py` into `scripts/triage.py` as a standalone argparse script (`--server` default `http://localhost:8421`, `--token` or `WORKBENCH_API_TOKEN`). Behavior is unchanged (GET `/api/triage/pending`, print numbered cards, read stdin choice, POST `/api/triage/respond`). `make triage` invokes `$(PYTHON) scripts/triage.py`. Update `src/workbench/providers/messenger/console.py` ("Respond via: workbench triage" → "Respond via the web UI Triage page or `make triage`") and add a one-line note to ADR 0001 that the CLI is now `make triage` / `scripts/triage.py`.

## Design Section 4 — Remove the console script

- Delete `src/workbench/cli.py`.
- Remove the `[project.scripts]` table from `pyproject.toml` (the `workbench = "workbench.cli:main"` entry).
- Update `README.md` (replace `workbench serve`/`workbench triage` with `make serve`/`make triage`) and `CLAUDE.md` (Development Commands: `workbench serve` → `make serve`).
- No tests import `workbench.cli` (verified) — nothing else to change.

## Design Section 5 — UI build + image fix + launch-path alignment

- **`make build` builds the UI:** `build: ui-build` so `ui/dist` is fresh before the image build.
- **Dockerfile fix:** in `workbench/Dockerfile`, change `COPY --from=ui-builder /ui/dist /app/ui-dist` to `COPY --from=ui-builder /ui/dist /app/ui/dist` so `main.py`'s mount (`../../ui/dist` = `/app/ui/dist`) finds it and the base image serves `/ui`.
- **`scripts/workbench-start.sh`** (systemd): replace the hardcoded `python -m uvicorn workbench.main:app --host 0.0.0.0 ...` with `exec "$PROJECT_DIR/.venv/bin/python" -m workbench` so it honors the loopback `config.server.host`.
- **Registry toolchain note:** UI targets document that on hosts where `npm` is wrapped, the real Node + `with-proxy npm install` are required (build/test need no network). The targets call plain `npm`; the env provides the real binary on PATH.

## Design Section 6 — workbench-meta lockstep

- **Host `ui-build` before `up`:** workbench-meta mounts `~/workspace/workbench/ui/dist:/app/ui/dist:ro`, so `ui/dist` must be host-built first. Add to `workbench-meta/Makefile` a step (or `up` dependency) that runs `cd $(WORKBENCH_DIR)/ui && npm run build` before `compose up`.
- **Launch path:** change the meta `workbench` override command's final line from `exec uvicorn workbench.main:app --host :: --port 8421 --loop asyncio` to `exec $(PYTHON-in-container) -m workbench` (it already sets `WORKBENCH_CONFIG_OVERRIDE`); the loopback `config.server.host` default then applies uniformly. (If meta deliberately needs all-interfaces, it sets `server.host` in `config.meta.yml` — explicit, not hardcoded.)
- meta's Makefile stays standalone (it references the base repo's compose + scripts); no `include` is introduced — alignment is by shared launch entrypoint (`python -m workbench`) and the ui-build prerequisite.

## File Changes

### workbench/ (new)
| File | Description |
|------|-------------|
| `src/workbench/__main__.py` | `python -m workbench` server launcher (honors `config.server.host`) |
| `scripts/triage.py` | terminal triage (moved from cli.py) |

### workbench/ (modified)
| File | Description |
|------|-------------|
| `Makefile` | full target set (§1); `build: ui-build`; `serve`/`triage`/`migrate` via `$(PYTHON)`; `lint`/`format`/`clean`/`ui-*`/`gen-api` |
| `pyproject.toml` | remove `[project.scripts]`; add `ruff` to dev deps |
| `Dockerfile` | UI copy path `/app/ui-dist` → `/app/ui/dist` |
| `scripts/workbench-start.sh` | launch via `python -m workbench` (loopback) |
| `src/workbench/providers/messenger/console.py` | triage hint → web UI / `make triage` |
| `README.md`, `CLAUDE.md` | `workbench serve/triage` → `make serve`/`make triage` |
| `docs/adr/0001-messenger-as-notification-only.md` | note CLI is now `make triage` |

### workbench/ (deleted)
| File | Description |
|------|-------------|
| `src/workbench/cli.py` | replaced by `__main__.py` + `scripts/triage.py` |

### workbench-meta/ (modified)
| File | Description |
|------|-------------|
| `Makefile` | host `ui-build` step before `up` |
| `docker-compose.override.yml` | workbench command → `python -m workbench` |

## Verification

1. `make setup` creates the venv and installs deps incl. `ruff`.
2. `make ui-build` produces `ui/dist/index.html`.
3. `make serve` starts the server bound to `127.0.0.1:8421` (confirm `ss -ltn` shows loopback) and `/ui/` returns 200.
4. `python -m workbench` honors `server.host` override (set `server.host: "::"` in a test config → binds all interfaces).
5. `make triage` runs `scripts/triage.py` and reaches `/api/triage/pending`.
6. `make test` → pytest passes (same as before; no test imports `cli`).
7. `make lint` and `make format` run `ruff` over `src/ tests/ scripts/`.
8. `pip install -e .` no longer creates a `workbench` console script (`which workbench` empty in a fresh venv).
9. `make build` (or base `docker build`) produces an image whose `/app/ui/dist/index.html` exists and `/ui/` serves the SPA.
10. workbench-meta `make up` builds host `ui/dist` first and the running stack serves `/ui`; the workbench container launches via `python -m workbench`.

## Resolved Questions

1. **Terminal triage:** → Kept as `scripts/triage.py` + `make triage` (web Triage page is the primary surface; CLI retained for terminal use).
2. **Serve launcher:** → `python -m workbench` thin launcher reading `config.server.host` — preserves the loopback bind; not a console script.
3. **Scope:** → Both repos in lockstep (workbench/ + workbench-meta/).
4. **UI in build:** → `ui-build` target, `build` depends on it, and the Dockerfile `/app/ui/dist` path bug is fixed.
5. **Lint/format tool:** → add `ruff` (single binary for lint + format); the one additive dependency.
6. **Config/override flags:** → dropped from the launcher; `WORKBENCH_CONFIG`/`WORKBENCH_CONFIG_OVERRIDE` env vars (already used by the container + meta) are the mechanism.

## Out of Scope

- A `workbench init` setup wizard (referenced in old specs; not built).
- Changing the compose engine choice (base uses `docker compose`; meta uses `podman-compose`) — unchanged.
- Introducing a base→meta Makefile `include` hierarchy — meta stays standalone.
- CI wiring of the new lint/format targets.
- Fixing the 6 pre-existing unrelated test failures.
