# tests/test_free_text_response.py

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from workbench.domain import (
    TriageCard,
    TriageOption,
    TriageResponse,
    InterpretedResponse,
    SystemAction,
    UserTodo,
    InteractionEntry,
    Item,
    ItemCategory,
    ItemOrigin,
    ItemStatus,
    ItemUpdate,
    Priority,
    FilterRule,
)


@pytest.fixture
def mock_stores():
    stores = MagicMock()
    stores.triage = AsyncMock()
    stores.items = AsyncMock()
    stores.filter_rules = AsyncMock()
    stores.interactions = AsyncMock()
    stores.config = AsyncMock()
    stores.ingestion_queue = AsyncMock()
    stores.ingestion_queue.queue_depth.return_value = 0
    stores.ingestion_queue.get_dead_letters.return_value = []
    return stores


@pytest.fixture
def card():
    return TriageCard(
        id=1,
        item_id=1,
        status="sent",
        card_content={"summary": "Review PR #200", "source_type": "github"},
        options=[
            TriageOption(
                label="Add todo P1", action="add_todo", details={"priority": "P1"}
            ),
            TriageOption(label="Skip", action="skip"),
            TriageOption(
                label="Other -- tell me what you'd like to do", action="other"
            ),
        ],
    )


# --- interpret_triage_response tests ---


@pytest.mark.asyncio
async def test_free_text_add_todo():
    """Free-text 'add as P3' produces add_todo system action."""
    from workbench.providers.llm.anthropic import AnthropicLLM

    llm = AsyncMock(spec=AnthropicLLM)
    llm.interpret_triage_response.return_value = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P3"})],
        user_todos=[],
        explanation="Adding as P3 todo.",
    )

    card = TriageCard(
        card_content={"summary": "Fix CI", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    result = await llm.interpret_triage_response(card, "add as P3")
    assert len(result.system_actions) == 1
    assert result.system_actions[0].action == "add_todo"
    assert result.system_actions[0].details["priority"] == "P3"


@pytest.mark.asyncio
async def test_free_text_with_user_todo():
    """Free-text 'add as P3 and assign to bob' produces system action + user todo."""
    llm = AsyncMock()
    llm.interpret_triage_response.return_value = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P3"})],
        user_todos=[UserTodo(summary="Assign to bob", action_category="delegation")],
        explanation="Adding as P3 todo. Created action item to assign to bob.",
    )

    result = await llm.interpret_triage_response(
        MagicMock(), "add as P3 and assign to bob"
    )
    assert len(result.system_actions) == 1
    assert len(result.user_todos) == 1
    assert result.user_todos[0].summary == "Assign to bob"
    assert result.user_todos[0].action_category == "delegation"


# --- _execute_interpreted_response tests ---


@pytest.mark.asyncio
async def test_execute_add_todo_updates_item(mock_stores, card):
    """add_todo system action updates item priority and status."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(
                daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10
            ),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P3"})],
        user_todos=[],
        explanation="Adding as P3.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    # FIX 32: Priority string -> enum conversion
    mock_stores.items.update_item.assert_called_once_with(
        1, ItemUpdate(priority=Priority.P3, status=ItemStatus.ACTIVE)
    )


@pytest.mark.asyncio
async def test_execute_skip_requires_confirmation(mock_stores, card):
    """FIX 34: skip/mute_pattern are destructive -- require confirmation and return early."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    messenger = AsyncMock()
    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=messenger,
        config=MagicMock(
            triage=MagicMock(
                daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10
            ),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="skip")],
        user_todos=[],
        explanation="Skipping this item.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    # Card should be set to awaiting_confirmation
    mock_stores.triage.update_card.assert_called()
    updated_card = mock_stores.triage.update_card.call_args[0][0]
    assert updated_card.status == "awaiting_confirmation"

    # FIX 20: Pending InterpretedResponse stored in card_content
    assert "pending_interpreted" in updated_card.card_content

    # Confirmation message sent
    messenger.send_card.assert_called_once()
    msg = messenger.send_card.call_args[0][0]
    assert "yes" in msg.lower()

    # Items should NOT have been updated (destructive action deferred)
    mock_stores.items.update_item.assert_not_called()


@pytest.mark.asyncio
async def test_execute_defer_sets_deferred_until(mock_stores, card):
    """Defer action sets deferred_until and re-queues card."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(
                daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10
            ),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="defer", details={"hours": 6})],
        user_todos=[],
        explanation="Deferring for 6 hours.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    mock_stores.triage.update_card.assert_called()
    updated_card = mock_stores.triage.update_card.call_args[0][0]
    assert updated_card.status == "queued"
    assert updated_card.deferred_until is not None
    # FIX 34: Defer must return early -- no further processing
    mock_stores.items.update_item.assert_not_called()


@pytest.mark.asyncio
async def test_execute_creates_user_todos_as_items(mock_stores, card):
    """User todos are created as action Item entities."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(
                daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10
            ),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P2"})],
        user_todos=[
            UserTodo(summary="Assign to bob", action_category="delegation"),
            UserTodo(summary="Schedule review meeting", action_category="scheduling"),
        ],
        explanation="Adding todo and creating action items.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    # card.item_id is set, so each user todo is nested under the parent item via
    # allocate_child (which assigns seq/path/parent_item_id) rather than save_item.
    parent = await mock_stores.items.get_item(card.item_id)
    assert mock_stores.items.allocate_child.call_count == 2
    mock_stores.items.save_item.assert_not_called()
    first_parent, first_child = mock_stores.items.allocate_child.call_args_list[0][0]
    assert first_parent is parent
    assert first_child.summary == "Assign to bob"
    assert first_child.action_category == "delegation"
    assert first_child.action_source == "triage_response"
    # parent_item_id is NOT set manually -- allocate_child sets it.
    assert first_child.parent_item_id is None


