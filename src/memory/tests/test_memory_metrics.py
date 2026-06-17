import asyncio

import pytest
from prometheus_client import CollectorRegistry

from memory.metrics import create_metrics
from memory.instrumentation import instrument_llm_client, MemoryUsageAggregator
from memory.llm_capture import LlmCallWriter


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


# --- Capture hookup (writer) -------------------------------------------------


class _CaptureConn:
    def __init__(self):
        self.executed = []

    async def fetchval(self, query, *args):
        return "llm_calls" if "to_regclass" in query else None

    async def execute(self, query, *args):
        self.executed.append((query, args))


class _CaptureAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _CapturePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _CaptureAcquire(self._conn)


class _GraphitiStyleClient:
    """Mimics Graphiti's AnthropicClient: messages in, parsed dict out, no usage."""

    async def generate_response(self, messages, response_model=None, **kwargs):
        return {"entities": ["a", "b"]}


@pytest.mark.asyncio
async def test_instrument_with_active_writer_captures_row():
    conn = _CaptureConn()
    writer = LlmCallWriter(pool=_CapturePool(conn), enabled=True)
    await writer.preflight()
    assert writer.active is True

    m = create_metrics(CollectorRegistry())
    client = _GraphitiStyleClient()
    wrapped = instrument_llm_client(client, m, "haiku", writer=writer)

    messages = [
        {"role": "system", "content": "You are an extractor."},
        {"role": "user", "content": "Extract from: hello"},
    ]
    out = await wrapped.generate_response(messages)
    assert out == {"entities": ["a", "b"]}

    # capture is fire-and-forget; let the spawned task run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(conn.executed) == 1
    query, args = conn.executed[0]
    assert "INSERT INTO llm_calls" in query
    # origin / stage are positions 2 and 4 in the INSERT.
    assert args[1] == "memory_subservice"
    assert args[3] == "memory"


@pytest.mark.asyncio
async def test_instrument_capture_failure_does_not_break_call():
    class _FailConn(_CaptureConn):
        async def execute(self, query, *args):
            raise RuntimeError("workbench db down")

    conn = _FailConn()
    writer = LlmCallWriter(pool=_CapturePool(conn), enabled=True)
    await writer.preflight()

    m = create_metrics(CollectorRegistry())
    wrapped = instrument_llm_client(_GraphitiStyleClient(), m, "haiku", writer=writer)
    # The LLM call still returns normally despite the capture write failing.
    out = await wrapped.generate_response([{"role": "user", "content": "x"}])
    assert out == {"entities": ["a", "b"]}
    await asyncio.sleep(0)
    await asyncio.sleep(0)
