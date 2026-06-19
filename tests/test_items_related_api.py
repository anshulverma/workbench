"""GET /api/items/{path}/related returns entities grouped by type: the UNION of
entity_item_links (joined to its entity tables) and the three FK tables
(triage_card / enrichment_trace / feedback_correction), with counts and a
subtree toggle."""

import pytest
from httpx import AsyncClient, ASGITransport

from workbench.domain import (
    Item,
    ItemCategory,
    ItemOrigin,
    Priority,
    ItemStatus,
    TriageCard,
)

pytestmark = pytest.mark.asyncio


async def _app(stores):
    from fastapi import FastAPI
    from workbench.api import items as items_api

    app = FastAPI()
    app.include_router(items_api.router)
    app.state.stores = stores
    return app


async def test_related_unions_links_and_fk(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t",
            source_id="r1",
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
        )
    )
    # An entity_item_links llm_call row.
    await stores.entity_links.record("llm_call", 991, [root.path])
    # A triage_card FK row at the same item.
    card = TriageCard(card_content={"summary": "s"})
    card.item_id = root.id
    await stores.triage.save_card(card)

    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(f"/api/items/{root.path}/related")
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == root.path
    assert data["counts"].get("llm_call", 0) >= 1
    assert data["counts"].get("triage_card", 0) >= 1
    llm_entries = data["groups"]["llm_call"]
    assert all("entity_type" in e and "id" in e and "label" in e for e in llm_entries)


async def test_related_subtree_toggle(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t",
            source_id="r1",
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.EXTRACTED,
        )
    )
    child = await stores.items.allocate_child(
        root,
        Item(
            source_type="t",
            source_id="r1",
            summary="c",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
        ),
    )
    await stores.entity_links.record("llm_call", 1, [child.path])

    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        shallow = (await ac.get(f"/api/items/{root.path}/related")).json()
        deep = (await ac.get(f"/api/items/{root.path}/related?subtree=true")).json()
    assert shallow["counts"].get("llm_call", 0) == 0
    assert deep["counts"].get("llm_call", 0) == 1


async def test_related_resolves_correlation_only_llm_call(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t",
            source_id="r1",
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
        )
    )
    # Persist an llm_calls row carrying the correlation_id, then a correlation link.
    from datetime import datetime, timezone
    from workbench.domain.llm_calls import LlmCallRecord

    await stores.llm_calls.save_many(
        [
            LlmCallRecord(
                started_at=datetime.now(timezone.utc),
                origin="o",
                purpose="p",
                stage="filter",
                model="m",
                status="ok",
                correlation_id="corr-7",
            )
        ]
    )
    await stores.entity_links.record_by_correlation("llm_call", "corr-7", [root.path])

    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        data = (await ac.get(f"/api/items/{root.path}/related")).json()
    entries = data["groups"]["llm_call"]
    # entity_id was NULL on the link row; the endpoint resolved it via the join.
    assert any(e["id"] is not None for e in entries)
