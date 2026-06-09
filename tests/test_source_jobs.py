import pytest
from unittest.mock import AsyncMock
from workbench.config import AppConfig, StorageConfig
from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.domain import SourceConfig
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.scheduler import WorkbenchScheduler


def _config():
    return AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x"),
        llm={"class": "workbench.providers.llm.anthropic.AnthropicLLM", "api_key": "t"},
    )


class _FakeSource:
    def adapter_type(self):
        return "github"

    async def poll(self, since=None):
        return []


def _sched(stores):
    mock_llm = AsyncMock()
    pipeline = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, None)
    return WorkbenchScheduler(
        stores, NoopMemoryLayer(), pipeline, None, _config(), sources=[], llm=mock_llm
    )


@pytest.mark.asyncio
async def test_add_source_job_creates_cron_job(stores):
    sched = _sched(stores)
    src = SourceConfig(
        adapter_type="github", config={}, schedule="*/15 * * * *", enabled=True
    )
    sched.add_source_job(src, _FakeSource())
    job = sched.scheduler.get_job(f"poll_source:{src.id}")
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
    # mapping is keyed by source id, not the prefixed job id
    assert f"poll_source:{src.id}" not in sched._source_by_id
    assert src.id in sched._source_by_id


@pytest.mark.asyncio
async def test_disabled_source_has_no_job(stores):
    sched = _sched(stores)
    src = SourceConfig(
        adapter_type="github", config={}, schedule="*/15 * * * *", enabled=False
    )
    sched.add_source_job(src, _FakeSource())
    assert sched.scheduler.get_job(f"poll_source:{src.id}") is None


@pytest.mark.asyncio
async def test_reschedule_and_remove_source_job(stores):
    sched = _sched(stores)
    src = SourceConfig(
        adapter_type="github", config={}, schedule="*/15 * * * *", enabled=True
    )
    sched.add_source_job(src, _FakeSource())
    src2 = src.model_copy(update={"schedule": "0 * * * *"})
    sched.reschedule_source_job(src2, _FakeSource())
    assert sched.scheduler.get_job(f"poll_source:{src.id}") is not None
    sched.remove_source_job(src.id)
    assert sched.scheduler.get_job(f"poll_source:{src.id}") is None
    assert src.id not in sched._source_by_id


@pytest.mark.asyncio
async def test_invalid_cron_raises(stores):
    sched = _sched(stores)
    src = SourceConfig(
        adapter_type="github", config={}, schedule="not a cron", enabled=True
    )
    with pytest.raises(ValueError):
        sched.add_source_job(src, _FakeSource())


@pytest.mark.asyncio
async def test_no_global_poll_sources_job(stores):
    sched = _sched(stores)
    src = SourceConfig(
        adapter_type="github", config={}, schedule="*/15 * * * *", enabled=True
    )
    sched._source_by_id = {src.id: _FakeSource()}
    sched._db_sources = [src]
    sched.start()
    try:
        # the old global interval job is gone
        assert sched.scheduler.get_job("poll_sources") is None
        # one Source Job per enabled source instead
        assert sched.scheduler.get_job(f"poll_source:{src.id}") is not None
    finally:
        sched.scheduler.shutdown(wait=False)