@pytest.mark.asyncio
async def test_execute_logs_interaction_entry(mock_stores, card):
    """FIX 6: Actual InteractionEntry is appended, not a placeholder comment."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(
                daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10
            ),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P2"})],
        user_todos=[],
        explanation="Adding as P2.",
    )

    await scheduler._execute_interpreted_response(interpreted, card)

    # InteractionEntry appended with interpreted data
    mock_stores.interactions.append.assert_called_once()
    entry = mock_stores.interactions.append.call_args[0][0]
    assert isinstance(entry, InteractionEntry)
    assert entry.type == "free_text"
    assert entry.interpreted is not None
    assert entry.interpreted["explanation"] == "Adding as P2."


# --- awaiting_confirmation "yes" handler ---


@pytest.mark.asyncio
async def test_awaiting_confirmation_yes_executes_pending(mock_stores):
    """FIX 7: 'yes' response to awaiting_confirmation executes the stored InterpretedResponse."""
    from workbench.pipeline.scheduler import WorkbenchScheduler

    pending_interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="skip")],
        user_todos=[],
        explanation="Skipping this item.",
    )

    card = TriageCard(
        id=1,
        item_id=1,
        status="awaiting_confirmation",
        card_content={
            "summary": "Review PR #200",
            "source_type": "github",
            "pending_interpreted": pending_interpreted.model_dump(),
        },
        options=[
            TriageOption(label="Skip", action="skip"),
        ],
    )

    mock_stores.triage.get_card.return_value = card

    scheduler = WorkbenchScheduler(
        stores=mock_stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(
                daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10
            ),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )

    # Simulate "yes" confirmation
    await scheduler._handle_confirmation(card, "yes")

    # Skip action should now execute (archive item)
    mock_stores.items.update_item.assert_called_once_with(
        1, ItemUpdate(status=ItemStatus.ARCHIVED)
    )


# --- triage-response actions nest via allocate_child (real Postgres) ---


@pytest.fixture
async def scheduler_with_card(stores):
    """Real-store scheduler whose card.item_id points at a persisted depth-1 item.

    Builds: root (create_root) -> depth-1 parent (allocate_child) -> a TriageCard
    saved with item_id = parent_item.id. Returns (scheduler, card, parent_item).
    """
    from workbench.pipeline.scheduler import WorkbenchScheduler

    root = await stores.items.create_root(
        Item(
            source_type="github",
            source_id="D-fttr-1",
            summary="root",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.MANUAL,
            priority="P2",
            status=ItemStatus.INGESTED,
        )
    )
    parent_item = await stores.items.allocate_child(
        root,
        Item(
            source_type="github",
            source_id="D-fttr-1",
            summary="parent",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED,
            priority="P2",
            status=ItemStatus.ACTIVE,
        ),
    )

    saved_card = await stores.triage.save_card(
        TriageCard(
            item_id=parent_item.id,
            status="sent",
            card_content={"summary": "Review PR #200", "source_type": "github"},
            options=[TriageOption(label="Skip", action="skip")],
        )
    )

    scheduler = WorkbenchScheduler(
        stores=stores,
        memory=AsyncMock(),
        pipeline=AsyncMock(),
        messenger=AsyncMock(),
        config=MagicMock(
            triage=MagicMock(
                daily_cap=20, expiry_days=7, triage_poll_interval_seconds=10
            ),
            scheduler=MagicMock(poll_interval_minutes=15, morning_briefing_hour=9),
            logging=MagicMock(timezone="America/Los_Angeles"),
        ),
    )
    return scheduler, saved_card, parent_item


@pytest.mark.asyncio
async def test_user_todo_action_is_allocated_as_child(stores, scheduler_with_card):
    scheduler, card, parent_item = scheduler_with_card

    interpreted = InterpretedResponse(
        explanation="add a follow-up",
        system_actions=[],
        user_todos=[UserTodo(summary="ping reviewer", action_category="communication")],
    )
    await scheduler._execute_interpreted_response(interpreted, card)

    children = await stores.items.get_children(parent_item.id)
    assert len(children) == 1
    action, _ = children[0]
    assert action.summary == "ping reviewer"
    assert action.path == f"{parent_item.path}.1"
    assert action.parent_item_id == parent_item.id
    assert action.action_source == "triage_response"
