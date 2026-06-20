# api/

**Purpose:** FastAPI route modules — the HTTP surface of Workbench. Each module
is one resource family (items, triage, sources, queue, stats, …) registered on
the app in `runtime/`. Pure HTTP: routes call into `pipeline/`, `storage/`,
`providers/`, and `config/`; they hold no business logic of their own beyond
request/response shaping.

**What belongs here:** route modules (`APIRouter`s), request/response shaping,
and API-output rules such as `redaction.py` (the Redaction Rule — `redact_secrets`
applied to config-derived responses). The auth-token endpoint lives here
(`auth_token.py`); the ASGI auth/correlation middleware does not — it is app
assembly and lives in `runtime/`. The `client_logs.py` module is auth-exempt
client error ingestion — it validates batches and re-emits them through
`structlog.get_logger("workbench.client")` for inclusion in the unified log
stream.

**What does NOT belong here:** domain models (`domain/`), persistence
(`storage/`), pipeline stages (`pipeline/`), provider implementations
(`providers/`), or the log Sanitizing Processor (`telemetry/privacy.py`, distinct
from the API Redaction Rule).

**Update this README when** you add a new kind of code here (a new resource
family or a new API-output rule) — not for every new endpoint.
