# ADR 0015: Dedicated `ingestion_runs` Table for Per-Source Run History and Stats

Per-source "last run", ingested counts, **Source Health Status**, and the ingestion-over-time chart are backed by a new `ingestion_runs` table (one row per poll: `source_id`, `started_at`, `finished_at`, `status` running/success/error, `raw_enqueued`, `error`) with an `IngestionRunStore` repository. Rows are written by `_poll_one_source` at start, finish, and on error. A `RetentionConfig.ingestion_runs_days` controls cleanup.

We chose a dedicated table over the two alternatives: (a) adding `last_run_at`/`ingested_count` columns to `source_configs` mixes mutable operational counters into declarative config and the denormalized count drifts; (b) adding `source_type`/`source_id` to `PipelineJob` and deriving from it conflates a per-raw-item processing unit with a per-poll fetch cycle, muddying "ingestion over time" semantics and making last-run indirect. A run table answers last-run, per-source counts, run history, and time-series from one clean model.

The trade-off is a new table, store, and migration — more surface than denormalized columns — plus a write on every poll. For a single-user tool the write volume is trivial and the model avoids count drift, matching the "do it now, avoid future migrations" preference.

**Consequence:** "Ingested Count" is always qualified as `raw_enqueued` (queue rows), `items_stored` (item rows), or `in_flight` (queued+processing depth) — never a single conflated number. Source Health Status (`never_run`/`healthy`/`erroring`/`disabled`) is derived from the latest `ingestion_runs` row plus the referenced `Connection.is_healthy()`, not stored on `SourceConfig`.
