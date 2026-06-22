# tests/test_entity_links_linked_items.py
import pytest

from workbench.domain import (
    Item,
    ItemCategory,
    ItemOrigin,
    Priority,
    ItemStatus,
)

pytestmark = pytest.mark.asyncio


async def _seed_item(stores, summary: str) -> Item:
    return await stores.items.create_root(
        Item(
            source_type="diff",
            source_id=f"D{summary}",
            summary=summary,
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
        )
    )


async def test_linked_items_for_correlation_returns_joined_items(stores):
    a = await _seed_item(stores, "alpha")
    b = await _seed_item(stores, "beta")
    await stores.entity_links.record_by_correlation(
        "llm_call", "corr-1", [a.path, b.path]
    )

    out = await stores.entity_links.linked_items_for_correlation("corr-1")

    by_id = {li.id: li for li in out}
    assert set(by_id) == {a.id, b.id}
    assert by_id[a.id].summary == "alpha"
    assert by_id[a.id].path == a.path


async def test_linked_items_for_correlation_empty_cases(stores):
    assert await stores.entity_links.linked_items_for_correlation(None) == []
    assert await stores.entity_links.linked_items_for_correlation("nope") == []
