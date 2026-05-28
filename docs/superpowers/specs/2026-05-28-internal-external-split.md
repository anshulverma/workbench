# Internal/External Split — Implementation Spec

Split Workbench into a public GitHub repo (`workbench`) and a private internal overlay (`workbench-meta`) synced via dotsync2.

## Goals

- Push `workbench` to `github.com/anshulverma/workbench` with zero Meta-internal references
- Meta-specific providers live in `workbench-meta` as a pip-installable overlay
- External users get a working system with ConsoleMessenger, GitHubSourceAdapter, and direct Anthropic API
- MIT license

## Architecture

Two repos, one package namespace:

**`workbench`** (public, GitHub):
- Framework: FastAPI server, pipeline engine, storage layer, provider ABCs, YAML config/registry, Alembic migrations
- External providers: `AnthropicLLM` (direct API, no proxy/certs), `ConsoleMessenger` (stdout), `GitHubSourceAdapter` (polls repos via PyGithub)
- Default providers: `StubEnricher`, `NoopMemoryLayer`
- `config.example.yml` with external defaults (api.anthropic.com, ConsoleMessenger)
- Dockerfile, docker-compose.yml, plugin, tests, genericized docs

**`workbench-meta`** (private, `~/workspace/workbench-meta`, dotsync2):
- Meta providers: `MetaAnthropicLLM` (Plugboard + x509 mTLS), `MetaQueueScorer` (same certs), `GoogleChatMessenger` (google_api.py + DCAT), `PhabricatorAdapter` (arc conduit), `GmailAdapter`, `MetaEnricher`
- `lib/google_api.py` (1565 lines, DCAT auth)
- `config.meta.yml` (layered override)
- `docker-compose.override.yml`
- Internal Dockerfile (extends public image)
- Original design docs (preserved for reference)

## Deployment

On devvm with dotsync2:
```bash
pip install -e ~/workspace/workbench
pip install -e ~/workspace/workbench-meta
workbench serve --config config.yml --override ~/workspace/workbench-meta/config.meta.yml
```

Or via Podman:
```bash
podman compose up -d                                    # base stack
podman compose -f docker-compose.override.yml up -d     # with meta overlay
```

## What moves where

### Stays in `workbench` (genericized)

All framework code:
- `src/workbench/` — models, storage (ABCs + PG), pipeline, API, scheduler, worker, registry, config, auth, MCP
- Provider ABCs: all `base.py` files in providers/
- Default providers: `StubEnricher`, `NoopMemoryLayer`
- Alembic migrations
- Plugin (with localhost:8421 defaults)
- Tests (framework + external providers)

New external providers (created during split):
- `src/workbench/providers/llm/anthropic.py` — `AnthropicLLM`: direct `AsyncAnthropic(api_key, base_url="https://api.anthropic.com")`, no certs, no proxy
- `src/workbench/providers/messenger/console.py` — `ConsoleMessenger`: prints triage cards to stdout, reads responses from stdin (for local dev/debugging)
- `src/workbench/providers/source/github.py` — `GitHubSourceAdapter`: polls GitHub repos for PRs/issues via PyGithub
- `src/workbench/providers/queue_scorer/llm.py` — genericized: strip cert logic, use direct Anthropic API

Infrastructure:
- `pyproject.toml` — updated dependencies (add PyGithub, remove aiosqlite)
- `Dockerfile` — unchanged from Phase 1a
- `docker-compose.yml` — unchanged
- `config.example.yml` — external defaults
- `alembic.ini`
- `.gitignore`
- `LICENSE` (MIT)
- `README.md`

### Moves to `workbench-meta`

Provider implementations:
- `src/workbench/providers/llm/claude.py` → `workbench_meta/providers/llm/meta_anthropic.py` (`MetaAnthropicLLM`)
- `src/workbench/providers/queue_scorer/llm.py` (Meta cert version) → `workbench_meta/providers/queue_scorer/meta_scorer.py` (`MetaQueueScorer`)
- `src/workbench/providers/messenger/google_chat.py` → `workbench_meta/providers/messenger/gchat.py`
- `src/workbench/providers/source/phabricator.py` → `workbench_meta/providers/source/phabricator.py`
- `src/workbench/providers/source/email_gmail.py` → `workbench_meta/providers/source/gmail.py`
- `src/workbench/lib/google_api.py` → `workbench_meta/lib/google_api.py`

Config + Docker:
- `config.meta.yml` — layered override with Meta class paths
- `docker-compose.override.yml` — extends public image, mounts meta config
- `Dockerfile` — `FROM workbench:latest`, `pip install -e /opt/workbench-meta`

Docs:
- `docs/specs/` (originals with Meta-internal details)
- `docs/adr/` (originals)
- `docs/superpowers/specs/` (originals)
- `CONTEXT.md` (original with Meta terms)

### Removed from repo (already in Claude project memory)

- `docs/memory/MEMORY.md`
- `docs/memory/project_meta_internal_pivot.md`
- `docs/memory/project_tech_decisions.md`

These files exist in `~/.claude/projects/-home-anshulverma-workspace-workbench/memory/` (dotsynced).

## Provider Changes

### ClaudeProvider → AnthropicLLM (public) + MetaAnthropicLLM (internal)

**Public `AnthropicLLM`:**
```python
class AnthropicLLM(LLMProvider):
    class ProviderConfig(BaseModel):
        api_key: str
        base_url: str = "https://api.anthropic.com"
        model: str = "claude-sonnet-4-20250514"

    def __init__(self, config: ProviderConfig):
        self.client = AsyncAnthropic(api_key=config.api_key, base_url=config.base_url)
        self.model = config.model
```

No SSL context, no cert paths, no proxy. Simple and clean.

