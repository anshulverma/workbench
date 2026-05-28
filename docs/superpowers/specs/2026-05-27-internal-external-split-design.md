# Internal/External Code Split Design

Split Workbench into a public GitHub repo (generic framework) and a private internal repo (`workbench-meta`) containing Meta-specific provider implementations. The public repo ships working external defaults (Discord, GitHub, direct Anthropic API). The internal repo provides Meta-specific providers as a separate installable package, living in dotsync2 at `~/workspace/workbench-meta`.

## Goals

- Push `workbench` to `github.com/anshulverma/workbench` with zero Meta-internal references in code or config defaults
- Meta-internal implementations live in a separate `workbench-meta` package synced via dotsync2
- External users get a working system out-of-the-box with Discord messenger, GitHub source adapter, and direct Anthropic API
- The provider system uses standard Python mechanics (dynamic import + typed config) so anyone can add providers
- Design for extensibility now; don't over-invest in community implementations upfront

## Provider System

### Discovery & Registration

Provider implementations are discovered via **Python entry points** (for discoverability — e.g., a `workbench providers list` CLI command) and loaded at runtime via **dynamic import** (`importlib.import_module`) from the YAML config file.

Entry point groups (for discovery):

| Group | External defaults | Internal (workbench-meta) |
|---|---|---|
| `workbench.messenger` | `discord`, `console` | `gchat` |
| `workbench.source` | `github` | `phabricator`, `tasks`, `workplace`, `calendar`, `sevs`, `oncall` |
| `workbench.llm` | `anthropic` | `anthropic-meta` |
| `workbench.enrichment` | `stub` | `meta` |
| `workbench.doc_reader` | `web` | `intern` |
| `workbench.memory` | `noop` | `zep` |

Note: Storage is excluded from the provider pattern — it's a different shape (one backend produces ten repositories in a `Stores` bundle). Storage keeps its own factory (`create_stores()`).


### Provider Lifecycle

All provider base classes define `async def close(self): pass` as a no-op default. Providers that hold connections (Discord gateway, HTTP pools, gRPC channels) override `close()` for cleanup. The FastAPI lifespan calls `close()` on all providers after yield (on shutdown). The `/api/reload` endpoint also calls `close()` before reconstructing providers.

### Typed Provider Config

Each provider declares a `ProviderConfig` pydantic model. The server validates the YAML config section against it at startup — full type safety, no untyped dicts.

```python
# workbench/providers/messenger/discord.py
from pydantic import BaseModel

class DiscordMessenger(Messenger):
    class ProviderConfig(BaseModel):
        bot_token: str
        channel_id: str

    def __init__(self, config: ProviderConfig):
        self.bot_token = config.bot_token
        self.channel_id = config.channel_id
```

### Provider Factory

The registry resolves the class from the dotted path, grabs its `ProviderConfig`, validates the YAML section, and constructs the provider:

```python
# workbench/registry.py
import importlib

def create_provider(section: dict):
    class_path = section.pop("class")
    module_path, class_name = class_path.rsplit(".", 1)
    cls = getattr(importlib.import_module(module_path), class_name)
    typed_config = cls.ProviderConfig(**section)
    return cls(typed_config)
```

The server never imports or knows about specific provider implementations. If the class path cannot be resolved (package not installed), the registry catches `ModuleNotFoundError` and re-raises with guidance: which provider role, which class path, and a suggestion to check the package install.

### Messenger Interface

