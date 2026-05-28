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
- External providers: `AnthropicLLM` (direct API, no proxy/certs), `ConsoleMessenger` (prints to stdout, responses via API/CLI), `GitHubSourceAdapter` (polls repos via `gh` CLI)
- Default providers: `StubEnricher`, `NoopMemoryLayer`
- CLI: `workbench serve`, `workbench triage` (interactive stdin-based triage)
- `config.example.yml` with external defaults (api.anthropic.com, ConsoleMessenger)
- Dockerfile, docker-compose.yml, plugin, tests, genericized docs

**`workbench-meta`** (private, `~/workspace/workbench-meta`, dotsync2):
- Meta providers: `MetaAnthropicLLM` (Plugboard + x509 mTLS), `MetaQueueScorer` (same certs), `GoogleChatMessenger` (google_api.py + DCAT), `PhabricatorAdapter` (arc conduit), `GmailAdapter`, `MetaEnricher`
- `lib/google_api.py` (1565 lines, DCAT auth)
- `config.meta.yml` (layered override)
- `docker-compose.override.yml` (volume-mounts meta into public container)
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
# From workbench repo root:
podman compose up -d

# With meta overlay (from workbench-meta):
podman compose -f ~/workspace/workbench/docker-compose.yml \
  -f ~/workspace/workbench-meta/docker-compose.override.yml up -d
```

The override file volume-mounts `workbench-meta` into the public container and pip-installs it at startup — no second Dockerfile needed:

```yaml
# workbench-meta/docker-compose.override.yml
services:
  workbench:
    volumes:
      - ~/workspace/workbench-meta:/opt/workbench-meta:ro
      - ~/workspace/workbench-meta/config.meta.yml:/app/config.override.yml:ro
    command: >
      sh -c "pip install -e /opt/workbench-meta &&
             workbench serve --config /app/config.yml --override /app/config.override.yml"
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
- `src/workbench/providers/llm/anthropic.py` — `AnthropicLLM`: direct `AsyncAnthropic(api_key, base_url="https://api.anthropic.com")`, no certs, no proxy. Takes optional `http_client` param in ProviderConfig for subclass injection.
- `src/workbench/providers/messenger/console.py` — `ConsoleMessenger`: prints triage cards to stdout, `poll_responses` returns `[]`. Responses come via API or CLI.
- `src/workbench/providers/source/github.py` — `GitHubSourceAdapter`: polls GitHub repos for PRs/issues via `gh` CLI (`asyncio.create_subprocess_exec`). No Python library dependency.
- `src/workbench/providers/queue_scorer/llm.py` — genericized: strip cert logic, use direct Anthropic API with optional `http_client`.
- `src/workbench/cli.py` — `workbench triage` command: interactive stdin loop that calls API (GET pending, print card, read choice, POST respond).

Interface cleanup:
- `src/workbench/providers/source/base.py` — `SourceAdapter.poll()` signature changes from `poll(config: dict, since)` to `poll(since)`. Adapters already have config from ProviderConfig construction.

Infrastructure:
- `pyproject.toml` — remove `pydantic-settings`, `aiosqlite` (no longer used). No new deps (gh CLI is external).
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
- `docker-compose.override.yml` — volume-mounts meta package, pip installs at startup

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

### AnthropicLLM (public) + MetaAnthropicLLM (internal)

**Public `AnthropicLLM`** — all LLM business logic lives here (prompts, retry, JSON parsing, template options):
```python
class AnthropicLLM(LLMProvider):
    class ProviderConfig(BaseModel):
        api_key: str
        base_url: str = "https://api.anthropic.com"
        model: str = "claude-sonnet-4-20250514"
        http_client: Any = None  # optional, for subclass injection

    def __init__(self, config: ProviderConfig):
        self.client = AsyncAnthropic(
            api_key=config.api_key, base_url=config.base_url,
            http_client=config.http_client,
        )
        self.model = config.model
        self._http_client = config.http_client

    # extract(), score_relevance(), generate_triage_card(),
    # _call_with_retry(), _extract_json(), _template_options()
    # — all business logic stays here, unchanged from ClaudeProvider
```

**Internal `MetaAnthropicLLM`** — only adds the mTLS transport:
```python
class MetaAnthropicLLM(AnthropicLLM):
    class ProviderConfig(AnthropicLLM.ProviderConfig):
        base_url: str = "https://plugboard.x2p.facebook.net"

    def __init__(self, config: ProviderConfig):
        user = os.environ.get("USER", "anshulverma")
        cert_path = f"/var/facebook/credentials/{user}/agent_x509/claude_code_{user}.pem"
        ca_path = "/var/facebook/rootcanal/ca.pem"
        if os.path.exists(cert_path):
            ssl_ctx = ssl.create_default_context(cafile=ca_path)
            ssl_ctx.load_cert_chain(cert_path)
            config.http_client = httpx.AsyncClient(verify=ssl_ctx)
        super().__init__(config)
```

