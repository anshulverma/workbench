import asyncio

import pytest
from unittest.mock import AsyncMock
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.triage import format_card_for_chat
from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.models import (
    ExtractedItem, ItemCategory, RawItem, TriageCard, TriageOption,
    JobTrigger, JobStatus, ItemFilters, ItemStatus,
)


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.extract.return_value = [
        ExtractedItem(
            summary="Review auth PR",
            category=ItemCategory.ACTION_ITEM,
            source_context="ctx",
            raw_item=RawItem(id="D123_100", source_type="diff", source_label="D123", raw_text="test"),
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
    from workbench.models import EntityKnowledge, Relationship, Fact

    mock_memory = AsyncMock()
    mock_memory.query_preferences = AsyncMock(return_value=[
        Fact(content="User prefers auth diffs"),
    ])
    mock_memory.query_entity = AsyncMock(return_value=EntityKnowledge(
        entity_type="github", entity_id="D123_100", facts={"team": "infra", "lang": "python"},
    ))
    mock_memory.query_relationships = AsyncMock(return_value=[
        Relationship(from_entity="alice", to_entity="infra-core", relation="reviews"),
    ])

    item = ExtractedItem(
        summary="Review auth PR",
        category=ItemCategory.ACTION_ITEM,
        source_context="ctx",
        raw_item=RawItem(id="D123_100", source_type="github", source_label="D123", raw_text="test"),
    )

    mock_llm.score_relevance.return_value = (85, 90)
    action, relevance, confidence = await score_and_decide(
        mock_llm, mock_memory, stores.filter_rules, item,
    )

    assert action == "auto_include"
    # Verify all three queries were called
    mock_memory.query_preferences.assert_called_once()
    mock_memory.query_entity.assert_called_once_with("github", "D123_100")
    mock_memory.query_relationships.assert_called_once_with("github", "D123_100")

    # Verify facts passed to LLM include entity and relationship context
    call_args = mock_llm.score_relevance.call_args
    facts_passed = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("preference_facts", [])
    sources = [f.source for f in facts_passed]
    assert "entity" in sources
    assert "relationship" in sources
    assert len(facts_passed) == 3  # 1 preference + 1 entity + 1 relationship


@pytest.mark.asyncio
async def test_score_and_decide_handles_none_entity(stores, mock_llm):
    from workbench.pipeline.filter import score_and_decide
    from workbench.models import Fact

    mock_memory = AsyncMock()
    mock_memory.query_preferences = AsyncMock(return_value=[])
    mock_memory.query_entity = AsyncMock(return_value=None)
    mock_memory.query_relationships = AsyncMock(return_value=[])

    item = ExtractedItem(
        summary="Some item",
        category=ItemCategory.ACTION_ITEM,
        source_context="ctx",
        raw_item=RawItem(id="E1", source_type="email", source_label="email", raw_text="test"),
    )

    mock_llm.score_relevance.return_value = (50, 50)
    action, _, _ = await score_and_decide(
        mock_llm, mock_memory, stores.filter_rules, item,
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

    job = await engine.enqueue("diff content", "diff")
    raw = RawItem(id="D123_100", source_type="diff", source_label="D123", raw_text="diff content")
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 1
    assert items[0].status == ItemStatus.ACTIVE


@pytest.mark.asyncio
async def test_process_raw_item_auto_drop(stores, mock_llm):
    mock_llm.score_relevance.return_value = (10, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    job = await engine.enqueue("spam content", "email")
    raw = RawItem(id="E1", source_type="email", source_label="email", raw_text="spam content")
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 0


@pytest.mark.asyncio
async def test_process_raw_item_triage(stores, mock_llm):
    mock_llm.score_relevance.return_value = (50, 50)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    job = await engine.enqueue("ambiguous content", "email")
    raw = RawItem(id="E2", source_type="email", source_label="email", raw_text="ambiguous content")
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
        id="D123", source_type="diff", source_label="D123",
        raw_text='{"number": 123, "title": "fix auth"}',
        urgency_signals={"type": "pull_request"},
    )
    job = await engine.enqueue(raw.raw_text, "diff")
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 1
    assert items[0].raw_data != {}
    assert items[0].raw_data["raw_text"] == '{"number": 123, "title": "fix auth"}'


@pytest.mark.asyncio
async def test_triage_item_populates_raw_data(stores, mock_llm):
    mock_llm.score_relevance.return_value = (50, 50)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    raw = RawItem(
        id="D456", source_type="diff", source_label="D456",
        raw_text='{"number": 456, "title": "add tests"}',
    )
    job = await engine.enqueue(raw.raw_text, "diff")
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
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.models import RawItem
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    mock_source = AsyncMock()
    mock_source.adapter_type = MagicMock(return_value="github")
    mock_source.poll.return_value = [
        RawItem(id="gh-pr-1", source_type="github", source_label="PR #1", raw_text='{"number":1}'),
        RawItem(id="gh-pr-2", source_type="github", source_label="PR #2", raw_text='{"number":2}'),
    ]

    messenger = AsyncMock()
    scheduler = WorkbenchScheduler(stores, memory, pipeline, messenger, config, sources=[mock_source])

    await scheduler._poll_sources()

    mock_source.poll.assert_called_once()
    assert await stores.ingestion_queue.queue_depth() == 2


@pytest.mark.asyncio
async def test_scheduler_poll_sources_tracks_last_polled(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.models import RawItem
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    mock_source = AsyncMock()
    mock_source.adapter_type = MagicMock(return_value="github")
    mock_source.poll.return_value = [
        RawItem(id="gh-pr-1", source_type="github", source_label="PR #1", raw_text='{"number":1}'),
    ]

    scheduler = WorkbenchScheduler(stores, memory, pipeline, None, config, sources=[mock_source])

    # First poll: since=None (no stored timestamp yet)
    await scheduler._poll_sources()
    assert mock_source.poll.call_args.kwargs["since"] is None

    # Verify last_polled_at was stored in ConfigStore
    stored = await stores.config.get("source_last_polled:github")
    assert stored is not None

    # Second poll: since should be the stored timestamp
    mock_source.poll.reset_mock()
    mock_source.poll.return_value = []
    await scheduler._poll_sources()
    assert mock_source.poll.call_args.kwargs["since"] is not None


@pytest.mark.asyncio
async def test_scheduler_poll_sources_skips_duplicates(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.config import AppConfig, StorageConfig
    from workbench.models import RawItem
    from unittest.mock import AsyncMock, MagicMock

    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )
    memory = NoopMemoryLayer()
    pipeline = PipelineEngine(stores, memory, mock_llm, StubEnricher())

    mock_source = AsyncMock()
    mock_source.adapter_type = MagicMock(return_value="github")
    mock_source.poll.return_value = [
        RawItem(id="gh-pr-1", source_type="github", source_label="PR #1", raw_text='{"number":1}'),
    ]

    scheduler = WorkbenchScheduler(stores, memory, pipeline, None, config, sources=[mock_source])

    await scheduler._poll_sources()
    await scheduler._poll_sources()

    # Second poll returns the same item — dedup should skip it
    assert await stores.ingestion_queue.queue_depth() == 1


@pytest.mark.asyncio
async def test_scheduler_poll_sources_handles_adapter_failure(stores, mock_llm):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.pipeline.engine import PipelineEngine
    from workbench.memory.noop import NoopMemoryLayer
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

    scheduler = WorkbenchScheduler(stores, memory, pipeline, None, config, sources=[failing_source])

    # Should not raise — adapter failures are caught and logged
    await scheduler._poll_sources()
    assert await stores.ingestion_queue.queue_depth() == 0

    # last_polled_at should NOT be updated on failure
    stored = await stores.config.get("source_last_polled:github")
    assert stored is None


@pytest.mark.asyncio
async def test_e2e_enqueue_to_triage_card(stores, mock_llm):
    """Full pipeline: enqueue → worker dequeues → extraction → filter → triage card."""
    from workbench.pipeline.worker import IngestionQueueWorker

    mock_llm.score_relevance.return_value = (50, 50)

    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    worker = IngestionQueueWorker(stores, engine, concurrency=1)

    job = await engine.enqueue("Review the auth migration PR #456", "diff")
    assert job.status == JobStatus.QUEUED
    assert await stores.ingestion_queue.queue_depth() == 1

    worker.start()
    for _ in range(20):
        if await stores.ingestion_queue.queue_depth() == 0:
            break
        await asyncio.sleep(0.1)
    worker.stop()

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

    job = await engine.enqueue("P0 incident: auth service down", "incident")
    worker.start()
    for _ in range(20):
        if await stores.ingestion_queue.queue_depth() == 0:
            break
        await asyncio.sleep(0.1)
    worker.stop()

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

    job = await engine.enqueue("CI bot comment: lint passed", "github")
    worker.start()
    for _ in range(20):
        if await stores.ingestion_queue.queue_depth() == 0:
            break
        await asyncio.sleep(0.1)
    worker.stop()

    assert len(await stores.triage.get_pending()) == 0
    assert len(await stores.items.get_items(ItemFilters())) == 0
