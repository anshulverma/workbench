import pytest
from unittest.mock import AsyncMock
from pydantic import BaseModel
from workbench.providers.enrichment.composite import CompositeEnricher
from workbench.providers.enrichment.stub import StubEnricher
from workbench.domain import EnrichmentBudget, ExtractedItem, RawItem, ItemCategory


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
        "context": {
            "thread_id": "t1",
            "entity_refs": [{"type": "person", "id": "email:alice@meta.com"}],
        },
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
    result = await composite.enrich(
        _make_item("unknown"), "shallow", EnrichmentBudget()
    )
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_default_is_stub_when_not_provided():
    composite = CompositeEnricher(enrichers={})
    result = await composite.enrich(
        _make_item("calendar"), "shallow", EnrichmentBudget()
    )
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
    await composite.enrich(
        _make_item("github"), "deep", EnrichmentBudget(), memory=mock_memory
    )
    call_kwargs = enricher.enrich.call_args[1]
    assert call_kwargs["memory"] is mock_memory


class MarkerEnricher:
    """A non-stub enricher create_provider can instantiate from a config dict."""

    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config=None):
        pass

    async def enrich(self, item, depth, budget, *, memory=None):
        return {"calls_made": 1, "time_ms": 0, "context": {"marker": True}}

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_default_only_config_routes_to_default_not_stub():
    """Regression: a `enrichment: {class: X}` config normalizes to
    `{providers: [], default: {class: X}}`. The app must build a composite that
    routes through the configured default — not silently fall back to a no-op
    StubEnricher because `providers` is empty (which left diffs un-enriched, so
    triage cards never got curated hunks)."""
    import sys

    from workbench.config.models import EnrichmentConfig
    from workbench.providers.registry import create_composite_enricher

    sys.modules.setdefault("tests.test_composite_enricher", sys.modules[__name__])

    # The normalized form the config validator produces for `enrichment: {class}`.
    cfg = EnrichmentConfig(
        providers=[],
        default={"class": "tests.test_composite_enricher.MarkerEnricher"},
    )
    enricher = create_composite_enricher(cfg)
    assert isinstance(enricher, CompositeEnricher)
    # The default is the configured provider, not the implicit StubEnricher.
    assert isinstance(enricher.default, MarkerEnricher)
    assert not isinstance(enricher.default, StubEnricher)
    # And it actually routes an unknown source_type through that default.
    result = await enricher.enrich(_make_item("diff"), "deep", EnrichmentBudget())
    assert result["context"] == {"marker": True}


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
