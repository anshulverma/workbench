import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from workbench.models import (
    InteractionEntry,
    Item,
    ItemCategory,
    ItemFilters,
    ItemOrigin,
    ItemStatus,
    ItemUpdate,
    Priority,
)

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("")
async def get_actions(
    request: Request,
    status: str = "active",
    category: str | None = None,
):
    stores = request.app.state.stores

    # Query active items, then filter for action items in Python (FIX 13)
    filters = ItemFilters(status=ItemStatus(status))
    all_items = await stores.items.get_items(filters)

    # Only include items that have action_source set
    items = [i for i in all_items if i.action_source is not None]

    if category:
        items = [i for i in items if i.action_category == category]

    categories = defaultdict(list)
    for item in items:
        cat = item.action_category or "uncategorized"
        parent = None
        if item.parent_item_id:
            parent_item = await stores.items.get_item(item.parent_item_id)
            if parent_item:
                parent = {"id": parent_item.id, "summary": parent_item.summary}
        categories[cat].append(
            {
                "id": item.id,
                "summary": item.summary,
                "priority": item.priority,
                "parent_item": parent,
                "action_source": item.action_source,
                "action_category": item.action_category,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
        )

    return {"categories": dict(categories), "total": len(items)}


class CreateActionBody(BaseModel):
    summary: str
    priority: Priority = Priority.P2
    action_category: str | None = None

    @field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("summary must not be empty")
        return v

    @field_validator("action_category")
    @classmethod
    def _category_normalize(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


@router.post("", status_code=201)
async def create_action(request: Request, body: CreateActionBody):
    """Create a manual Action Item (FAB on the Action Items page).

    Returns the created row in the same shape the GET listing / useActions
    hook consumes. Only named safe fields are serialized (ADR0017
    allowlist-on-output); no config-derived data is exposed.
    """
    stores = request.app.state.stores
    item = Item(
        source_type="manual",
        source_id=str(uuid.uuid4()),
        summary=body.summary,
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.MANUAL,
        priority=body.priority,
        status=ItemStatus.ACTIVE,
        action_source="manual",
        action_category=body.action_category,
    )
    await stores.items.save_item(item)
    return {
        "id": item.id,
        "summary": item.summary,
        "priority": item.priority.value,
        "parent_item": None,
        "action_source": item.action_source,
        "action_category": item.action_category,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


class PriorityUpdate(BaseModel):
    priority: str


class SnoozeRequest(BaseModel):
    hours: int = 4


async def _log_action_lifecycle(
    stores,
    item_id: str,
    action: str,
    summary: str,
    source_type: str,
) -> None:
    """Log an action lifecycle event as an InteractionEntry (FIX 8)."""
    entry = InteractionEntry(
        type="action_lifecycle",
        source_type=source_type,
        item_id=item_id,
        item_summary=summary,
        option_chosen=action,
    )
    await stores.interactions.append(entry)


@router.post("/{item_id}/done")
async def mark_done(request: Request, item_id: str):
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    await stores.items.update_item(item_id, ItemUpdate(status=ItemStatus.DONE))
    await _log_action_lifecycle(
        stores,
        item_id,
        "done",
        item.summary,
        item.source_type,
    )
    return {"status": "done"}


@router.post("/{item_id}/priority")
async def change_priority(request: Request, item_id: str, body: PriorityUpdate):
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    await stores.items.update_item(
        item_id,
        ItemUpdate(priority=Priority(body.priority)),
    )
    await _log_action_lifecycle(
        stores,
        item_id,
        f"priority:{body.priority}",
        item.summary,
        item.source_type,
    )
    return {"status": "updated", "priority": body.priority}


@router.post("/{item_id}/snooze")
async def snooze_action(request: Request, item_id: str, body: SnoozeRequest):
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Action item not found")
    # Snooze keeps the item active but logs a snooze lifecycle event.
    # A future scheduler tick can check snooze_until to suppress
    # the item from briefings until the snooze period expires.
    await _log_action_lifecycle(
        stores,
        item_id,
        f"snooze:{body.hours}h",
        item.summary,
        item.source_type,
    )
    return {"status": "snoozed", "hours": body.hours}