### LLMQueueScorer

Same pattern: public version uses direct Anthropic API with optional `http_client`. Internal `MetaQueueScorer` inherits and injects the SSL client.

### ConsoleMessenger (new, public)

Server-side component only. Prints cards, returns empty from poll. Triage responses come via API/CLI.

```python
class ConsoleMessenger(Messenger):
    class ProviderConfig(BaseModel):
        pass

    async def send_card(self, card_text: str) -> str:
        msg_id = f"console-{uuid4()}"
        print(f"\n{'='*60}")
        print(card_text)
        print(f"{'='*60}")
        print(f"Respond via: curl -X POST http://localhost:8421/api/triage/respond ...")
        return msg_id

    async def poll_responses(self, since_message_id=None) -> list[dict]:
        return []
```

### `workbench triage` CLI command (new, public)

Interactive client-side triage loop:
```python
# src/workbench/cli.py (triage subcommand)
def triage_interactive(server_url, token):
    """Pull pending cards, print each, read stdin choice, post response."""
    pending = requests.get(f"{server_url}/api/triage/pending", headers=auth).json()
    for i, card in enumerate(pending):
        print(format_card(card, i+1, len(pending)))
        choice = input("Your choice: ")
        requests.post(f"{server_url}/api/triage/respond",
                      json={"card_id": card["id"], "choice": int(choice)}, headers=auth)
```

### GitHubSourceAdapter (new, public)

Uses `gh` CLI via `asyncio.create_subprocess_exec`. Same pattern as PhabricatorAdapter.

```python
class GitHubSourceAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        repos: list[str] = []

    def adapter_type(self) -> str:
        return "github"

    async def poll(self, since=None) -> list[RawItem]:
        items = []
        for repo in self.repos:
            prs = await self._gh_json("pr", "list", "--repo", repo, "--json", "number,title,updatedAt,url")
            for pr in prs:
                items.append(RawItem(
                    id=f"gh-pr-{repo}-{pr['number']}",
                    source_type="github",
                    source_label=f"PR #{pr['number']} — {pr['title']}",
                    raw_text=json.dumps(pr),
                ))
        return items

    async def _gh_json(self, *args) -> list[dict]:
        proc = await asyncio.create_subprocess_exec(
            "gh", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return json.loads(stdout) if proc.returncode == 0 else []
```

### SourceAdapter ABC cleanup

```python
# BEFORE (redundant config param):
class SourceAdapter(ABC):
    async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]: ...

# AFTER:
class SourceAdapter(ABC):
    async def poll(self, since: datetime | None = None) -> list[RawItem]: ...
```

All existing adapters (PhabricatorAdapter, GmailAdapter) updated to match. Scheduler's `_poll_sources` updated to not pass config.

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
├── docker-compose.override.yml # volume-mounts meta, pip installs at startup
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
│   └── original/               # pre-genericization docs from workbench
└── tests/
```

## Genericization Checklist

### Files to genericize (strip Meta references)

- `CLAUDE.md` — remove Plugboard URLs, devgpu references, Meta-specific deployment details
- `CONTEXT.md` — replace Google Chat/Meta-specific terms with generic messenger language, replace Phabricator/SEV examples with GitHub examples, remove XDB/devserver references
- `config.example.yml` — external defaults (already covered above)
- `README.md` — write from scratch for OSS audience
- `pyproject.toml` — remove `pydantic-settings`, `aiosqlite` (no longer used). No new deps added.

### Git history rewrite

Done as the **last step** after all split code is committed. Single interactive rebase pass to clean all commit messages:
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
2. Clean up SourceAdapter ABC (remove redundant `config` param)
3. Create external providers in `workbench` (AnthropicLLM, ConsoleMessenger, GitHubSourceAdapter, genericized LLMQueueScorer)
4. Add `workbench triage` CLI command
5. Delete Meta-specific files from `workbench` (claude.py, google_chat.py, phabricator.py, email_gmail.py, lib/google_api.py)
6. Remove `docs/memory/` from repo
7. Genericize docs (CLAUDE.md, CONTEXT.md, README.md)
8. Add LICENSE (MIT)
9. Update pyproject.toml (remove unused deps)
10. Rewrite git history (single pass, all commits)
11. Run security scan
12. Push to GitHub
13. Verify: clone on devvm, `pip install -e .`, `podman compose up`, `curl /health`
