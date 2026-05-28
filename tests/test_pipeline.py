import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.filter import score_and_decide
from workbench.pipeline.triage import format_card_for_chat
from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.models import (
    ExtractedItem, ItemCategory, RawItem, TriageCard, TriageOption,
    FilterRule, JobTrigger, JobStatus,
)
import tempfile, os
from workbench.storage.sqlite import create_sqlite_stores

@pytest_asyncio.fixture
async def stores():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        yield await create_sqlite_stores(db_path)
    finally:
        os.unlink(db_path)

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
async def test_pipeline_auto_include(stores, mock_llm):
    mock_llm.score_relevance.return_value = (85, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    job = await engine.process("diff content", "diff")
    assert job.status == JobStatus.COMPLETED
    assert job.items_extracted == 1
    assert job.items_included == 1
    from workbench.models import ItemFilters
    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 1

@pytest.mark.asyncio
async def test_pipeline_auto_drop(stores, mock_llm):
    mock_llm.score_relevance.return_value = (10, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    job = await engine.process("spam content", "email")
    assert job.items_dropped == 1
    from workbench.models import ItemFilters
    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 0

@pytest.mark.asyncio
async def test_pipeline_triage(stores, mock_llm):
    mock_llm.score_relevance.return_value = (50, 50)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    job = await engine.process("ambiguous content", "email")
    assert job.items_triaged == 1
    pending = await stores.triage.get_pending()
    assert len(pending) == 1

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
