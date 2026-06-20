import pytest
from unittest.mock import AsyncMock
from workbench.config import AppConfig, StorageConfig
from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.domain import JobTrigger, RawItem, SourceConfig
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.scheduler import WorkbenchScheduler


def _config():
    return AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x"),
        llm={"class": "workbench.providers.llm.anthropic.AnthropicLLM", "api_key": "t"},
    )


class _FakeSource:
    def __init__(self, items):
        self._items = items
        self.since_seen = "unset"

    def adapter_type(self):
        return "github"

    async def poll(self, since=None):
        self.since_seen = since
        return self._items


@pytest.mark.asyncio
async def test_poll_one_source_records_run_and_watermark(stores):
    mock_llm = AsyncMock()
    pipeline = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, None)
    # enqueue returns (job, root_path) per the tuple contract.
    pipeline.enqueue = AsyncMock(return_value=(None, None))
    src = SourceConfig(adapter_type="github", config={}, enabled=True)
    await stores.sources.upsert_source(src)
    adapter = _FakeSource(
        [
            RawItem(id="r1", source_type="github", source_label="x", raw_text="t"),
            RawItem(id="r2", source_type="github", source_label="y", raw_text="t2"),
        ]
    )
    sched = WorkbenchScheduler(
        stores,
        NoopMemoryLayer(),
        pipeline,
        None,
        _config(),
        sources=[adapter],
        llm=mock_llm,
    )
    sched._source_by_id = {src.id: adapter}

    await sched._poll_one_source(src.id, JobTrigger.POLL)

    latest = await stores.ingestion_runs.latest_for_source(src.id)
    assert latest.status == "success"
    assert latest.raw_enqueued == 2
    assert pipeline.enqueue.await_count == 2
    wm = await stores.config.get(f"source_last_polled:{src.id}")
    assert wm is not None


@pytest.mark.asyncio
async def test_poll_one_source_error_marks_run(stores):
    mock_llm = AsyncMock()
    pipeline = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, None)
    src = SourceConfig(adapter_type="github", config={}, enabled=True)
    await stores.sources.upsert_source(src)

    class _Boom:
        def adapter_type(self):
            return "github"

        async def poll(self, since=None):
            raise RuntimeError("kaboom")

    sched = WorkbenchScheduler(
        stores, NoopMemoryLayer(), pipeline, None, _config(), sources=[], llm=mock_llm
    )
    sched._source_by_id = {src.id: _Boom()}

    await sched._poll_one_source(src.id, JobTrigger.POLL)
    latest = await stores.ingestion_runs.latest_for_source(src.id)
    assert latest.status == "error"
    assert "kaboom" in latest.error


@pytest.mark.asyncio
async def test_poll_one_source_migrates_legacy_watermark(stores):
    mock_llm = AsyncMock()
    pipeline = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, None)
    pipeline.enqueue = AsyncMock()
    src = SourceConfig(adapter_type="github", config={}, enabled=True)
    await stores.sources.upsert_source(src)
    await stores.config.set("source_last_polled:github", "2026-06-01T00:00:00+00:00")
    adapter = _FakeSource([])
    sched = WorkbenchScheduler(
        stores,
        NoopMemoryLayer(),
        pipeline,
        None,
        _config(),
        sources=[adapter],
        llm=mock_llm,
    )
    sched._source_by_id = {src.id: adapter}

    await sched._poll_one_source(src.id, JobTrigger.POLL)
    # legacy value copied to source_id key and used as since=
    assert adapter.since_seen is not None
    assert adapter.since_seen.year == 2026 and adapter.since_seen.month == 6
    # legacy key left in place (non-destructive)
    assert await stores.config.get("source_last_polled:github") is not None
    # per-source key now populated
    assert await stores.config.get(f"source_last_polled:{src.id}") is not None
