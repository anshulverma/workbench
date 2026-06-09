# Observability: Plugboard Call Metrics

Workbench reduces and observes calls to the LLM gateway ("plugboard"). This doc
covers the observability stack added by the plugboard-call-reduction work
(ADRs 0048–0051).

## Running the stack

```bash
make up   # brings up postgres, neo4j, memory, workbench, prometheus, grafana
```

All services use `network_mode: host`. Endpoints (loopback — reach via SSH tunnel):

| Service | Endpoint |
|---------|----------|
| Workbench `/metrics` | `http://localhost:8421/metrics` |
| Memory `/metrics` | `http://localhost:8422/metrics` |
| Prometheus | `http://localhost:9090` (targets: `/targets`) |
| Grafana | `http://localhost:3000` (anonymous admin; Prometheus datasource pre-provisioned) |

`/metrics` is **unauthenticated** on both services (ADR 0051), consistent with
`/health`. Prometheus scrapes both targets (`prometheus.yml`).

## Metrics

The `plugboard_*` family is emitted by **both** processes, labelled by `client`
and `model` (Prometheus also adds `job`/`instance` per scrape target):

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `plugboard_calls_total` | counter | client, model | messages.create attempts (retries included) |
| `plugboard_call_seconds` | histogram | client, model | call latency (buckets to 60s) |
| `plugboard_tokens_total` | counter | client, model, direction | input/output/cache tokens (best-effort in the memory service) |
| `plugboard_errors_total` | counter | client, model, error_type | failed calls |
| `plugboard_items_total` | counter | client, model | logical items folded into calls (main app) |
| `memory_episodes_ingested_total` | counter | type | triage/decision/entity episodes (memory service) |

`client` ∈ `main_llm` (Sonnet), `queue_scorer` (Haiku), `memory` (Graphiti/Haiku).

The existing `workbench_llm_*{method}` metrics (method-view latency) are
unchanged and coexist with the transport-view `plugboard_*` family.

### Reading the batching win

Unit-of-work batching (ADR 0048) folds N items into one call:

```
rate(plugboard_items_total{client="main_llm"}[5m])
  / rate(plugboard_calls_total{client="main_llm"}[5m])
```

A ratio > 1 confirms folding (items-per-call). Tokens-per-item is derivable from
`plugboard_tokens_total / plugboard_items_total`.

## Periodic usage summary

Both processes emit one `llm_usage_summary` structlog line every
`metrics.summary_interval_seconds` (default 30), drained from an in-process
aggregator — calls/errors/tokens per (client, model). Empty intervals are
skipped. Gated by `metrics.summary_log`.

## Config

`config.yml` (main app) and `memory-config.yml` (memory service) both gain a
`metrics:` block (`enabled`, `endpoint`, `summary_log`, `summary_interval_seconds`),
plus the main app's `batching:` block and `pipeline.record_drop_decisions`. YAML
stays the source of truth.

## Caveats / follow-ups

- **Memory token capture is best-effort.** Graphiti's `generate_response`
  returns a parsed dict that typically omits Anthropic `usage`, so
  `plugboard_tokens_total{client="memory"}` may stay at 0; calls/latency/errors
  are authoritative (ADR 0050).
- **Curated Grafana dashboards are deferred.** Only the Prometheus datasource is
  provisioned; build dashboards from the metrics above.
- **Meta deployment mounts `config.example.yml` read-only** as the container
  config — the metrics/batching fields apply, but UI config write-back does not
  work there (pre-existing, out of scope).
- **Runtime verification** (`make up`, Prometheus targets UP, Grafana datasource
  live) is the human acceptance step for this slice.
