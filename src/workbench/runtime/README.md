# runtime/

Assembles the running ASGI app: the app factory plus app-level middleware.
The entrypoint is `workbench.runtime.app:app`.

## What belongs here

- `app.py` — the FastAPI app factory (`create_app()`) that exposes the module-level `app`.
- `auth.py` — `BearerTokenMiddleware` (app-level bearer-token auth).
- `middleware.py` — `CorrelationIdMiddleware` (app-level correlation-id wiring).

## What does not belong here

- Domain entity vocabulary — that is `domain/`.
- Emitted operational signals (metrics, logging, instrumentation) — that is `telemetry/`.
- Pluggable provider implementations — that is `providers/`.
- HTTP route modules — those live under `api/`.

## Maintenance

Update this README when you add a new kind of app-assembly or app-level
middleware concern to this package.
