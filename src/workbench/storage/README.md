# storage

**Purpose:** the persistence layer — per-entity repository interfaces plus the
factory that bundles them, all backend-agnostic. Concrete implementations live
in subpackages (see `postgres/`).

**What belongs here:** abstract repository interfaces (Repository pattern, one
ABC per domain entity, aggregated in `base.py` as `Stores`), the
`create_stores` factory (`factory.py`, resolves the backend), and the
cross-entity stores that are not tied to one domain model — `adapter_state.py`
(`AdapterStateStore`, source-adapter cursor/state) and `ingestion_runs.py`
(`IngestionRunStore`, per-source ingestion run records).

**What does NOT belong here:** concrete backend code (asyncpg SQL lives in
`postgres/`), domain models (`domain/`), pipeline stages (`pipeline/`), or
provider implementations (`providers/`).

**Update this README when** you add a new KIND of code here (a new repository
interface family or a new storage backend) — not for every new method.
