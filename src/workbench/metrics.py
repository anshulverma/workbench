from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


@dataclass
class WorkbenchMetrics:
    # Counters
    items_ingested: Counter
    adapter_polls: Counter
    llm_calls: Counter
    llm_errors: Counter
    items_triaged: Counter
    items_dropped: Counter
    identity_merges: Counter
    cards_generated: Counter
    alerts_sent: Counter

    enrichment_errors: Counter

    # Histograms
    adapter_poll_seconds: Histogram
    llm_call_seconds: Histogram
    pipeline_stage_seconds: Histogram
    enrichment_seconds: Histogram

    # Gauges
    ingestion_queue_depth: Gauge
    triage_queue_depth: Gauge
    dead_letter_count: Gauge
    connection_healthy: Gauge
    tracked_threads: Gauge


def create_metrics(registry: CollectorRegistry | None = None) -> WorkbenchMetrics:
    kw = {"registry": registry} if registry else {}

    return WorkbenchMetrics(
        items_ingested=Counter(
            "workbench_items_ingested_total", "Items ingested from sources",
            ["source_type", "adapter"], **kw,
        ),
        adapter_polls=Counter(
            "workbench_adapter_polls_total", "Source adapter poll attempts",
            ["adapter", "status"], **kw,
        ),
        llm_calls=Counter(
            "workbench_llm_calls_total", "LLM API calls",
            ["method"], **kw,
        ),
        llm_errors=Counter(
            "workbench_llm_errors_total", "LLM API errors",
            ["method", "error_type"], **kw,
        ),
        items_triaged=Counter(
            "workbench_items_triaged_total", "Items triaged by user action",
            ["action"], **kw,
        ),
        items_dropped=Counter(
            "workbench_items_dropped_total", "Items dropped from pipeline",
            ["reason"], **kw,
        ),
        identity_merges=Counter(
            "workbench_identity_merges_total", "Entity identity merges",
            ["resolved_by"], **kw,
        ),
        cards_generated=Counter(
            "workbench_cards_generated_total", "Triage cards generated",
            ["method"], **kw,
        ),
        alerts_sent=Counter(
            "workbench_alerts_sent_total", "Operational alerts sent",
            ["alert_type"], **kw,
        ),
        enrichment_errors=Counter(
            "workbench_enrichment_errors_total", "Enrichment errors",
            ["enricher", "error_type"], **kw,
        ),
        adapter_poll_seconds=Histogram(
            "workbench_adapter_poll_seconds", "Source adapter poll duration",
            ["adapter"], **kw,
        ),
        llm_call_seconds=Histogram(
            "workbench_llm_call_seconds", "LLM call duration",
            ["method"], **kw,
        ),
        pipeline_stage_seconds=Histogram(
            "workbench_pipeline_stage_seconds", "Pipeline stage duration",
            ["stage"], **kw,
        ),
        enrichment_seconds=Histogram(
            "workbench_enrichment_seconds", "Enrichment duration",
            ["enricher"], **kw,
        ),
        ingestion_queue_depth=Gauge(
            "workbench_ingestion_queue_depth", "Current ingestion queue depth",
            **kw,
        ),
        triage_queue_depth=Gauge(
            "workbench_triage_queue_depth", "Current triage queue depth",
            **kw,
        ),
        dead_letter_count=Gauge(
            "workbench_dead_letter_count", "Current dead letter count",
            **kw,
        ),
        connection_healthy=Gauge(
            "workbench_connection_healthy", "Connection health (1=healthy, 0=unhealthy)",
            ["name"], **kw,
        ),
        tracked_threads=Gauge(
            "workbench_tracked_threads", "Tracked chat threads",
            ["adapter"], **kw,
        ),
    )
