import asyncio

import pytest
from unittest.mock import AsyncMock
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.triage import format_card_for_chat
from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.domain import (
    ExtractedItem,
    Item,
    ItemCategory,
    ItemOrigin,
    Priority,
    RawItem,
    TriageCard,
    TriageOption,
    JobTrigger,
    JobStatus,
    ItemFilters,
    ItemStatus,
)


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.extract.return_value = [
        ExtractedItem(
            summary="Review auth PR",
            category=ItemCategory.ACTION_ITEM,
            source_context="ctx",
            raw_item=RawItem(
                id="D123_100", source_type="diff", source_label="D123", raw_text="test"
            ),
        )
    ]
    llm.score_relevance.return_value = (85, 90)
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"summary": "Review auth PR", "source_type": "diff"},
        options=[TriageOption(label="Add todo (P1)", action="add_todo")],
    )
    return llm


@pytest.mark.asyncio
async def test_score_and_decide_with_entity_and_relationships(stores, mock_llm):
    from workbench.pipeline.filter import score_and_decide
    from workbench.domain import EntityKnowledge, Relationship, Fact

    mock_memory = AsyncMock()
    mock_memory.query_preferences = AsyncMock(
        return_value=[
            Fact(content="User prefers auth diffs"),
        ]
    )
    mock_memory.query_entity = AsyncMock(
        return_value=EntityKnowledge(
            entity_type="github",
            entity_id="D123_100",
            facts={"team": "infra", "lang": "python"},
        )
    )
    mock_memory.query_relationships = AsyncMock(
        return_value=[
            Relationship(
                from_entity="alice", to_entity="infra-core", relation="reviews"
            ),
        ]
    )

    item = ExtractedItem(
        summary="Review auth PR",
        category=ItemCategory.ACTION_ITEM,
        source_context="ctx",
        raw_item=RawItem(
            id="D123_100", source_type="github", source_label="D123", raw_text="test"
        ),
    )

    mock_llm.score_relevance.return_value = (85, 90)
    action, relevance, confidence = await score_and_decide(
        mock_llm,
        mock_memory,
        stores.filter_rules,
        item,
    )

    assert action == "auto_include"
    # Verify all three queries were called
    mock_memory.query_preferences.assert_called_once()
    mock_memory.query_entity.assert_called_once_with("github", "D123_100")
    mock_memory.query_relationships.assert_called_once_with("github", "D123_100")

    # Verify facts passed to LLM include entity and relationship context
    call_args = mock_llm.score_relevance.call_args
    facts_passed = (
        call_args.args[1]
        if len(call_args.args) > 1
        else call_args.kwargs.get("preference_facts", [])
    )
    sources = [f.source for f in facts_passed]
    assert "entity" in sources
    assert "relationship" in sources
    assert len(facts_passed) == 3  # 1 preference + 1 entity + 1 relationship


@pytest.mark.asyncio
async def test_score_and_decide_handles_none_entity(stores, mock_llm):
    from workbench.pipeline.filter import score_and_decide
    from workbench.domain import Fact

    mock_memory = AsyncMock()
    mock_memory.query_preferences = AsyncMock(return_value=[])
    mock_memory.query_entity = AsyncMock(return_value=None)
    mock_memory.query_relationships = AsyncMock(return_value=[])

    item = ExtractedItem(
        summary="Some item",
        category=ItemCategory.ACTION_ITEM,
        source_context="ctx",
        raw_item=RawItem(
            id="E1", source_type="email", source_label="email", raw_text="test"
        ),
    )

    mock_llm.score_relevance.return_value = (50, 50)
    action, _, _ = await score_and_decide(
        mock_llm,
        mock_memory,
        stores.filter_rules,
        item,
    )
    assert action == "triage"


@pytest.mark.asyncio
async def test_enqueue_creates_job(stores, mock_llm):
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    job = await engine.enqueue("test content", "manual")
    assert job.status == JobStatus.QUEUED

    fetched = await stores.jobs.get_job(job.id)
    assert fetched is not None
    assert await stores.ingestion_queue.queue_depth() == 1


