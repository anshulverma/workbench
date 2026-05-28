# Workbench

Personal intelligence feed. Ingests from sources, filters noise adaptively, and triages items through interactive cards.

## Quick Start

```bash
# Install
pip install -e .

# Set up PostgreSQL
podman compose up -d postgres

# Configure
cp config.example.yml config.yml
# Edit config.yml: set ANTHROPIC_API_KEY

# Run migrations
alembic upgrade head

# Start the server
workbench serve
```

## Architecture

FastAPI server with PostgreSQL storage, pluggable provider system, and durable queues.

```
Source Adapter → Ingestion Queue → LLM Extraction → Noise Filter → Triage Card → Messenger → User Response → Storage
```

### Providers

All external integrations are pluggable via YAML config:

| Provider | Role | Default |
|----------|------|---------|
| LLM | Extraction, scoring, card generation | AnthropicLLM (Claude API) |
| Messenger | Send triage cards, receive responses | ConsoleMessenger (stdout) |
| Source | Poll external systems for new items | GitHubSourceAdapter (gh CLI) |
| Enrichment | Additional context before triage | StubEnricher |
| Memory | Knowledge graph for preference learning | NoopMemoryLayer |
| Queue Scorer | Urgency scoring at ingest time | LLMQueueScorer (Haiku) |

### Configuration

YAML config with OmegaConf env var interpolation:

```yaml
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: ${oc.env:ANTHROPIC_API_KEY}
```

Custom providers: implement the ABC, add a `ProviderConfig` inner class, reference via `class:` in config.

## CLI

```bash
workbench serve              # Start the server
workbench triage --token T   # Interactive triage from terminal
```

## API

- `POST /api/process` -- Submit content for processing
- `GET /api/items` -- List items
- `GET /api/triage/pending` -- Pending triage cards
- `POST /api/triage/respond` -- Respond to a triage card
- `GET /health` -- Server health + queue stats

## License

MIT
