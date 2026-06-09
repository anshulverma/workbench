# telemetry/

Emitted operational signals: metrics, structured logging (including the
Sanitizing Processor), instrumentation wrappers, LLM usage aggregation, and
alerting.

## What belongs here

- `metrics.py` — Prometheus metric definitions and the `WorkbenchMetrics` registry.
- `instrumentation.py` — Instrumented Wrappers that emit metrics/logs around providers.
- `logging.py` — structured logging setup and the Sanitizing Processor.
- `usage_aggregator.py` — LLM usage aggregation over call records.
- `alerting.py` — the Alert Manager.
- `privacy.py` — the Sanitizing Processor used by structured logging.

## What does not belong here

- Web wiring (middleware, auth) — that is `runtime/`.
- Domain entity vocabulary — that is `domain/`.
- Pluggable provider implementations — that is `providers/`.

## Maintenance

Update this README when adding a new telemetry concern.