@pytest.mark.asyncio
async def test_process_raw_item_auto_include(stores, mock_llm):
    mock_llm.score_relevance.return_value = (85, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    job = await engine.enqueue("diff content", "diff", source_id="D123_100")
    raw = RawItem(
        id="D123_100", source_type="diff", source_label="D123", raw_text="diff content"
    )
    await engine.process_raw_item(raw, job.id)

    # Root (EXTRACTED) + one extracted child (ACTIVE) now share the source id.
    items = await stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
    assert len(items) == 1
    assert items[0].status == ItemStatus.ACTIVE
    assert items[0].parent_item_id is not None


@pytest.mark.asyncio
async def test_process_raw_item_auto_drop(stores, mock_llm):
    mock_llm.score_relevance.return_value = (10, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    job = await engine.enqueue("spam content", "email", source_id="E1")
    raw = RawItem(
        id="E1", source_type="email", source_label="email", raw_text="spam content"
    )
    await engine.process_raw_item(raw, job.id)

    # Dropped items are now persisted (status=DROPPED) so the Ingestion funnel
    # can show what was filtered out, but excluded from the active/triage feeds.
    dropped = await stores.items.get_items(ItemFilters(status=ItemStatus.DROPPED))
    assert len(dropped) == 1
    assert dropped[0].status == ItemStatus.DROPPED
    assert dropped[0].verdict_action == "drop"
    assert dropped[0].funnel_log
    assert await stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE)) == []
    assert (
        await stores.items.get_items(ItemFilters(status=ItemStatus.PENDING_TRIAGE))
        == []
    )


@pytest.mark.asyncio
async def test_process_raw_item_triage(stores, mock_llm):
    mock_llm.score_relevance.return_value = (50, 50)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    job = await engine.enqueue("ambiguous content", "email", source_id="E2")
    raw = RawItem(
        id="E2", source_type="email", source_label="email", raw_text="ambiguous content"
    )
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters(status=ItemStatus.PENDING_TRIAGE))
    assert len(items) == 1
    pending = await stores.triage.get_pending()
    assert len(pending) == 1
    assert pending[0].item_id == items[0].id


