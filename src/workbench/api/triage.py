from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone, timedelta
from workbench.models import (
    FilterRule, InteractionEntry, Item, ItemCategory, ItemOrigin,
    ItemStatus, ItemUpdate, Priority, TriageResponse,
)

router = APIRouter(prefix="/api", tags=["triage"])


@router.get("/triage/pending")
async def get_pending(request: Request):
    stores = request.app.state.stores
    return await stores.triage.get_pending()


@router.post("/triage/respond")
async def respond_to_triage(response: TriageResponse, request: Request):
    stores = request.app.state.stores
    memory = request.app.state.memory
    card = await stores.triage.get_card(response.card_id)
    if not card:
        raise HTTPException(404, "Triage card not found")

    # Free-text response (choice is None) -- handled in Task 19
    if response.choice is None and response.raw_text:
        # Will be implemented in Task 19
        raise HTTPException(501, "Free-text responses not yet implemented")

    if response.choice is None:
        raise HTTPException(400, "Must provide either choice or raw_text")

    if response.choice < 1 or response.choice > len(card.options):
        raise HTTPException(400, f"Invalid choice {response.choice}, must be 1-{len(card.options)}")

    option = card.options[response.choice - 1]
    await stores.triage.record_response(response.card_id, response)

    if option.action == "add_todo":
        # FIX 32: Priority string -> enum conversion
        priority = Priority(option.details.get("priority", "P2"))
        if card.item_id:
            await stores.items.update_item(
                card.item_id, ItemUpdate(priority=priority, status=ItemStatus.ACTIVE)
            )
        else:
            item = Item(
                source_type=card.card_content.get("source_type", "unknown"),
                source_id=card.id,
                summary=card.card_content.get("summary", ""),
                category=ItemCategory.ACTION_ITEM,
                origin=ItemOrigin.TRIAGED, priority=priority,
            )
            await stores.items.save_item(item)

    elif option.action == "skip":
        if card.item_id:
            await stores.items.update_item(
                card.item_id, ItemUpdate(status=ItemStatus.ARCHIVED)
            )

    elif option.action == "mute_pattern":
        rule = FilterRule(
            source_type=card.card_content.get("source_type"),
            pattern=card.card_content.get("summary", ""),
            action="drop",
            created_from_interaction_id=card.id,
        )
        await stores.filter_rules.add_rule(rule)

    elif option.action == "defer":
        hours = option.details.get("hours", 4)
        card.deferred_until = datetime.now(timezone.utc) + timedelta(hours=hours)
        card.status = "queued"
        await stores.triage.update_card(card)

    elif option.action == "other":
        # "Other" option transitions to awaiting_followup -- handled in Task 19
        card.status = "awaiting_followup"
        await stores.triage.update_card(card)

    # Log interaction
    entry = InteractionEntry(
        source_type=card.card_content.get("source_type", "unknown"),
        item_id=card.item_id,
        item_summary=card.card_content.get("summary", ""),
        triage_card_full=card.model_dump(),
        options_presented=[o.model_dump() for o in card.options],
        option_chosen=option.label,
        choice_index=response.choice,
    )
    await stores.interactions.append(entry)
    await memory.record_triage(card, response)

    return {"status": "recorded", "action": option.action}