The Messenger interface is richer than the current `send_card` + `poll_responses` — it supports buttons, reactions, threads as first-class concepts. Both push (webhooks/callbacks) and pull (polling) response models are supported; each provider implements whichever fits its platform, and the server adapts. Simpler implementations (like GChat's text-reply model) degrade gracefully by implementing rich methods in terms of simpler primitives.

## Configuration

### YAML Config Files

Configuration is file-based, not env-var-based. The server takes a config file at startup.

```yaml
# config.yml
server:
  port: 8421
  debug: false
  api_token: ${oc.env:WORKBENCH_API_TOKEN,dev-token-change-me}
  sqlite_path: /data/workbench.db

messenger:
  class: workbench.providers.messenger.discord.DiscordMessenger
  bot_token: ${oc.env:DISCORD_BOT_TOKEN}
  channel_id: "123456"

llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  base_url: "https://api.anthropic.com"

sources:
  - class: workbench.providers.source.github.GithubSourceAdapter
    token: ${oc.env:GITHUB_TOKEN}
    repos:
      - "anshulverma/workbench"

memory:
  class: workbench.memory.noop.NoopMemoryLayer
```

### Secrets via OmegaConf

Secrets use OmegaConf's env var interpolation (`${oc.env:VAR}` or `${oc.env:VAR,default}`). OmegaConf is a standalone dependency (no Hydra needed). Config files with `${oc.env:...}` are safe to commit — secrets stay in the environment.

OmegaConf is used *only* for env var resolution. After resolution, the config is converted to a plain dict via `OmegaConf.to_container(cfg, resolve=True)` and passed to pydantic for all validation and type checking. The `server:` section is validated against a `ServerConfig` pydantic model; each provider section is validated against the provider's `ProviderConfig`. OmegaConf resolution errors (missing env vars) are caught and re-raised with config context (which provider role, which field, which config file).

### Config Reload

`POST /api/reload` (auth required) triggers config re-read, provider teardown (`close()`), and reconstruction from the updated config. No automatic file watching — reload is explicit. Restart is also always an option.

### Layered Config Merge

The server loads a base config file, then deep-merges an optional override file on top:

```bash
workbench serve --config config.yml --override config.meta.yml
```

**Merge rules:**
- Scalars: override wins
- Dicts: deep-merged recursively
- Lists (e.g., `sources`): override replaces the entire list (no append/merge)

### Internal Override Config

```yaml
# config.meta.yml (in workbench-meta)
messenger:
  class: workbench_meta.providers.messenger.gchat.GChatMessenger
  space_id: ${oc.env:GCHAT_SPACE_ID}

llm:
  class: workbench_meta.providers.llm.anthropic_meta.MetaAnthropicLLM
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  base_url: "https://plugboard.x2p.facebook.net"

sources:
  - class: workbench_meta.providers.source.phabricator.PhabricatorSourceAdapter
    user_phid: "PHID-USER-abc123"
  - class: workbench_meta.providers.source.tasks.TasksSourceAdapter
    owner: "anshulverma"
```

## Package Structure

### Package Rename

The Python package is renamed from `server` to `workbench`. All imports change: `server.models` becomes `workbench.models`. Uses the `src` layout (PyPA recommended) to prevent import shadowing.

**The rename happens before phase 1a continues** — so new code uses the correct import paths from the start, avoiding a bulk rename later.

### Public Repo Structure

```
workbench/                          # repo root
├── pyproject.toml                  # package metadata + entry point declarations
├── Dockerfile                      # at repo root (build context is .)
├── Makefile                        # auto-detects podman/docker
├── docker-compose.yml              # generic (no Meta URLs), volume-mounts config.yml
├── config.example.yml              # template config (committed, documented)
├── .gitignore                      # includes config.yml, .env, docker-compose.override.yml
├── src/
│   └── workbench/                  # Python package (src layout)
│       ├── cli.py                  # workbench CLI (serve, init, providers list)
│       ├── config.py               # ServerConfig model, YAML loader, OmegaConf resolver
│       ├── main.py
│       ├── models.py
│       ├── registry.py             # provider discovery + factory
│       ├── providers/
│       │   ├── base/               # interfaces only
│       │   │   ├── messenger.py    # richer interface (buttons, reactions, threads)
│       │   │   ├── source.py
│       │   │   ├── llm.py
│       │   │   ├── enrichment.py
│       │   │   ├── doc_reader.py
│       │   │   └── memory.py       # MemoryLayer interface
│       │   ├── messenger/
│       │   │   ├── discord.py      # default external messenger
│       │   │   └── console.py      # local dev / debugging
│       │   ├── source/
│       │   │   └── github.py       # default external source
│       │   ├── llm/
│       │   │   └── anthropic.py    # direct Anthropic API (no proxy, no certs)
│       │   ├── enrichment/
│       │   │   └── stub.py
│       │   ├── doc_reader/
│       │   │   └── web.py          # generic URL reader
│       │   └── memory/
│       │       └── noop.py         # NoopMemoryLayer (default)
│       ├── storage/                # own factory pattern, not provider system
│       └── pipeline/
├── plugin/                         # Claude Code plugin (extensible from internal repo)
│   ├── commands/                   # base commands
│   └── config/
│       └── config.json             # default: localhost:8421
├── tests/
│   └── providers/
│       └── test_utils.py           # shared provider test fixtures
├── .github/
│   └── workflows/
│       └── ci.yml                  # lint + type check + test (Python 3.11-3.13 matrix)
├── docs/                           # generic docs
└── CLAUDE.md                       # genericized project guide
```

### Docker

The `Dockerfile` lives at the repo root. `docker-compose.yml` volume-mounts `config.yml` and passes secrets as env vars:

```yaml
services:
  workbench:
    build: .
    volumes:
      - ./config.yml:/app/config.yml:ro
    environment:
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
```

For the internal case, `docker-compose.override.yml` adds:

```yaml
services:
  workbench:
    build: ~/workspace/workbench-meta  # extends public image
    command: workbench serve --config /app/config.yml --override /app/config.override.yml
    volumes:
      - ~/workspace/workbench-meta/config.meta.yml:/app/config.override.yml:ro
    environment:
      - GCHAT_SPACE_ID=${GCHAT_SPACE_ID}
```

### Internal Repo Structure (`workbench-meta`)

Lives at `~/workspace/workbench-meta`, synced via dotsync2.

```
workbench-meta/
├── pyproject.toml                  # declares entry points, declares workbench as dependency
├── Dockerfile                      # FROM workbench:latest, adds pip install
├── docker-compose.override.yml     # points to internal config
├── config.meta.yml                 # internal provider config
├── workbench_meta/
│   ├── __init__.py
│   ├── providers/
│   │   ├── messenger/
│   │   │   └── gchat.py            # Google Chat via Meta's API proxy
│   │   ├── source/
│   │   │   ├── phabricator.py      # Phabricator diffs (arc conduit)
│   │   │   ├── tasks.py            # Meta Tasks
│   │   │   ├── workplace.py        # Workplace posts
│   │   │   ├── calendar.py         # Calendar events
│   │   │   ├── sevs.py             # SEVs
│   │   │   └── oncall.py           # Oncall alerts
│   │   ├── llm/
│   │   │   └── anthropic_meta.py   # Anthropic via plugboard + x509 certs
│   │   ├── enrichment/
│   │   │   └── meta.py             # Meta-specific context enrichment
│   │   └── doc_reader/
│   │       └── intern.py           # Intern wiki reader
│   ├── lib/
│   │   └── google_api.py           # moved from main repo
│   └── plugin/
│       └── commands/               # Meta-specific plugin commands
├── docs/                           # Meta-specific supplemental docs
│   └── original/                   # pre-genericization docs from main repo
└── tests/                          # uses shared test utils from main repo
```

### Internal Dockerfile

```dockerfile
FROM workbench:latest
COPY . /opt/workbench-meta
RUN pip install -e /opt/workbench-meta
```

### Makefile

Auto-detects container runtime (podman vs docker):

```makefile
COMPOSE := $(shell command -v podman 2>/dev/null && echo "podman compose" || echo "docker compose")

.PHONY: up down logs dev setup

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

dev:
	workbench serve --config config.yml --reload

init:
	workbench init

setup:
	pip install -e .
	@if [ -d "$(HOME)/workspace/workbench-meta" ]; then \
		echo "Installing workbench-meta..."; \
		pip install -e $(HOME)/workspace/workbench-meta; \
	fi
```

## Source Adapter Config Split

Source adapters have two kinds of configuration:

- **Static** (YAML config): which adapter class to use, credentials (tokens, API keys). Declared in `config.yml`.
- **Dynamic** (database): enabled/disabled status, poll schedule, last polled timestamp, cursor. Stored in `SourceConfigStore`.

At startup, the server loads source adapter classes from YAML, syncs them into the database if not already present, and the scheduler uses the DB for runtime state (schedule, cursor, enabled/disabled toggled via API).

Source creation and deletion are YAML-only — `POST /api/sources` and `DELETE /api/sources` are removed. The API manages dynamic state only: `PATCH /api/sources/{id}` (enable/disable, schedule), `GET /api/sources` (list). To add or remove a source, edit config.yml and call `POST /api/reload`.

## First-Run Experience

The repo ships `config.example.yml` (committed, documented template). The real `config.yml` is gitignored.

### CLI

The `workbench` CLI is registered as a console script in pyproject.toml:

```toml
[project.scripts]
workbench = "workbench.cli:main"
```

Subcommands:
- `workbench serve` — starts the server (wraps uvicorn), accepts `--config` and `--override` args (default: `./config.yml`)
- `workbench init` — setup wizard, generates config.yml
- `workbench providers list` — shows installed providers via entry points

### Setup Wizard

A setup wizard (`workbench init`) walks the user through:
1. Which messenger to use (Discord, console, or custom)
2. Which source adapters to enable (GitHub, RSS, or custom)
3. API keys and tokens for selected providers
4. Generates a working `config.yml`

Without running the wizard, `workbench serve` refuses to start with a clear message: "No config.yml found. Run `workbench init` to configure."

## Dependencies

`workbench-meta` declares `workbench` as a dependency in its `pyproject.toml`. Since `workbench` is not on PyPI, this fails if `workbench` isn't already installed. The Makefile `setup` target ensures correct install order. The dependency declaration serves as documentation.

All bundled provider dependencies (discord.py, PyGithub, anthropic, etc.) are mandatory dependencies of the `workbench` package — no optional extras. The provider set is small enough that the dependency footprint is reasonable, and this avoids confusing ImportError scenarios.

`pydantic-settings` is no longer needed — OmegaConf handles env var resolution in YAML, and all config models are plain `pydantic.BaseModel`, not `BaseSettings`. Drop from dependencies.

## Testing

The main repo ships shared provider test utilities (`tests/providers/test_utils.py`) — fixtures and contract tests that validate any provider implementation against its base interface. The internal repo imports and runs these against its providers.

Each repo has independent test suites, but the shared utilities ensure consistency.

## Plugin Extensibility

The Claude Code plugin is provider-agnostic and lives in the public repo. The internal repo can add Meta-specific plugin commands (e.g., `/workbench:phab-sync`) in its own `plugin/commands/` directory. The plugin config supports additional command directories to scan.

## Files to Move or Remove from Public Repo

| File | Action |
|---|---|
| `server/lib/google_api.py` | Move to `workbench-meta/workbench_meta/lib/` |
| `server/providers/llm/claude.py` | Split: generic part stays as `anthropic.py`, Meta cert/proxy code moves to `workbench-meta` |
| `server/providers/messenger/google_chat.py` | Move to `workbench-meta` |
| `server/providers/source/phabricator.py` | Move to `workbench-meta` |
| `plugin/config/config.json` | Change hostname to `localhost:8421` |
| `docker-compose.yml` | Remove plugboard URL |
| `server/config.py` | Rewrite for YAML config + provider registry |
| `CLAUDE.md` | Genericize |
| `CONTEXT.md` | Genericize |
| `docs/specs/*.md` | Genericize; originals preserved in `workbench-meta/docs/original/` |
| `docs/adr/0001-*.md` | Genericize (remove WWW/fbcode references) |
| `docs/memory/` | Remove (internal project context) |
| `server/` directory | Rename to `workbench/` |

## Pre-Push Security Checklist

Before pushing to GitHub:

1. Run the grep scan:
```bash
grep -rn -i -E '(facebook|meta\.com|fbsource|plugboard|x2p|clicat|corp_clicat|jellyfish|xfb_|dcat|/var/facebook|rootcanal|devgpu|\.lla[0-9]|\.prn[0-9]|\.ftw[0-9])' \
  --include='*.py' --include='*.yml' --include='*.yaml' --include='*.md' \
  --include='*.txt' --include='*.toml' --include='*.json' --include='*.cfg' \
  . | grep -v '.git/' | grep -v '__pycache__/' | grep -v '.venv/'
```
Must return zero results.

2. Rewrite git history — interactive rebase to clean commit messages of Meta-internal references (7 commits, manageable).

3. Verify `.gitignore` includes:
```
.env
*.pyc
__pycache__/
.venv/
internal/
docker-compose.override.yml
config.meta.yml
```

## License

MIT or Apache 2.0 for the public repo. Decision deferred.

## Sequencing

### Pre-phase-1a (do now)

1. Rename `server/` → `src/workbench/`, update all imports, add `pyproject.toml` with src layout

### Post-phase-1a (the split)

2. Create `~/workspace/workbench-meta` with dotsync2 sync
3. Add `config.example.yml`, `src/workbench/registry.py`, `Dockerfile`
4. Implement YAML config loading with OmegaConf interpolation and layered merge
5. Implement setup wizard (`workbench init`)
6. Refactor `main.py` lifespan to use registry instead of hardcoded provider imports
7. Move Meta-specific files to internal repo
8. Add external provider implementations (Discord, GitHub, direct Anthropic)
9. Richen the Messenger interface
10. Add Memory Layer to provider system (noop default, zep via config)
11. Add shared test utilities
12. Genericize docs (preserve originals in internal repo)
13. Rewrite git history
14. Add GitHub Actions CI (lint, type check, test — Python 3.11-3.13 matrix)
15. Run security checklist
16. Push to GitHub
