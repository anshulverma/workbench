# ADR 0055: DB-Authoritative Config with `.env` Bootstrap; `config.yml` Removed

Workbench config becomes **DB-authoritative** with a two-tier model and the **UI
as the authoritative editing surface**. A gitignored **`.env`** (loaded via
`python-dotenv` into `os.environ`) holds Tier-1 *bootstrap* — Postgres DSN
(required, hard-fail if unset), server host/port/debug, API token, logging
dir/level/format — plus all provider **secret values**. The **DB** holds every
other section: a single-row JSONB **settings document** (`app_settings`, a sparse
override deep-merged over pydantic defaults, storing `${oc.env:...}` references
unresolved) for singletons, and `source_configs` for sources. `config.yml` and
the `ruamel.yaml` write-back are **removed**; the YAML→DB startup re-sync and
dual-write are deleted. `AppConfig` stays the in-memory shape: assembly is
`load_dotenv → BootstrapConfig → connect DB → deep-merge document over defaults →
OmegaConf resolve → AppConfig`. The `__main__`/`cli_main` entrypoints, which bind
uvicorn *before* the lifespan and today read host/port off `config.yml`, are
converted to bind from `BootstrapConfig` (`os.environ`) so boot no longer depends
on the removed file.

**Every Tier-2 section hot-applies** via `PATCH /api/settings/{section}` →
`apply_settings` (validate candidate → construct-all-then-swap-all for providers,
incremental for sources/scheduler → per-section appliers → rebind
`scheduler.config` → copy-on-write swap `app.state.config`, all under
`reload_lock`). This includes live worker-pool resize (swap the semaphore),
scheduler reschedule, presentation, and connections (connections are edited as
the top-level `connections` section through `/api/settings`, not via a new route).
Because `PipelineEngine`,
`WorkbenchScheduler`, and `IngestionQueueWorker` capture config at construction,
appliers mutate those live objects via setters rather than relying on the
`app.state.config` swap alone. Ordering is `validate → persist (DB) → apply`, so a
restart always converges to the user's intent; a settings PATCH re-runs
`load_dotenv(override=False)` so newly added `.env` vars resolve without a restart.

Secrets stay out of the DB: secret fields are identified by `ProviderConfig`
schema metadata, persisted as `${oc.env:...}` references, and **never disclosed in
the `GET /api/settings` body** — `redact_secrets()` runs as a fail-closed backstop
and replaces any secret-keyed value (including the env-ref string) with
`[REDACTED]`. The env-var **name** the UI needs is surfaced only via a separate
per-field `{env_var, resolvable}` resolution map computed from the unredacted
in-memory document (never the value); PATCH rejects raw literals in known-secret
fields. First boot imports a seed
(`WORKBENCH_CONFIG_SEED`, else `config.yml`) into the DB once (atomic, non-empty,
unresolved), then the file is removed; **workbench-meta** uses this seed seam for
its Meta providers, with its full override migration handled separately in that
repo (ADR-0053-style cross-repo ordering: land workbench first).

We chose this over the prior YAML-authoritative-with-DB-mirror model (the
"awkward middle" of dual-write + startup re-sync) because the UI has become the
authoritative interface and one source of truth removes the confusion of the same
config in two places. We chose a sparse JSONB override document over a full
snapshot (drifts from evolving pydantic defaults) and over a column-per-section
table (schema churn on every new section); over env-only/pydantic-settings
(ADR 0005's original rejection of nested provider config in env vars still holds —
hence DB JSONB, not env vars). **Supersedes ADR 0005 (YAML config) and ADR 0013
(YAML write-back), supersedes ADR 0029 (presentation is now hot-applied), and
amends ADR 0017** (the token-vend, loopback boundary, `redact_secrets`
allowlist-on-output, and provider-`class:` allowlist all still hold; the secret
model gains env-ref fields and the `/api/settings` redaction surface).

The trade-offs: hot-applying **connections** needs new connection→dependents
reverse-index machinery (connections were restart-only); the credential flow is a
deliberate two-step (set the value in `.env`, then reference its name in the UI),
and the server never writes `.env`; live worker-pool resize accepts transient
over-subscription for one batch; an apply failure after persist leaves live state
lagging the DB until restart (surfaced as a live-vs-persisted drift flag). We
keep `extra="ignore"` on the config models (making the implicit pydantic default
explicit) so a stale override key from a renamed field never crashes boot. The file-level config `version` concept retires; a
`schema_version` key in the document carries the major-compat check and Alembic
owns document-shape migrations.

**Consequence:** `config/writer.py` and the public `/api/config` route are
deleted (`/api/debug/config` is retained as the read-only debug view); the
`config` KV table is retained for runtime state (watermarks) only.
`api/auth_token.py` keeps vending `config.server.api_token` (now `.env`-sourced;
no rotation exists). CONTEXT.md updates ~15 glossary terms ("Config File" splits
into **Bootstrap Config** + **Settings Document**; **Targeted Hot-Reload** →
**apply_settings**). Per-package READMEs for `config/`, `storage/`, `api/`,
`runtime/` are updated. The `feedback_config_write_back` memory is reversed.
