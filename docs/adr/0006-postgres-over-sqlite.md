# ADR 0006: PostgreSQL as Primary Storage Instead of SQLite

Workbench uses PostgreSQL as its only storage backend in Phase 1, replacing the original plan of SQLite-first with PostgreSQL as a later option. A single PostgreSQL instance hosts two databases: `workbench` (application data) and `memory` (memory service queue). The `memory` database and user are created by an `init-db.sh` script mounted into `/docker-entrypoint-initdb.d/` on first container start.

Schema is managed by Alembic migrations, auto-applied via an entrypoint script (`alembic upgrade head && exec uvicorn ...`) on every container start. Migrations are idempotent — Alembic skips already-applied ones. Migration failure prevents the server from starting, which is visible immediately in container logs. Migrations live at `src/workbench/migrations/`.

We chose this over SQLite-first (Approach A) because: (1) the memory service already requires PostgreSQL in the Podman stack — running SQLite alongside it adds operational complexity (two database engines, two backup strategies, two failure modes) for no benefit; (2) the ingestion queue's concurrent workers (default 2) benefit from PostgreSQL's `SELECT ... FOR UPDATE SKIP LOCKED` for atomic dequeue, which is cleaner than SQLite WAL contention; (3) JSONB columns give native queryable/indexable JSON storage instead of TEXT with `json.loads/json.dumps` round-tripping; (4) building only one storage implementation halves the Phase 1 storage work.

We chose a single PG instance over two separate instances because: for a single-user tool, resource isolation isn't a concern. One backup target, one PG to tune. Simplest operational footprint.

The repository interfaces remain as ABCs, so a SQLite implementation can be added later (zero-infrastructure dev experience).

**Consequence:** The Compose stack has a single `postgres` service (always-on, not behind a profile) with an init script for dual-database setup. `aiosqlite` is replaced by `asyncpg`. The storage factory has one implementation. Alembic migrations live in `src/workbench/migrations/`. The `storage` config section uses `postgres_dsn` instead of `sqlite_path`. The docker-compose separate postgres service for the memory layer is removed — the memory service connects to the shared `postgres` service.
