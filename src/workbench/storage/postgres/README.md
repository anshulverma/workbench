# storage/postgres

**Purpose:** the concrete asyncpg implementation of the `storage/` repository
interfaces.

**What belongs here:** the connection `pool.py` (asyncpg pool factory), the
`stores.py` bundle (`create_postgres_stores` wiring every `Pg*Store` into the
`Stores` aggregate), and one module per entity holding its `Pg*Store`
implementation — `items.py`, `triage.py`, `jobs.py`, `ingestion_queue.py`,
`interactions.py`, `filter_rules.py`, `enrichment.py`, `enrichers.py`,
`feedback.py`, `funnel.py`, `llm_calls.py`, `loopbacks.py`, `sources.py`,
`config.py`, `plans.py`, `processed.py`.

**What does NOT belong here:** the abstract repository interfaces (those live in
`storage/`), schema migrations (`migrations/`), or domain models (`domain/`).

**Update this README when** you add a new KIND of code here (a new per-entity
store implementation or a different infrastructure concern) — not for every new
query.
