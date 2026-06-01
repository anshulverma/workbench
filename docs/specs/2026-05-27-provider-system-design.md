# Provider System & Configuration Design

## Overview

Workbench uses a pluggable provider system for all external integrations. Providers are discovered via Python entry points (for discoverability) and loaded at runtime via dynamic import (`importlib.import_module`) from the YAML config file. The server never imports or knows about specific provider implementations.

## Provider System

### Discovery & Registration

Provider implementations are discovered via **Python entry points** (for discoverability — e.g., a `workbench providers list` CLI command) and loaded at runtime via **dynamic import** from the YAML config file.

Entry point groups:

| Group | Description |
|---|---|
| `workbench.messenger` | Triage card delivery and response polling |
| `workbench.source` | External system polling for raw content |
| `workbench.llm` | LLM API for extraction, scoring, filtering |
| `workbench.enrichment` | Entity context gathering |
| `workbench.doc_reader` | Document content retrieval |
| `workbench.memory` | Knowledge graph integration (Zep) |

Note: Storage is excluded from the provider pattern — it's a different shape (one backend produces multiple repositories in a `Stores` bundle). Storage keeps its own factory (`create_stores()`).

### Provider Lifecycle

All provider base classes define `async def close(self): pass` as a no-op default. Providers that hold connections (HTTP pools, gRPC channels, websockets) override `close()` for cleanup. The FastAPI lifespan calls `close()` on all providers after yield (on shutdown).

### Typed Provider Config

Each provider declares a `ProviderConfig` pydantic model. The server validates the YAML config section against it at startup — full type safety, no untyped dicts.

```python
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

The Messenger interface supports buttons, reactions, threads as first-class concepts. Both push (webhooks/callbacks) and pull (polling) response models are supported; each provider implements whichever fits its platform, and the server adapts. Simpler implementations degrade gracefully by implementing rich methods in terms of simpler primitives.

## Configuration

### YAML Config Files

Configuration is file-based, not env-var-based. The server takes a config file at startup.

```yaml
# config.yml
server:
  port: 8421
  debug: false
  api_token: ${oc.env:WORKBENCH_API_TOKEN,dev-token-change-me}

storage:
  postgres_dsn: ${oc.env:WORKBENCH_POSTGRES_DSN}

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

### Layered Config Merge

The server loads a base config file, then deep-merges an optional override file on top:

```bash
workbench serve --config config.yml --override config.override.yml
```

**Merge rules:**
- Scalars: override wins
- Dicts: deep-merged recursively
- Lists (e.g., `sources`): override replaces the entire list (no append/merge)

This enables a base config for the generic setup and an override for environment-specific providers.

## Package Structure

Uses the `src` layout (PyPA recommended) to prevent import shadowing:

```
workbench/                          # repo root
├── pyproject.toml                  # package metadata + entry point declarations
├── Dockerfile
├── Makefile                        # auto-detects podman/docker
├── docker-compose.yml
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
│       │   │   ├── messenger.py
│       │   │   ├── source.py
│       │   │   ├── llm.py
│       │   │   ├── enrichment.py
│       │   │   ├── doc_reader.py
│       │   │   └── memory.py
│       │   ├── messenger/
│       │   │   ├── discord.py      # default messenger
│       │   │   └── console.py      # local dev / debugging
│       │   ├── source/
│       │   │   └── github.py       # default source
│       │   ├── llm/
│       │   │   └── anthropic.py    # direct Anthropic API
│       │   ├── enrichment/
│       │   │   └── stub.py
│       │   ├── doc_reader/
│       │   │   └── web.py          # generic URL reader
│       │   └── memory/
│       │       └── noop.py         # NoopMemoryLayer (default)
│       ├── storage/                # own factory pattern, not provider system
│       └── pipeline/
├── plugin/                         # Claude Code plugin
├── tests/
│   └── providers/
│       └── test_utils.py           # shared provider test fixtures
└── docs/
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

For environment-specific overrides, `docker-compose.override.yml` adds the override config and any additional environment variables.

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
```

## CLI

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

## Source Adapter Config Split

Source adapters have two kinds of configuration:

- **Static** (YAML config): which adapter class to use, credentials (tokens, API keys). Declared in `config.yml`.
- **Dynamic** (database): enabled/disabled status, poll schedule, last polled timestamp, cursor. Stored in `SourceConfigStore`.

At startup, the server loads source adapter classes from YAML, syncs them into the database if not already present, and the scheduler uses the DB for runtime state (schedule, cursor, enabled/disabled toggled via API).

Source creation and deletion are YAML-only — the API manages dynamic state only: `PATCH /api/sources/{id}` (enable/disable, schedule), `GET /api/sources` (list). To add or remove a source, edit config.yml and restart.

## Dependencies

All bundled provider dependencies (discord.py, PyGithub, anthropic, etc.) are mandatory dependencies of the `workbench` package — no optional extras. The provider set is small enough that the dependency footprint is reasonable, and this avoids confusing ImportError scenarios.

`pydantic-settings` is no longer needed — OmegaConf handles env var resolution in YAML, and all config models are plain `pydantic.BaseModel`, not `BaseSettings`.

## Testing

The main repo ships shared provider test utilities (`tests/providers/test_utils.py`) — fixtures and contract tests that validate any provider implementation against its base interface. Provider packages import and run these against their providers.

## Plugin Extensibility

The Claude Code plugin is provider-agnostic. Provider packages can add platform-specific plugin commands in their own `plugin/commands/` directory. The plugin config supports additional command directories to scan.
