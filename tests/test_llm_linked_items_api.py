# tests/test_llm_linked_items_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
from workbench.domain import LlmCallRecord

pytestmark = pytest.mark.asyncio


async def _app(stores):
    from fastapi import FastAPI
    from workbench.api import llm as llm_api

    app = FastAPI()
    app.include_router(llm_api.router)
    app.state.stores = stores
    return app


async def _seed_call(stores, *, correlation_id):
    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="pipeline",
        purpose="extract",
        stage="extract",
        model="claude-4",
        status="ok",
        correlation_id=correlation_id,
    )
    await stores.llm_calls.save_many([rec])
    return (await stores.llm_calls.list_calls(limit=1))[0]  # has .id


async def test_detail_includes_linked_items(stores):
    item = await stores.items.create_root(
        Item(
            source_type="diff",
            source_id="D1",
            summary="the linked item",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
        )
    )
    call = await _seed_call(stores, correlation_id="corr-x")
    await stores.entity_links.record_by_correlation("llm_call", "corr-x", [item.path])

    app = await _app(stores)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/api/llm/calls/llm_{call.id}")
    assert resp.status_code == 200
    linked = resp.json()["linked_items"]
    assert linked == [{"id": item.id, "path": item.path, "summary": "the linked item"}]


async def test_detail_linked_items_empty_without_correlation(stores):
    call = await _seed_call(stores, correlation_id=None)
    app = await _app(stores)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/api/llm/calls/llm_{call.id}")
    assert resp.status_code == 200
    assert resp.json()["linked_items"] == []
