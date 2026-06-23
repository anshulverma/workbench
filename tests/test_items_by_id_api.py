# tests/test_items_by_id_api.py
import pytest
from httpx import AsyncClient, ASGITransport

from workbench.domain import (
    Item,
    ItemCategory,
    ItemOrigin,
    Priority,
    ItemStatus,
)

pytestmark = pytest.mark.asyncio


async def _app(stores):
    from fastapi import FastAPI
    from workbench.api import items as items_api

    app = FastAPI()
    app.include_router(items_api.router)
    app.state.stores = stores
    return app


async def _seed(stores) -> Item:
    return await stores.items.create_root(
        Item(
            source_type="diff",
            source_id="D123",
            summary="fix the thing",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
            tags=["infra", "urgent"],
            llm_summary="why it matters",
            enriched_context={"type": "diff", "author": "x"},
            funnel_log=[
                {"label": "noise filter", "outcome": "pass", "stage": "filter"}
            ],
            verdict_action="triage",
            verdict_priority="P2",
            verdict_confidence=42,
        )
    )


async def test_get_item_by_id_returns_rich_shape(stores):
    item = await _seed(stores)
    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get(f"/api/items/by-id/{item.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == item.id
    assert body["tags"] == ["infra", "urgent"]
    assert body["llm_summary"] == "why it matters"
    assert body["enriched_context"] == {"type": "diff", "author": "x"}
    assert body["processing_log"] == [
        {"label": "noise filter", "outcome": "pass", "stage": "filter"}
    ]
    assert body["verdict"] == {"action": "triage", "priority": "P2", "confidence": 42}
    assert body["source_type"] == "diff"


async def test_get_item_by_id_surfaces_triage_card_content(stores):
    """When the item row has no enriched_context/llm_summary, the detail popup
    sources the diff payload (hunks, why-care, metadata) from the item's latest
    triage card."""
    from workbench.domain import TriageCard

    item = await stores.items.create_root(
        Item(
            source_type="diff",
            source_id="D777",
            summary="Diff D777 fixes a check is awaiting review",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
            # No enriched_context / llm_summary on the row.
        )
    )
    await stores.triage.save_card(
        TriageCard(
            item_id=item.id,
            card_content={
                "source_type": "diff",
                "source_url": "https://www.internalfb.com/diff/D777",
                "summary": "Diff D777 fixes a check",
                "sections": {
                    "metadata": {
                        "author": "alice",
                        "team": "infra",
                        "status": "In Review",
                    },
                    "why_care": "A mismatch here causes silent mis-serving.",
                    "hunks": [
                        {
                            "file": "a/x.py",
                            "header": "@@ -1 +1 @@",
                            "code": "+ok",
                            "annotation": "guard added",
                            "rank": 1,
                        }
                    ],
                },
            },
        )
    )

    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get(f"/api/items/by-id/{item.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_summary"] == "A mismatch here causes silent mis-serving."
    ctx = body["enriched_context"]
    assert ctx["type"] == "diff"
    assert ctx["author"] == "alice"
    assert ctx["team"] == "infra"
    assert ctx["status"] == "In Review"
    assert ctx["url"] == "https://www.internalfb.com/diff/D777"
    assert len(ctx["hunks"]) == 1
    assert ctx["hunks"][0]["file"] == "a/x.py"


async def test_get_item_by_id_404_when_missing(stores):
    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get("/api/items/by-id/999999999")
    assert resp.status_code == 404