def test_format_card_for_chat():
    card = TriageCard(
        card_content={"summary": "Review D123", "source_type": "diff"},
        options=[
            TriageOption(label="Add todo (P1)", action="add_todo"),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = format_card_for_chat(card, position=1, total=3)
    assert "3 items to triage" in text
    assert "Review D123" in text
    assert "1. Add todo (P1)" in text
    assert "2. Skip" in text


@pytest.mark.asyncio
async def test_auto_include_populates_raw_data(stores, mock_llm):
    mock_llm.score_relevance.return_value = (85, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    raw = RawItem(
        id="D123",
        source_type="diff",
        source_label="D123",
        raw_text='{"number": 123, "title": "fix auth"}',
        urgency_signals={"type": "pull_request"},
    )
    job = await engine.enqueue(raw.raw_text, "diff", source_id="D123")
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
    assert len(items) == 1
    assert items[0].raw_data != {}
    assert items[0].raw_data["raw_text"] == '{"number": 123, "title": "fix auth"}'


@pytest.mark.asyncio
async def test_triage_item_populates_raw_data(stores, mock_llm):
    mock_llm.score_relevance.return_value = (50, 50)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    raw = RawItem(
        id="D456",
        source_type="diff",
        source_label="D456",
        raw_text='{"number": 456, "title": "add tests"}',
    )
    job = await engine.enqueue(raw.raw_text, "diff", source_id="D456")
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters(status=ItemStatus.PENDING_TRIAGE))
    assert len(items) == 1
    assert items[0].raw_data["source_type"] == "diff"


def test_format_card_with_enrichment_context():
    card = TriageCard(
        card_content={
            "summary": "Review D123: fix auth",
            "source_type": "github",
            "enrichment": {
                "context": {
                    "author": "alice",
                    "files_changed": 3,
                    "review_status": "changes_requested",
                    "labels": "security, auth",
                }
            },
        },
        options=[
            TriageOption(label="Add todo (P1)", action="add_todo"),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = format_card_for_chat(card)
    assert "alice" in text
    assert "3 files" in text
    assert "changes requested" in text


def test_format_card_without_enrichment():
    card = TriageCard(
        card_content={"summary": "Some item", "source_type": "manual"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card)
    assert "Some item" in text
    # No enrichment line should appear
    assert "By" not in text


@pytest.mark.asyncio
async def test_scheduler_poll_sources_enqueues_items(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.providers.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.domain import RawItem
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    mock_source = AsyncMock()
    mock_source.adapter_type = MagicMock(return_value="github")
    mock_source.supports_monitoring = MagicMock(return_value=False)
    mock_source.poll.return_value = [
        RawItem(
            id="gh-pr-1",
            source_type="github",
            source_label="PR #1",
            raw_text='{"number":1}',
        ),
        RawItem(
            id="gh-pr-2",
            source_type="github",
            source_label="PR #2",
            raw_text='{"number":2}',
        ),
    ]

    messenger = AsyncMock()
    scheduler = WorkbenchScheduler(
        stores, memory, pipeline, messenger, config, sources=[mock_source]
    )
    scheduler._source_by_id = {"src-gh": mock_source}

    await scheduler._poll_one_source("src-gh")

    mock_source.poll.assert_called_once()
    assert await stores.ingestion_queue.queue_depth() == 2


@pytest.mark.asyncio
async def test_scheduler_poll_sources_tracks_last_polled(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.providers.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.domain import RawItem
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    mock_source = AsyncMock()
    mock_source.adapter_type = MagicMock(return_value="github")
    mock_source.supports_monitoring = MagicMock(return_value=False)
    mock_source.poll.return_value = [
        RawItem(
            id="gh-pr-1",
            source_type="github",
            source_label="PR #1",
            raw_text='{"number":1}',
        ),
    ]

    scheduler = WorkbenchScheduler(
        stores, memory, pipeline, None, config, sources=[mock_source]
    )
    scheduler._source_by_id = {"src-gh": mock_source}

    # First poll: since=None (no stored timestamp yet)
    await scheduler._poll_one_source("src-gh")
    assert mock_source.poll.call_args.kwargs["since"] is None

    # Verify last_polled_at was stored in ConfigStore (keyed by source_id)
    stored = await stores.config.get("source_last_polled:src-gh")
    assert stored is not None

    # Second poll: since should be the stored timestamp
    mock_source.poll.reset_mock()
    mock_source.poll.return_value = []
    await scheduler._poll_one_source("src-gh")
    assert mock_source.poll.call_args.kwargs["since"] is not None


@pytest.mark.asyncio
async def test_scheduler_poll_sources_skips_duplicates(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.providers.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.domain import RawItem
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    mock_source = AsyncMock()
    mock_source.adapter_type = MagicMock(return_value="github")
    mock_source.supports_monitoring = MagicMock(return_value=False)
    mock_source.poll.return_value = [
        RawItem(
            id="gh-pr-1",
            source_type="github",
            source_label="PR #1",
            raw_text='{"number":1}',
        ),
    ]

    scheduler = WorkbenchScheduler(
        stores, memory, pipeline, None, config, sources=[mock_source]
    )
    scheduler._source_by_id = {"src-gh": mock_source}

    await scheduler._poll_one_source("src-gh")
    await scheduler._poll_one_source("src-gh")

    # Second poll returns the same item — dedup should skip it
    assert await stores.ingestion_queue.queue_depth() == 1


@pytest.mark.asyncio
async def test_scheduler_poll_sources_handles_adapter_failure(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.providers.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    failing_source = AsyncMock()
    failing_source.adapter_type = MagicMock(return_value="github")
    failing_source.poll.side_effect = Exception("API timeout")

    scheduler = WorkbenchScheduler(
        stores, memory, pipeline, None, config, sources=[failing_source]
    )
    scheduler._source_by_id = {"src-gh": failing_source}

    # Should not raise — adapter failures are caught and recorded as an error run
    await scheduler._poll_one_source("src-gh")
    assert await stores.ingestion_queue.queue_depth() == 0

    # last_polled_at should NOT be updated on failure
    stored = await stores.config.get("source_last_polled:src-gh")
    assert stored is None

    # the failed run is recorded in ingestion_runs
    latest = await stores.ingestion_runs.latest_for_source("src-gh")
    assert latest.status == "error"


@pytest.mark.asyncio
async def test_e2e_enqueue_to_triage_card(stores, mock_llm):
    """Full pipeline: enqueue → worker dequeues → extraction → filter → triage card."""
    from workbench.pipeline.worker import IngestionQueueWorker

    mock_llm.score_relevance.return_value = (50, 50)

    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    worker = IngestionQueueWorker(stores, engine, concurrency=1)

    job = await engine.enqueue(
        "Review the auth migration PR #456", "diff", source_id="D456-e2e"
    )
    assert job.status == JobStatus.QUEUED
    assert await stores.ingestion_queue.queue_depth() == 1

    worker.start()
    for _ in range(20):
        if await stores.ingestion_queue.queue_depth() == 0:
            break
        await asyncio.sleep(0.1)
    await worker.stop()

    assert await stores.ingestion_queue.queue_depth() == 0

    pending = await stores.triage.get_pending()
    assert len(pending) == 1
    assert pending[0].item_id is not None

    items = await stores.items.get_items(ItemFilters(status=ItemStatus.PENDING_TRIAGE))
    assert len(items) == 1
    assert items[0].id == pending[0].item_id
    assert items[0].raw_data != {}

    fetched_job = await stores.jobs.get_job(job.id)
    assert fetched_job.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_e2e_auto_include(stores, mock_llm):
    """Full pipeline: high relevance → auto-include, no triage card."""
    from workbench.pipeline.worker import IngestionQueueWorker

    mock_llm.score_relevance.return_value = (90, 95)

    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    worker = IngestionQueueWorker(stores, engine, concurrency=1)

    job = await engine.enqueue(
        "P0 incident: auth service down", "incident", source_id="INC-1"
    )
    worker.start()
    for _ in range(20):
        if await stores.ingestion_queue.queue_depth() == 0:
            break
        await asyncio.sleep(0.1)
    await worker.stop()

    assert len(await stores.triage.get_pending()) == 0

    items = await stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
    assert len(items) == 1
    assert items[0].raw_data != {}


@pytest.mark.asyncio
async def test_e2e_auto_drop(stores, mock_llm):
    """Full pipeline: low relevance → auto-drop, no item or card."""
    from workbench.pipeline.worker import IngestionQueueWorker

    mock_llm.score_relevance.return_value = (5, 95)

    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    worker = IngestionQueueWorker(stores, engine, concurrency=1)

    job = await engine.enqueue(
        "CI bot comment: lint passed", "github", source_id="GH-ci-1"
    )
    worker.start()
    for _ in range(20):
        if await stores.ingestion_queue.queue_depth() == 0:
            break
        await asyncio.sleep(0.1)
    await worker.stop()

    assert len(await stores.triage.get_pending()) == 0
    # Drop is persisted as a DROPPED item (visible in the funnel), not in the feed.
    dropped = await stores.items.get_items(ItemFilters(status=ItemStatus.DROPPED))
    assert len(dropped) == 1
    assert dropped[0].verdict_action == "drop"
    assert dropped[0].funnel_log
    assert len(await stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))) == 0


@pytest.mark.asyncio
async def test_scheduler_skips_unhealthy_connection(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.providers.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    unhealthy_conn = MagicMock()
    unhealthy_conn.is_healthy.return_value = False

    adapter = AsyncMock()
    adapter.adapter_type = MagicMock(return_value="email")
    adapter._connection = unhealthy_conn
    adapter.poll.return_value = []

    scheduler = WorkbenchScheduler(
        stores,
        memory,
        pipeline,
        None,
        config,
        sources=[adapter],
    )
    scheduler._source_by_id = {"src-email": adapter}
    await scheduler._poll_one_source("src-email")

    adapter.poll.assert_not_called()


# --- S1: auto_drop recording config gate (plan Task 1) ---


@pytest.mark.asyncio
async def test_auto_drop_not_recorded_when_flag_false(monkeypatch):
    from unittest.mock import AsyncMock
    from workbench.pipeline.engine import PipelineEngine
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.domain import ExtractedItem, ItemCategory, RawItem
    import workbench.pipeline.engine as eng

    mem = AsyncMock()
    engine = PipelineEngine(
        AsyncMock(), mem, AsyncMock(), StubEnricher(), record_drop_decisions=False
    )
    ext = ExtractedItem(
        summary="noise",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=RawItem(id="X1", source_type="email", source_label="", raw_text="x"),
    )

    async def fake(*a, **k):
        return ("auto_drop", 10, 95)

    monkeypatch.setattr(eng, "score_and_decide", fake)
    await engine._process_extracted_item(ext, job=None)
    mem.record_pipeline_decision.assert_not_called()


@pytest.mark.asyncio
async def test_auto_drop_recorded_when_flag_true(monkeypatch):
    from unittest.mock import AsyncMock
    from workbench.pipeline.engine import PipelineEngine
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.domain import ExtractedItem, ItemCategory, RawItem
    import workbench.pipeline.engine as eng

    mem = AsyncMock()
    engine = PipelineEngine(
        AsyncMock(), mem, AsyncMock(), StubEnricher(), record_drop_decisions=True
    )
    ext = ExtractedItem(
        summary="noise",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=RawItem(id="X2", source_type="email", source_label="", raw_text="x"),
    )

    async def fake(*a, **k):
        return ("auto_drop", 10, 95)

    monkeypatch.setattr(eng, "score_and_decide", fake)
    await engine._process_extracted_item(ext, job=None)
    mem.record_pipeline_decision.assert_called_once()


# --- Funnel trace + verdict population (Ingestion page wiring) ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,verdict,status",
    [
        ("auto_include", "include", ItemStatus.ACTIVE),
        ("auto_drop", "drop", ItemStatus.DROPPED),
        ("triage", "triage", ItemStatus.PENDING_TRIAGE),
    ],
)
async def test_process_populates_funnel_log_and_verdict(
    monkeypatch, action, verdict, status
):
    """Every routing branch saves an Item carrying a funnel_log + verdict so the
    Ingestion funnel can render it — including auto_drop (status=DROPPED)."""
    from unittest.mock import AsyncMock, MagicMock
    from workbench.pipeline.engine import PipelineEngine
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.domain import ExtractedItem, ItemCategory, RawItem
    import workbench.pipeline.engine as eng

    stores = AsyncMock()
    engine = PipelineEngine(stores, AsyncMock(), AsyncMock(), StubEnricher())
    ext = ExtractedItem(
        summary="x",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=RawItem(id="Z1", source_type="email", source_label="", raw_text="x"),
    )

    async def fake_decide(*a, **k):
        return (action, 42, 88)

    async def fake_enrich(*a, **k):
        return {}

    async def fake_card(*a, **k):
        return MagicMock()

    monkeypatch.setattr(eng, "score_and_decide", fake_decide)
    monkeypatch.setattr(eng, "enrich_item", fake_enrich)
    monkeypatch.setattr(eng, "generate_card", fake_card)

    await engine._process_extracted_item(ext, job=None)

    stores.items.save_item.assert_awaited_once()
    saved = stores.items.save_item.await_args.args[0]
    assert saved.status == status
    assert saved.verdict_action == verdict
    assert saved.verdict_confidence == 88
    assert saved.funnel_log
    assert saved.funnel_log[0]["stage"] == "extract"
    # the relevance stage carries the outcome + reason the UI renders
    rel = next(e for e in saved.funnel_log if e["stage"] == "relevance")
    assert rel["confidence"] == 88
    assert "relevance 42" in rel["reason"]


@pytest.mark.asyncio
async def test_enqueue_births_root_item(stores, mock_llm):
    engine = PipelineEngine(
        stores=stores,
        memory=NoopMemoryLayer(),
        llm=mock_llm,
        enricher=StubEnricher(),
    )
    await engine.enqueue(
        raw_text="some diff text",
        source_type="diff",
        source_id="D-birth-1",
        trigger=JobTrigger.MANUAL,
    )
    root = await stores.items.get_item_by_source_id("diff", "D-birth-1")
    assert root is not None
    assert root.status == ItemStatus.INGESTED
    assert root.path == str(root.id)
    assert root.parent_item_id is None
    assert root.raw_data == {
        "raw_text": "some diff text",
        "source_type": "diff",
        "id": "D-birth-1",
    }


@pytest.mark.asyncio
async def test_enqueue_dedup_does_not_birth_root(stores, mock_llm):
    # First enqueue births the root and marks (source_type, source_id) processed.
    engine = PipelineEngine(
        stores=stores,
        memory=NoopMemoryLayer(),
        llm=mock_llm,
        enricher=StubEnricher(),
    )
    await engine.enqueue(
        raw_text="first text",
        source_type="diff",
        source_id="D-dedup-1",
        trigger=JobTrigger.MANUAL,
    )
    root = await stores.items.get_item_by_source_id("diff", "D-dedup-1")
    assert root is not None
    original_id = root.id

    # Second enqueue dedups (is_processed) and must NOT create another root.
    await engine.enqueue(
        raw_text="second text",
        source_type="diff",
        source_id="D-dedup-1",
        trigger=JobTrigger.MANUAL,
    )
    still = await stores.items.get_item_by_source_id("diff", "D-dedup-1")
    assert still.id == original_id
    assert still.raw_data["raw_text"] == "first text"


@pytest.mark.asyncio
async def test_extraction_creates_depth1_children_under_root(stores, mock_llm):
    from workbench.providers.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher

    engine = PipelineEngine(
        stores=stores,
        memory=NoopMemoryLayer(),
        llm=mock_llm,
        enricher=StubEnricher(),
    )
    job = await engine.enqueue(
        raw_text="diff text body",
        source_type="diff",
        source_id="D-ext-1",
        trigger=JobTrigger.MANUAL,
    )
    root = await stores.items.get_item_by_source_id("diff", "D-ext-1")

    raw = RawItem(
        id="D-ext-1",
        source_type="diff",
        source_label="D-ext-1",
        raw_text="diff text body",
    )
    await engine.process_raw_item(raw, job.id)

    children = await stores.items.get_children(root.id)
    assert len(children) == 1
    child, _ = children[0]
    assert child.path == f"{root.id}.1"
    assert child.parent_item_id == root.id

    refreshed_root = await stores.items.get_item(root.id)
    assert refreshed_root.status == ItemStatus.EXTRACTED


@pytest.mark.asyncio
async def test_get_item_by_source_id_resolves_root_not_child(stores):
    # After a root + child share (source_type, source_id), the source-id
    # resolver must return the root (parent_item_id IS NULL), not the child.
    root = await stores.items.create_root(
        Item(
            source_type="diff",
            source_id="D-res-1",
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority="P2",
            status=ItemStatus.INGESTED,
            raw_data={"raw_text": "{}", "source_type": "diff", "id": "D-res-1"},
        )
    )
    await stores.items.allocate_child(
        root,
        Item(
            source_type="diff",
            source_id="D-res-1",
            summary="child",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED,
            priority="P2",
            status=ItemStatus.ACTIVE,
        ),
    )
    resolved = await stores.items.get_item_by_source_id("diff", "D-res-1")
    assert resolved is not None
    assert resolved.id == root.id
    assert resolved.parent_item_id is None
