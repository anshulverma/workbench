# tests/test_metrics.py

import pytest
from prometheus_client import CollectorRegistry

from workbench.metrics import create_metrics


def test_all_metrics_registered():
    """All expected metrics are created."""
    registry = CollectorRegistry()
    m = create_metrics(registry)
    assert m.items_ingested is not None
    assert m.adapter_polls is not None
    assert m.adapter_poll_seconds is not None
    assert m.llm_calls is not None
    assert m.llm_errors is not None
    assert m.llm_call_seconds is not None
    assert m.items_triaged is not None
    assert m.items_dropped is not None
    assert m.pipeline_stage_seconds is not None
    assert m.enrichment_seconds is not None
    assert m.enrichment_errors is not None
    assert m.identity_merges is not None
    assert m.cards_generated is not None
    assert m.alerts_sent is not None
    assert m.ingestion_queue_depth is not None
    assert m.triage_queue_depth is not None
    assert m.dead_letter_count is not None
    assert m.connection_healthy is not None


def test_plugboard_metrics_exist():
    from prometheus_client import CollectorRegistry
    from workbench.metrics import create_metrics

    m = create_metrics(CollectorRegistry())
    m.plugboard_calls.labels(client="main_llm", model="m").inc()
    m.plugboard_tokens.labels(client="main_llm", model="m", direction="input").inc(10)
    m.plugboard_items.labels(client="main_llm", model="m").inc(3)
    m.plugboard_errors.labels(client="main_llm", model="m", error_type="X").inc()
    m.plugboard_call_seconds.labels(client="main_llm", model="m").observe(0.5)
