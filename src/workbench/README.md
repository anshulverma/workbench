# workbench

**Purpose:** the Workbench Python package — a personal intelligence feed that
ingests from configurable sources, filters noise adaptively, and triages items
through interactive cards. This README is the map of the package's layered
taxonomy.

**Layered taxonomy (one line per subpackage):**

- `domain/` — entity vocabulary: pydantic models + enums (the shared domain language).
- `config/` — typed config models, the OmegaConf loader, and the ruamel write-back.
- `runtime/` — ASGI app factory, app-level middleware (auth, correlation id), entrypoint (`runtime.app:app`).
- `telemetry/` — emitted operational signals: metrics, logging, instrumentation, usage aggregation, alerting, log sanitizing.
- `providers/` — pluggable implementations behind base interfaces + the Provider Registry (resolves `class:` paths from YAML).
- `pipeline/` — orchestration stages (extraction, filter, enrichment, triage, scheduler, worker, engine, presenter, …).
- `storage/` — repository interfaces + the PostgreSQL implementation (`postgres/`).
- `api/` — HTTP route modules + API-output rules (redaction).
- `mcp/` — the MCP server and tool definitions (a thin HTTP client to the API).
- `migrations/` — Alembic env + generated version scripts.

Only `__init__.py` (the app `__version__`) and `__main__.py` (the `python -m
workbench` entry) live at this root — no other module.

**Placement rule (decide by primary role; record it in the subpackage's README):**
domain entity/enum → `domain/`; pluggable impl behind a base interface →
`providers/<interface>/`; storage repository → `storage/`; pipeline stage →
`pipeline/`; HTTP route or API-output rule → `api/`; config model/loader/writer →
`config/`; emitted operational signal → `telemetry/`; ASGI app assembly or
app-level middleware → `runtime/`.

**Update this README when** you add a new top-level subpackage or change the
layered taxonomy.
