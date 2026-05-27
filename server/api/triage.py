from fastapi import APIRouter, HTTPException, Request
from server.models import (
    TriageResponse, Item, ItemCategory, ItemOrigin, Priority,
    FilterRule, InteractionEntry,
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
    if response.choice < 1 or response.choice > len(card.options):
        raise HTTPException(400, f"Invalid choice {response.choice}, must be 1-{len(card.options)}")

    option = card.options[response.choice - 1]
    await stores.triage.record_response(response.card_id, response)

    if option.action == "add_todo":
        priority = Priority(option.details.get("priority", "P2"))
        item = Item(
            source_type=card.card_content.get("source_type", "unknown"),
            source_id=card.id,
            summary=card.card_content.get("summary", ""),
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED,
            priority=priority,
        )
        await stores.items.save_item(item)
    elif option.action == "mute_pattern":
        rule = FilterRule(
            source_type=card.card_content.get("source_type"),
            pattern=card.card_content.get("summary", ""),
            action="drop",
            created_from_interaction_id=card.id,
        )
        await stores.filter_rules.add_rule(rule)

    entry = InteractionEntry(
        source_type=card.card_content.get("source_type", "unknown"),
        item_summary=card.card_content.get("summary", ""),
        triage_card_full=card.card_content,
        options_presented=[o.model_dump() for o in card.options],
        option_chosen=option.label,
    )
    await stores.interactions.append(entry)
    await memory.record_triage(card, response)

    return {"status": "recorded", "action": option.action}
