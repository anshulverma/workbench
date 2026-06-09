# providers

**Purpose:** pluggable implementations behind base interfaces, resolved from YAML via the Provider Registry.

**What belongs here:** concrete provider implementations grouped under their interface
subfolder, the base interface for each family, and `registry.py` (the Provider Registry
that resolves `class:` paths from config via `importlib`).

Interface subfolders:

- `llm/` — LLM providers (also hosts `plugboard.py`, the LLM-gateway call sink)
- `source/` — SourceAdapter providers
- `messenger/` — Messenger providers
- `queue_scorer/` — QueueScorer providers
- `enrichment/` — ContextEnricher providers
- `connection/` — Connection providers
- `change_detector/` — ChangeDetector providers
- `doc_reader/` — DocReader interface (latent/unwired: a base interface is defined but no
  concrete implementation exists yet)
- `memory/` — MemoryLayer providers (was `workbench/memory/`)

Plus `registry.py` at this level.

**What does NOT belong here:** cross-cutting concerns (telemetry, runtime wiring), domain
models, pipeline stages, or storage repositories. The registry resolves provider modules
dynamically, so it must not statically import provider implementation modules.

**Update this README when** you add a new KIND of code here (a new provider interface
family) — not for every new file.
