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
