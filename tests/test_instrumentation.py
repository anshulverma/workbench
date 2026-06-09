# tests/test_instrumentation.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from prometheus_client import CollectorRegistry
from workbench.telemetry.metrics import create_metrics
from workbench.telemetry.instrumentation import InstrumentedSourceAdapter


@pytest.mark.asyncio
async def test_instrumented_adapter_tracks_success():
    registry = CollectorRegistry()
    metrics = create_metrics(registry)
    inner = AsyncMock()
    inner.poll.return_value = [MagicMock(source_type="email") for _ in range(3)]

    adapter = InstrumentedSourceAdapter(inner, "gmail", metrics)
    items = await adapter.poll(datetime.now())

    assert len(items) == 3
    assert metrics.adapter_polls.labels(adapter="gmail", status="success")._value.get() == 1.0


@pytest.mark.asyncio
async def test_instrumented_adapter_tracks_errors():
    registry = CollectorRegistry()
    metrics = create_metrics(registry)
    inner = AsyncMock()
    inner.poll.side_effect = RuntimeError("API error")

    adapter = InstrumentedSourceAdapter(inner, "gmail", metrics)
    with pytest.raises(RuntimeError):
        await adapter.poll(datetime.now())

    assert metrics.adapter_polls.labels(adapter="gmail", status="error")._value.get() == 1.0
