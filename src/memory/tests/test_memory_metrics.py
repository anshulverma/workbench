import pytest
from prometheus_client import CollectorRegistry

from memory.metrics import create_metrics
from memory.instrumentation import instrument_llm_client, MemoryUsageAggregator


def test_memory_metrics_exist():
    m = create_metrics(CollectorRegistry())
    m.plugboard_calls.labels(client="memory", model="h").inc()
    m.plugboard_errors.labels(client="memory", model="h", error_type="X").inc()
    m.plugboard_tokens.labels(client="memory", model="h", direction="input").inc(5)
    m.plugboard_call_seconds.labels(client="memory", model="h").observe(0.2)
    m.episodes_ingested.labels(type="decision").inc()


class _FakeClient:
    def __init__(self):
        self.calls = 0

    async def generate_response(self, *args, **kwargs):
        self.calls += 1
        return {"ok": True}


class _FailingClient:
    async def generate_response(self, *args, **kwargs):
        raise ValueError("boom")


@pytest.mark.asyncio
async def test_instrument_counts_success_and_passes_through():
    m = create_metrics(CollectorRegistry())
    agg = MemoryUsageAggregator()
    inner = _FakeClient()
    wrapped = instrument_llm_client(inner, m, "haiku", aggregator=agg)
    assert wrapped is inner  # type-preserving (same instance)
    out = await wrapped.generate_response("prompt")
    assert out == {"ok": True}
    assert m.plugboard_calls.labels(client="memory", model="haiku")._value.get() == 1
    snap = agg.drain()
    assert snap["haiku"]["calls"] == 1 and snap["haiku"]["errors"] == 0


@pytest.mark.asyncio
async def test_instrument_counts_error_and_reraises():
    m = create_metrics(CollectorRegistry())
    agg = MemoryUsageAggregator()
    wrapped = instrument_llm_client(_FailingClient(), m, "haiku", aggregator=agg)
    with pytest.raises(ValueError):
        await wrapped.generate_response("p")
    assert (
        m.plugboard_errors.labels(
            client="memory", model="haiku", error_type="ValueError"
        )._value.get()
        == 1
    )
    assert agg.drain()["haiku"]["errors"] == 1


def test_instrument_noop_when_no_generate_method():
    class Bare:
        pass

    obj = Bare()
    assert instrument_llm_client(obj, create_metrics(CollectorRegistry()), "m") is obj