**Internal `MetaAnthropicLLM` (in workbench-meta):**
```python
class MetaAnthropicLLM(AnthropicLLM):
    class ProviderConfig(AnthropicLLM.ProviderConfig):
        base_url: str = "https://plugboard.x2p.facebook.net"

    def __init__(self, config: ProviderConfig):
        # Add mTLS cert handling before calling super
        ...
```

Inherits from the public class, adds Meta-specific cert logic.

### LLMQueueScorer

Same pattern: public version uses direct Anthropic API. Internal `MetaQueueScorer` inherits and adds certs.

### ConsoleMessenger (new, public)

```python
class ConsoleMessenger(Messenger):
    class ProviderConfig(BaseModel):
        pass

    async def send_card(self, card_text: str) -> str:
        print(f"\n{'='*60}")
        print(card_text)
        print(f"{'='*60}\n")
        return f"console-{uuid4()}"

    async def poll_responses(self, since_message_id=None) -> list[dict]:
        return []  # Console messenger doesn't poll — responses come via API
```

### GitHubSourceAdapter (new, public)

```python
class GitHubSourceAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        token: str
        repos: list[str] = []

    async def poll(self, config, since=None) -> list[RawItem]:
        # Use PyGithub to poll PRs and issues
        ...
```

## Config Files

### `config.example.yml` (public, external defaults)

```yaml
version: "0.1.0"

server:
  port: 8421
  api_token: ${oc.env:WORKBENCH_API_TOKEN,change-me}

storage:
  postgres_dsn: ${oc.env:WORKBENCH_POSTGRES_DSN,postgres://workbench:workbench@localhost:5432/workbench}

llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  model: claude-sonnet-4-20250514

queue:
  scorer:
    class: workbench.providers.queue_scorer.llm.LLMQueueScorer
    api_key: ${oc.env:ANTHROPIC_API_KEY}
    model: claude-haiku-4-5-20251001
  worker_concurrency: 2

messenger:
  class: workbench.providers.messenger.console.ConsoleMessenger

sources: []

enrichment:
  class: workbench.providers.enrichment.stub.StubEnricher

memory:
  class: workbench.memory.noop.NoopMemoryLayer
```

### `config.meta.yml` (internal, layered override)

```yaml
llm:
  class: workbench_meta.providers.llm.meta_anthropic.MetaAnthropicLLM
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  base_url: https://plugboard.x2p.facebook.net

queue:
  scorer:
    class: workbench_meta.providers.queue_scorer.meta_scorer.MetaQueueScorer
    api_key: ${oc.env:ANTHROPIC_API_KEY}
    base_url: https://plugboard.x2p.facebook.net
    model: claude-haiku-4-5-20251001

messenger:
  class: workbench_meta.providers.messenger.gchat.GoogleChatMessenger
  space_id: ${oc.env:GCHAT_SPACE_ID}
  google_api_script: workbench_meta/lib/google_api.py

sources:
  - class: workbench_meta.providers.source.phabricator.PhabricatorAdapter
    user_phid: ${oc.env:PHABRICATOR_USER_PHID}
```

## workbench-meta Package Structure

```
workbench-meta/
├── pyproject.toml              # declares workbench as dependency
├── Dockerfile                  # FROM workbench:latest, pip install -e .
├── docker-compose.override.yml
├── config.meta.yml
├── workbench_meta/
│   ├── __init__.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   └── meta_anthropic.py
│   │   ├── messenger/
│   │   │   ├── __init__.py
│   │   │   └── gchat.py
│   │   ├── source/
│   │   │   ├── __init__.py
│   │   │   ├── phabricator.py
│   │   │   └── gmail.py
│   │   ├── enrichment/
│   │   │   ├── __init__.py
│   │   │   └── meta.py
│   │   └── queue_scorer/
│   │       ├── __init__.py
│   │       └── meta_scorer.py
│   └── lib/
│       └── google_api.py
├── docs/
│   └── original/               # pre-genericization docs
└── tests/
```

## Genericization Checklist

### Files to genericize (strip Meta references)

- `CLAUDE.md` — remove Plugboard URLs, devgpu references, Meta-specific deployment details
- `CONTEXT.md` — remove Meta-specific source types (Phabricator, Workplace, SEVs, Oncall), keep generic concepts
- `config.example.yml` — external defaults (already covered above)
- `README.md` — write from scratch for OSS audience
- `pyproject.toml` — remove pydantic-settings, aiosqlite (no longer used); add PyGithub

### Git history rewrite

Interactive rebase of 12 commits to clean commit messages:
- Remove Meta Task numbers (T273284990, etc.)
- Remove plugboard URLs
- Remove devgpu hostnames
- Remove ADR references to internal specs
- Keep the commit structure (one commit per logical change)

### Security scan (pre-push)

```bash
grep -rn -i -E '(facebook|meta\.com|fbsource|plugboard|x2p|dcat|/var/facebook|rootcanal|devgpu|\.lla[0-9]|\.prn[0-9]|\.ftw[0-9]|\.scu[0-9])' \
  --include='*.py' --include='*.yml' --include='*.yaml' --include='*.md' \
  --include='*.txt' --include='*.toml' --include='*.json' --include='*.cfg' \
  . | grep -v '.git/' | grep -v '__pycache__/'
```

Must return zero results.

## Sequencing

1. Create `workbench-meta` repo structure + move Meta providers there
2. Create external providers in `workbench` (AnthropicLLM, ConsoleMessenger, GitHubSourceAdapter)
3. Genericize `workbench` (strip Meta refs from all files)
4. Genericize docs (CLAUDE.md, CONTEXT.md, README.md)
5. Add LICENSE (MIT)
6. Rewrite git history
7. Run security scan
8. Push to GitHub
9. Verify: clone on devvm, `pip install -e .`, `podman compose up`, `curl /health`
