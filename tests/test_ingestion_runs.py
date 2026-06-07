import pytest
from datetime import datetime, timedelta, timezone


@pytest.mark.asyncio
async def test_start_finish_run(stores):
    run_id = await stores.ingestion_runs.start_run("src-1")
    assert run_id
    latest = await stores.ingestion_runs.latest_for_source("src-1")
    assert latest.status == "running"
    assert latest.raw_enqueued == 0

    await stores.ingestion_runs.finish_run(run_id, raw_enqueued=7)
    latest = await stores.ingestion_runs.latest_for_source("src-1")
    assert latest.status == "success"
    assert latest.raw_enqueued == 7
    assert latest.finished_at is not None


@pytest.mark.asyncio
async def test_error_run(stores):
    run_id = await stores.ingestion_runs.start_run("src-2")
    await stores.ingestion_runs.error_run(run_id, "boom")
    latest = await stores.ingestion_runs.latest_for_source("src-2")
    assert latest.status == "error"
    assert latest.error == "boom"


@pytest.mark.asyncio
async def test_latest_for_source_none(stores):
    assert await stores.ingestion_runs.latest_for_source("nope") is None


@pytest.mark.asyncio
async def test_recent_for_source(stores):
    for _ in range(3):
        run_id = await stores.ingestion_runs.start_run("src-r")
        await stores.ingestion_runs.finish_run(run_id, raw_enqueued=1)
    recent = await stores.ingestion_runs.recent_for_source("src-r", limit=2)
    assert len(recent) == 2
    assert all(r.source_id == "src-r" for r in recent)


@pytest.mark.asyncio
async def test_timeseries_buckets_by_day(stores):
    run_id = await stores.ingestion_runs.start_run("src-3")
    await stores.ingestion_runs.finish_run(run_id, raw_enqueued=5)
    run_id2 = await stores.ingestion_runs.start_run("src-3")
    await stores.ingestion_runs.finish_run(run_id2, raw_enqueued=3)
    series = await stores.ingestion_runs.timeseries(days=14, bucket="day")
    total = sum(n for _, n in series)
    assert total == 8


@pytest.mark.asyncio
async def test_delete_older_than(stores, pg_pool):
    run_id = await stores.ingestion_runs.start_run("src-old")
    await pg_pool.execute(
        "UPDATE ingestion_runs SET started_at = $1 WHERE id = $2",
        datetime.now(timezone.utc) - timedelta(days=100),
        run_id,
    )
    deleted = await stores.ingestion_runs.delete_older_than(30)
    assert deleted == 1
