"""Prometheus metrics for the memory service.

Emits the same ``plugboard_*`` family as the main app (with ``client="memory"``)
for uniform Grafana queries, plus episode-level ``memory_episodes_ingested_total``.
Separate process => separate registry. See ADR 0050 / spec 3.5.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


@dataclass
class MemoryMetrics:
    plugboard_calls: Counter
    plugboard_errors: Counter
    plugboard_tokens: Counter
    plugboard_call_seconds: Histogram
    episodes_ingested: Counter
    ingestion_queue_depth: Gauge
    dead_letter_count: Gauge


def create_metrics(registry: CollectorRegistry | None = None) -> MemoryMetrics:
    kw = {"registry": registry} if registry else {}
    return MemoryMetrics(
        plugboard_calls=Counter(
            "plugboard_calls_total",
            "Plugboard (LLM gateway) call attempts",
            ["client", "model"],
            **kw,
        ),
        plugboard_errors=Counter(
            "plugboard_errors_total",
            "Plugboard call errors",
            ["client", "model", "error_type"],
            **kw,
        ),
        plugboard_tokens=Counter(
            "plugboard_tokens_total",
            "Plugboard tokens by direction (best-effort in the memory service)",
            ["client", "model", "direction"],
            **kw,
        ),
        plugboard_call_seconds=Histogram(
            "plugboard_call_seconds",
            "Plugboard call duration",
            ["client", "model"],
            buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
            **kw,
        ),
        episodes_ingested=Counter(
            "memory_episodes_ingested_total",
            "Episodes recorded into the knowledge graph",
            ["type"],
            **kw,
        ),
        ingestion_queue_depth=Gauge(
            "memory_ingestion_queue_depth",
            "Current memory ingestion queue depth",
            **kw,
        ),
        dead_letter_count=Gauge(
            "memory_dead_letter_count",
            "Current memory dead-letter count",
            **kw,
        ),
    )
