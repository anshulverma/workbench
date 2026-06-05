# Workbench

Personal intelligence feed. Ingests from configurable sources, filters noise adaptively via preference learning, and triages items through interactive cards.

## Quick Start

```bash
# Clone and configure
cp config.example.yml config.yml
# Edit config.yml: set ANTHROPIC_API_KEY (or export it)

# Start PostgreSQL + server
docker compose up -d

# Or run locally
pip install -e .
alembic upgrade head
workbench serve
```

## Architecture

FastAPI server (Python 3.12+) with PostgreSQL storage, durable queues, and a pluggable provider system.

```
Source Adapter → Ingestion Queue (LLM scoring) → Queue Worker → LLM Extraction
→ Adaptive Noise Filter → Context Enrichment → Triage Card → Messenger → User Response → Storage
```

The server does all heavy lifting. Clients are thin interfaces:
- **CLI** -- `workbench triage` for terminal-based triage
- **Claude Code plugin** -- slash commands wrapping API calls
- **MCP server** -- tool access from any MCP-compatible client
- **Messenger** -- primary surface for triage cards and responses

### Providers

All external integrations are pluggable via YAML config:

| Provider | Role | Default |
|----------|------|---------|
| LLM | Extraction, scoring, card generation | `AnthropicLLM` (Claude Sonnet) |
| Queue Scorer | Urgency scoring at ingest time | `LLMQueueScorer` (Claude Haiku) |
| Messenger | Send triage cards, receive responses | `ConsoleMessenger` (stdout) |
| Source | Poll external systems for new items | `GitHubSourceAdapter` (gh CLI) |
| Enrichment | Additional context before triage | `StubEnricher` |
| Memory | Knowledge graph for preference learning | `NoopMemoryLayer` |

### Configuration

YAML config with [OmegaConf](https://omegaconf.readthedocs.io/) env var interpolation:

```yaml
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  model: claude-sonnet-4-20250514
```

Custom providers: implement the interface, add a `ProviderConfig` inner class, reference via `class:` in config.

## Development

```bash
make setup          # Create venv + install deps
make up             # Build and start services (docker compose)
make down           # Stop services
make logs           # Tail server log file
make test           # Run test suite
make migrate        # Run Alembic migrations
make health         # Check server health
```

## CLI

```bash
workbench serve                        # Start the server
workbench serve --config config.yml    # Explicit config path
workbench triage --token TOKEN         # Interactive triage from terminal
```

## UI Access (Remote / DevGPU)

The web UI is available at `http://localhost:8421/ui/`. When running on a remote host (e.g., devgpu), forward the port via SSH:

```bash
ssh -L 8421:localhost:8421 <remote-host>
```

If using `autossh`, ensure `-L 8421:localhost:8421` is included in your forwarded ports. Autossh will silently skip a port if something else already holds it locally — check with `lsof -i :8421` on your local machine if the UI isn't reachable.

## License

MIT
