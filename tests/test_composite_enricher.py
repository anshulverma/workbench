import pytest
from unittest.mock import AsyncMock
from workbench.providers.enrichment.composite import CompositeEnricher
from workbench.providers.enrichment.stub import StubEnricher
from workbench.models import EnrichmentBudget, ExtractedItem, RawItem, ItemCategory


def _make_item(source_type: str) -> ExtractedItem:
    raw = RawItem(
        id=f"test-{source_type}-1",
        source_type=source_type,
        source_label="test",
        raw_text="{}",
    )
    return ExtractedItem(
        summary="test",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=raw,
    )


@pytest.mark.asyncio
async def test_routes_by_source_type():
    email_enricher = AsyncMock()
    email_enricher.enrich.return_value = {
        "calls_made": 1,
        "time_ms": 50,
        "context": {"thread_id": "t1", "entity_refs": [{"type": "person", "id": "email:alice@meta.com"}]},
    }
    github_enricher = AsyncMock()
    github_enricher.enrich.return_value = {
        "calls_made": 1,
        "time_ms": 30,
        "context": {"author": "alice", "entity_refs": []},
    }

    composite = CompositeEnricher(
        enrichers={"email": email_enricher, "github": github_enricher},
    )
    result = await composite.enrich(_make_item("email"), "shallow", EnrichmentBudget())
    assert result["calls_made"] == 1
    assert result["context"]["thread_id"] == "t1"
    email_enricher.enrich.assert_called_once()
    github_enricher.enrich.assert_not_called()


@pytest.mark.asyncio
async def test_falls_back_to_default():
    composite = CompositeEnricher(enrichers={}, default=StubEnricher())
    result = await composite.enrich(_make_item("unknown"), "shallow", EnrichmentBudget())
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_default_is_stub_when_not_provided():
    composite = CompositeEnricher(enrichers={})
    result = await composite.enrich(_make_item("calendar"), "shallow", EnrichmentBudget())
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_per_enricher_budget():
    enricher = AsyncMock()
    enricher.enrich.return_value = {"calls_made": 0, "time_ms": 0, "context": {}}
    custom_budget = EnrichmentBudget(max_api_calls=8, max_seconds=20)

    composite = CompositeEnricher(
        enrichers={"email": enricher},
        budgets={"email": custom_budget},
    )
    await composite.enrich(_make_item("email"), "shallow", EnrichmentBudget())
    call_args = enricher.enrich.call_args
    assert call_args[0][2] == custom_budget


@pytest.mark.asyncio
async def test_passes_memory_through():
    enricher = AsyncMock()
    enricher.enrich.return_value = {"calls_made": 0, "time_ms": 0, "context": {}}
    mock_memory = AsyncMock()

    composite = CompositeEnricher(enrichers={"github": enricher})
    await composite.enrich(_make_item("github"), "deep", EnrichmentBudget(), memory=mock_memory)
    call_kwargs = enricher.enrich.call_args[1]
    assert call_kwargs["memory"] is mock_memory


@pytest.mark.asyncio
async def test_close_closes_all_enrichers():
    e1 = AsyncMock()
    e2 = AsyncMock()
    default = AsyncMock()

    composite = CompositeEnricher(enrichers={"a": e1, "b": e2}, default=default)
    await composite.close()
    e1.close.assert_called_once()
    e2.close.assert_called_once()
    default.close.assert_called_once()
