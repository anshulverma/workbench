"""Test that /api/feedback/* endpoints carry the new typed correction/task fields end-to-end.

This verifies Task 1's domain/storage changes flow through the API layer.
"""

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _app(stores):
    """Build a minimal FastAPI app with the feedback router and stores."""
    from fastapi import FastAPI
    from workbench.api import feedback

    app = FastAPI()
    app.include_router(feedback.router)
    app.state.stores = stores
    return app


async def test_post_and_get_task_with_typed_fields(stores):
    """POST /api/feedback/tasks + GET accept/return the new typed fields."""
    app = await _app(stores)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = {
            "filter_id": "5",
            "item_id": 1,
            "item_summary": "fix the thing",
            "from_outcome": "drop",
            "to_outcome": "include",
            "from_label": "Drop",
            "to_label": "Keep",
            "filter_prompt": "Drop noise",
            "proposed_prompt": "Drop noise but keep X",
            "kind": "filter-tuning",
            "correction_ids": [],
            "status": "open",
        }
        r = await c.post("/api/feedback/tasks", json=body)
        assert r.status_code == 200
        tid = r.json()["id"]

        # GET list + verify typed fields persisted
        got = await c.get("/api/feedback/tasks?status=open")
        row = next(x for x in got.json() if x["id"] == tid)
        assert row["filter_id"] == "5"
        assert row["proposed_prompt"] == "Drop noise but keep X"
        assert row["from_outcome"] == "drop"
        assert row["to_outcome"] == "include"
        assert row["from_label"] == "Drop"
        assert row["to_label"] == "Keep"
        assert row["filter_prompt"] == "Drop noise"
        assert row["kind"] == "filter-tuning"

        # PATCH to applied -> status applied + resolved_at set
        pr = await c.patch(f"/api/feedback/tasks/{tid}?status=applied")
        assert pr.status_code == 200
        assert pr.json()["status"] == "applied"
        assert pr.json()["resolved_at"] is not None


async def test_post_and_get_correction_with_typed_fields(stores):
    """POST /api/feedback/corrections + GET accept/return the new typed fields."""
    app = await _app(stores)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = {
            "item_id": 42,
            "filter_id": "3",
            "item_summary": "review this PR",
            "original_action": "drop",
            "corrected_action": "include",
            "from_label": "Noise",
            "to_label": "Important",
            "reason": "Actually relevant to my work",
        }
        r = await c.post("/api/feedback/corrections", json=body)
        assert r.status_code == 200
        cid = r.json()["id"]

        # GET list + verify typed fields persisted
        got = await c.get(f"/api/feedback/corrections?item_id=42")
        row = next(x for x in got.json() if x["id"] == cid)
        assert row["filter_id"] == "3"
        assert row["item_summary"] == "review this PR"
        assert row["from_label"] == "Noise"
        assert row["to_label"] == "Important"
        assert row["reason"] == "Actually relevant to my work"
