"""Stats & aggregation API tests (Tasks A3 + A4).

Covers repository aggregation methods and the /api/stats/*, /api/jobs (list),
and /api/activity endpoints against the live PostgreSQL test DB.

Fixtures (mock_llm, app_with_state, client) mirror tests/test_api.py.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.models import (
    Item,
    ItemCategory,
    ItemOrigin,
    ItemStatus,
    Priority,
    IngestionQueueEntry,
    QueueEntryStatus,
    PipelineJob,
    JobTrigger,
    JobStatus,
    SourceConfig,
    TriageCard,
    TriageOption,
)


# --------------------------------------------------------------------------- #
# Fixtures (file-local, mirrors test_api.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.extract.return_value = []
    llm.score_relevance.return_value = (50, 50)
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"summary": "test"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    return llm


@pytest_asyncio.fixture
async def app_with_state(stores, mock_llm):
    from workbench.config import AppConfig, ServerConfig, StorageConfig

    test_config = AppConfig(
        storage=StorageConfig(
            postgres_dsn="postgres://workbench:workbench@localhost:5432/workbench"
        ),
        llm={
            "class": "workbench.providers.llm.anthropic.AnthropicLLM",
            "api_key": "test",
        },
        server=ServerConfig(api_token="dev-token-change-me"),
    )

    with patch("workbench.main.get_config", return_value=test_config):
        from workbench.main import create_app

        test_app = create_app()

    # Inject the API token into the BearerTokenMiddleware so auth is enforced
    # deterministically in tests (otherwise it lazily loads config.yml, which
    # fails to resolve ${oc.env:ANTHROPIC_API_KEY} in CI and silently disables
    # auth — the cause of the pre-existing test_api auth failure).
    from workbench.auth import BearerTokenMiddleware

    for mw in test_app.user_middleware:
        if mw.cls is BearerTokenMiddleware:
            mw.kwargs["token"] = "dev-token-change-me"
    test_app.middleware_stack = test_app.build_middleware_stack()

    test_app.state.config = test_config
    test_app.state.stores = stores
    test_app.state.memory = NoopMemoryLayer()
    test_app.state.llm = mock_llm
    test_app.state.enricher = StubEnricher()
    test_app.state.messenger = None
    test_app.state.queue_scorer = None
    test_app.state.sources = []
    test_app.state.pipeline = PipelineEngine(
        stores, NoopMemoryLayer(), mock_llm, StubEnricher()
    )

    yield test_app


@pytest_asyncio.fixture
async def client(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer dev-token-change-me"},
    ) as c:
        yield c


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _item(source, status, priority, category):
    return Item(
        source_type=source,
        source_id="x",
        summary="s",
        category=category,
        origin=ItemOrigin.TRIAGED,
        priority=priority,
        status=status,
    )


# --------------------------------------------------------------------------- #
# A3 — ItemStore aggregations
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_item_count_by_status(stores):
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM)
    )
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P1, ItemCategory.MEETING)
    )
    await stores.items.save_item(
        _item("email", ItemStatus.ARCHIVED, Priority.P2, ItemCategory.INFORMATIONAL)
    )
    assert await stores.items.count_by_status() == {"active": 2, "archived": 1}


@pytest.mark.asyncio
async def test_item_count_by_priority(stores):
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM)
    )
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM)
    )
    assert await stores.items.count_by_priority() == {"P0": 2}


@pytest.mark.asyncio
async def test_item_count_by_category(stores):
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM)
    )
    await stores.items.save_item(
        _item("email", ItemStatus.ACTIVE, Priority.P1, ItemCategory.MEETING)
    )
    assert await stores.items.count_by_category() == {"action_item": 1, "meeting": 1}


@pytest.mark.asyncio
async def test_item_count_by_source(stores):
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM)
    )
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P1, ItemCategory.MEETING)
    )
    await stores.items.save_item(
        _item("email", ItemStatus.ACTIVE, Priority.P2, ItemCategory.INFORMATIONAL)
    )
    assert await stores.items.count_by_source() == {"github": 2, "email": 1}


@pytest.mark.asyncio
async def test_items_recent_orders_by_created_at_desc(stores):
    from datetime import datetime, timedelta, timezone

    older = _item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM)
    older.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    newer = _item("email", ItemStatus.ACTIVE, Priority.P1, ItemCategory.MEETING)
    newer.created_at = datetime.now(timezone.utc)
    await stores.items.save_item(older)
    await stores.items.save_item(newer)
    recent = await stores.items.items_recent(limit=10)
    assert [i.source_type for i in recent] == ["email", "github"]
    assert len(await stores.items.items_recent(limit=1)) == 1


# --------------------------------------------------------------------------- #
# A3 — IngestionQueueStore aggregations
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_queue_count_by_status_and_source(stores):
    for st, src in [
        ("queued", "github"),
        ("processing", "github"),
        ("dead_letter", "email"),
    ]:
        await stores.ingestion_queue.enqueue(
            IngestionQueueEntry(
                raw_content="c",
                source_type=src,
                job_id=f"j-{st}",
                status=QueueEntryStatus(st),
            )
        )
    assert await stores.ingestion_queue.count_by_status() == {
        "queued": 1,
        "processing": 1,
        "dead_letter": 1,
    }
    # raw_enqueued+in_flight = queued+processing only (excludes dead_letter/completed)
    assert await stores.ingestion_queue.count_by_source() == {"github": 2}


# --------------------------------------------------------------------------- #
# A3 — JobStore list + count
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_job_list_and_count(stores):
    for i in range(3):
        await stores.jobs.save_job(
            PipelineJob(
                trigger=JobTrigger.MANUAL,
                status=JobStatus.COMPLETED,
                input_hash=f"h{i}",
            )
        )
    await stores.jobs.save_job(
        PipelineJob(
            trigger=JobTrigger.POLL,
            status=JobStatus.FAILED,
            input_hash="hf",
        )
    )
    assert await stores.jobs.count_jobs() == 4
    assert await stores.jobs.count_jobs(status="failed") == 1
    page = await stores.jobs.list_jobs(limit=2, offset=0)
    assert len(page) == 2
    completed = await stores.jobs.list_jobs(limit=10, offset=0, status="completed")
    assert len(completed) == 3


# --------------------------------------------------------------------------- #
# A4 — Endpoints
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_stats_overview_returns_six_counts(client, app_with_state):
    stores = app_with_state.state.stores
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM)
    )
    await stores.ingestion_queue.enqueue(
        IngestionQueueEntry(
            raw_content="c",
            source_type="github",
            job_id="j1",
            status=QueueEntryStatus.PROCESSING,
        )
    )
    await stores.ingestion_queue.enqueue(
        IngestionQueueEntry(
            raw_content="c",
            source_type="github",
            job_id="j2",
            status=QueueEntryStatus.DEAD_LETTER,
        )
    )
    r = await client.get("/api/stats/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["pending_triage"] == 0
    assert data["in_flight"] == 1
    assert data["dead_letters"] == 1
    assert data["active_items"] == 1
    assert data["sources_enabled"] == 0
    assert data["sources_total"] == 0
    assert data["items"]["by_status"]["active"] == 1
    assert data["items"]["by_priority"]["P0"] == 1
    assert data["items"]["by_category"]["action_item"] == 1
    assert data["items"]["by_source"]["github"] == 1
    assert data["items"]["total"] == 1
    # queue section qualifies counts distinctly
    assert data["queue"]["in_flight"] == 1
    assert data["queue"]["dead_letters"] == 1


@pytest.mark.asyncio
async def test_stats_overview_requires_auth(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/stats/overview")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_stats_queue(client, app_with_state):
    stores = app_with_state.state.stores
    await stores.ingestion_queue.enqueue(
        IngestionQueueEntry(
            raw_content="c",
            source_type="github",
            job_id="j1",
            status=QueueEntryStatus.QUEUED,
        )
    )
    r = await client.get("/api/stats/queue")
    assert r.status_code == 200
    data = r.json()
    assert data["by_status"]["queued"] == 1
    assert data["by_source"]["github"] == 1
    assert data["dead_letter"] == 0


@pytest.mark.asyncio
async def test_stats_sources(client, app_with_state):
    stores = app_with_state.state.stores
    src = SourceConfig(adapter_type="github", config={}, enabled=True)
    await stores.sources.upsert_source(src)
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM)
    )
    # one run recorded
    run_id = await stores.ingestion_runs.start_run(src.id)
    await stores.ingestion_runs.finish_run(run_id, raw_enqueued=5)
    r = await client.get("/api/stats/sources")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["adapter_type"] == "github"
    assert row["items_stored"] == 1
    assert row["health_status"] == "healthy"
    assert row["last_run"] is not None


@pytest.mark.asyncio
async def test_stats_ingestion_timeseries(client, app_with_state):
    stores = app_with_state.state.stores
    src = SourceConfig(adapter_type="github", config={}, enabled=True)
    await stores.sources.upsert_source(src)
    run_id = await stores.ingestion_runs.start_run(src.id)
    await stores.ingestion_runs.finish_run(run_id, raw_enqueued=8)
    r = await client.get("/api/stats/ingestion-timeseries?days=14&bucket=day")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert sum(row["count"] for row in rows) == 8
    assert "date" in rows[0]


@pytest.mark.asyncio
async def test_jobs_list_with_total(client, app_with_state):
    stores = app_with_state.state.stores
    for i in range(3):
        await stores.jobs.save_job(
            PipelineJob(
                trigger=JobTrigger.MANUAL,
                status=JobStatus.COMPLETED,
                input_hash=f"h{i}",
            )
        )
    r = await client.get("/api/jobs?limit=2&offset=0")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert data["limit"] == 2
    assert data["offset"] == 0
    assert len(data["jobs"]) == 2


@pytest.mark.asyncio
async def test_jobs_list_status_filter(client, app_with_state):
    stores = app_with_state.state.stores
    await stores.jobs.save_job(
        PipelineJob(
            trigger=JobTrigger.MANUAL,
            status=JobStatus.COMPLETED,
            input_hash="h0",
        )
    )
    await stores.jobs.save_job(
        PipelineJob(
            trigger=JobTrigger.POLL,
            status=JobStatus.FAILED,
            input_hash="hf",
        )
    )
    r = await client.get("/api/jobs?status=failed")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_get_single_job_still_works(client, app_with_state):
    stores = app_with_state.state.stores
    job = PipelineJob(
        trigger=JobTrigger.MANUAL, status=JobStatus.COMPLETED, input_hash="h"
    )
    await stores.jobs.save_job(job)
    r = await client.get(f"/api/jobs/{job.id}")
    assert r.status_code == 200
    assert r.json()["id"] == job.id


@pytest.mark.asyncio
async def test_activity_returns_recent_items(client, app_with_state):
    stores = app_with_state.state.stores
    await stores.items.save_item(
        _item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM)
    )
    r = await client.get("/api/activity?limit=10")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["source_type"] == "github"


@pytest.mark.asyncio
async def test_activity_requires_auth(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/activity")
        assert r.status_code == 401


# --------------------------------------------------------------------------- #
# B1 — Derived metrics block (Task 16, ADR0039/0040, spec §6)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_overview_metrics_block_present(client):
    body = (await client.get("/api/stats/overview")).json()
    assert "metrics" in body
    for k in [
        "signal_velocity",
        "throughput",
        "efficiency_peak",
        "auto_resolved_pct",
        "avg_triage_seconds",
        "growth_velocity",
        "ingestion_success_rate",
    ]:
        assert k in body["metrics"], k


@pytest.mark.asyncio
async def test_overview_metrics_null_on_empty_denominator(client):
    # no triage cards, no runs, no items, noop memory → n/a fields are None,
    # never fabricated.
    m = (await client.get("/api/stats/overview")).json()["metrics"]
    assert m["avg_triage_seconds"] is None
    assert m["ingestion_success_rate"] is None
    assert m["growth_velocity"] is None  # NoopMemoryLayer
    assert m["auto_resolved_pct"] is None  # zero items in window
    assert m["efficiency_peak"] is None  # no created items in any bucket


@pytest.mark.asyncio
async def test_overview_signal_velocity_counts_recent_items(client, app_with_state):
    from datetime import datetime, timezone

    from workbench.models import Item

    stores = app_with_state.state.stores
    now = datetime.now(timezone.utc)
    for sid, src in (("sv1", "github"), ("sv2", "email")):
        await stores.items.save_item(
            Item(
                source_type=src,
                source_id=sid,
                summary="s",
                category=ItemCategory.ACTION_ITEM,
                origin=ItemOrigin.TRIAGED,
                priority=Priority.P1,
                status=ItemStatus.ACTIVE,
                created_at=now,
            )
        )
    m = (await client.get("/api/stats/overview")).json()["metrics"]
    # both items created "just now" → within the 24h signal-velocity window
    assert m["signal_velocity"] == 2


@pytest.mark.asyncio
async def test_overview_auto_resolved_pct(client, app_with_state):
    from workbench.models import Item

    stores = app_with_state.state.stores
    # one auto-included, one triaged → 50% auto-resolved
    auto = Item(
        source_type="github",
        source_id="a",
        summary="s",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
        status=ItemStatus.ACTIVE,
    )
    triaged = Item(
        source_type="github",
        source_id="b",
        summary="s",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P2,
        status=ItemStatus.ACTIVE,
    )
    await stores.items.save_item(auto)
    await stores.items.save_item(triaged)
    m = (await client.get("/api/stats/overview")).json()["metrics"]
    assert m["auto_resolved_pct"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_overview_avg_triage_seconds_from_triage_cards(client, app_with_state):
    from datetime import datetime, timedelta, timezone

    stores = app_with_state.state.stores
    sent = datetime.now(timezone.utc) - timedelta(minutes=5)
    responded = sent + timedelta(seconds=120)
    card = TriageCard(
        card_content={"summary": "x"},
        options=[TriageOption(label="Skip", action="skip")],
        status="responded",
        sent_at=sent,
        responded_at=responded,
    )
    await stores.triage.save_card(card)
    m = (await client.get("/api/stats/overview")).json()["metrics"]
    # avg of a single 120s span; comes from triage_cards, not items
    assert m["avg_triage_seconds"] == pytest.approx(120, abs=1)


@pytest.mark.asyncio
async def test_overview_ingestion_success_rate(client, app_with_state):
    stores = app_with_state.state.stores
    src = SourceConfig(adapter_type="github", config={}, enabled=True)
    await stores.sources.upsert_source(src)
    ok = await stores.ingestion_runs.start_run(src.id)
    await stores.ingestion_runs.finish_run(ok, raw_enqueued=1)
    bad = await stores.ingestion_runs.start_run(src.id)
    await stores.ingestion_runs.error_run(bad, "boom")
    m = (await client.get("/api/stats/overview")).json()["metrics"]
    # 1 success / 2 total = 0.5 (running runs excluded)
    assert m["ingestion_success_rate"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_overview_efficiency_peak_and_throughput(client, app_with_state):
    from datetime import datetime, timezone

    from workbench.models import Item

    stores = app_with_state.state.stores
    now = datetime.now(timezone.utc)
    # one item created and completed in the current hour bucket → close-rate 1.0
    done = Item(
        source_type="github",
        source_id="d",
        summary="s",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P1,
        status=ItemStatus.DONE,
        created_at=now,
        completed_at=now,
    )
    await stores.items.save_item(done)
    m = (await client.get("/api/stats/overview")).json()["metrics"]
    assert m["throughput"] == 1
    assert m["efficiency_peak"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# B1 — /api/stats/timeseries (Task 17, ADR0039, spec §6)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_timeseries_signal_velocity_zero_filled(client):
    r = await client.get(
        "/api/stats/timeseries?metric=signal_velocity&window=24&bucket=hour"
    )
    assert r.status_code == 200
    series = r.json()
    assert len(series) == 24  # full bucket array, empty buckets count:0 not omitted
    assert all(set(p) == {"bucket", "count"} for p in series)
    assert all(p["count"] == 0 for p in series)  # no items yet


@pytest.mark.asyncio
async def test_timeseries_signal_velocity_counts_items(client, app_with_state):
    from datetime import datetime, timezone

    from workbench.models import Item

    stores = app_with_state.state.stores
    # tz-aware created_at so it lands in a real backward bucket (the legacy
    # naive utcnow() default is stored as a session-tz instant, i.e. future).
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="ts1",
            summary="s",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED,
            priority=Priority.P0,
            status=ItemStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
        )
    )
    r = await client.get(
        "/api/stats/timeseries?metric=signal_velocity&window=24&bucket=hour"
    )
    series = r.json()
    assert sum(p["count"] for p in series) == 1


@pytest.mark.asyncio
async def test_timeseries_throughput_counts_completed(client, app_with_state):
    from datetime import datetime, timezone

    from workbench.models import Item

    stores = app_with_state.state.stores
    now = datetime.now(timezone.utc)
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="c",
            summary="s",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED,
            priority=Priority.P1,
            status=ItemStatus.DONE,
            created_at=now,
            completed_at=now,
        )
    )
    r = await client.get("/api/stats/timeseries?metric=throughput&window=8&bucket=hour")
    assert r.status_code == 200
    series = r.json()
    assert len(series) == 8
    assert sum(p["count"] for p in series) == 1


@pytest.mark.asyncio
async def test_timeseries_rejects_unknown_metric(client):
    r = await client.get("/api/stats/timeseries?metric=bogus&window=24&bucket=hour")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_timeseries_rejects_unknown_bucket(client):
    r = await client.get(
        "/api/stats/timeseries?metric=signal_velocity&window=24&bucket=year"
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_timeseries_day_bucket_full_axis(client):
    r = await client.get(
        "/api/stats/timeseries?metric=signal_velocity&window=7&bucket=day"
    )
    assert r.status_code == 200
    series = r.json()
    assert len(series) == 7
    assert all(p["count"] == 0 for p in series)
