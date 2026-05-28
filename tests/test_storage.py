import pytest
from workbench.models import (
    EnrichmentTrace,
    FilterRule,
    IngestionQueueEntry,
    InteractionEntry,
    Item,
    ItemCategory,
    ItemFilters,
    ItemOrigin,
    ItemStatus,
    ItemUpdate,
    PipelineJob,
    JobTrigger,
    JobStatus,
    Plan,
    PlanFilters,
    PlanUpdate,
    QueueEntryStatus,
    SourceConfig,
    SourceConfigUpdate,
    TraceFilters,
    TriageCard,
    TriageOption,
    TriageResponse,
)


# ── Items ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_item_crud(stores):
    item = Item(
        source_type="diff",
        source_id="D123",
        summary="test",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.MANUAL,
        priority="P1",
    )
    saved = await stores.items.save_item(item)
    assert saved.id == item.id

    fetched = await stores.items.get_item(item.id)
    assert fetched is not None
    assert fetched.summary == "test"

    updated = await stores.items.update_item(item.id, ItemUpdate(priority="P0"))
    assert updated.priority == "P0"

    await stores.items.archive_item(item.id)
    archived = await stores.items.get_item(item.id)
    assert archived is not None
    assert archived.status == ItemStatus.ARCHIVED


@pytest.mark.asyncio
async def test_item_filters(stores):
    await stores.items.save_item(
        Item(
            source_type="diff",
            source_id="D1",
            summary="a",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.MANUAL,
            priority="P0",
        )
    )
    await stores.items.save_item(
        Item(
            source_type="email",
            source_id="E1",
            summary="b",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.MANUAL,
            priority="P3",
        )
    )
    results = await stores.items.get_items(ItemFilters(priority="P0"))
    assert len(results) == 1
    assert results[0].source_id == "D1"


# ── Filter rules ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_rules(stores):
    rule = FilterRule(pattern="CI bot comments", action="drop")
    await stores.filter_rules.add_rule(rule)
    rules = await stores.filter_rules.get_rules()
    assert len(rules) == 1
    assert rules[0].pattern == "CI bot comments"


@pytest.mark.asyncio
async def test_filter_rules_by_source(stores):
    rule1 = FilterRule(source_type="diff", pattern="CI bot", action="drop")
    rule2 = FilterRule(source_type="email", pattern="newsletter", action="drop")
    await stores.filter_rules.add_rule(rule1)
    await stores.filter_rules.add_rule(rule2)
    diff_rules = await stores.filter_rules.get_source_rules("diff")
    assert len(diff_rules) == 1
    assert diff_rules[0].pattern == "CI bot"


# ── Processed dedup ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_processed_dedup(stores):
    assert not await stores.processed.is_processed("diff", "D123_100")
    await stores.processed.mark_processed("diff", "D123_100")
    assert await stores.processed.is_processed("diff", "D123_100")


# ── Interaction log ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_interaction_log(stores):
    entry = InteractionEntry(
        source_type="diff", item_summary="test", option_chosen="1"
    )
    await stores.interactions.append(entry)
    assert await stores.interactions.count() == 1
    entries = await stores.interactions.get_all()
    assert entries[0].option_chosen == "1"


@pytest.mark.asyncio
async def test_interaction_get_since(stores):
    for i in range(5):
        entry = InteractionEntry(
            source_type="diff", item_summary=f"item {i}", option_chosen=str(i)
        )
        await stores.interactions.append(entry)
    entries = await stores.interactions.get_since(cursor=2, limit=2)
    assert len(entries) == 2
    assert entries[0].item_summary == "item 2"


# ── Triage cards ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_triage_card_lifecycle(stores):
    card = TriageCard(
        card_content={"summary": "test"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    await stores.triage.save_card(card)
    pending = await stores.triage.get_pending()
    assert len(pending) == 1

    await stores.triage.record_response(
        card.id, TriageResponse(card_id=card.id, choice=1)
    )
    pending = await stores.triage.get_pending()
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_triage_get_card(stores):
    card = TriageCard(
        card_content={"summary": "find me"},
        options=[TriageOption(label="OK", action="ok")],
    )
    await stores.triage.save_card(card)
    fetched = await stores.triage.get_card(card.id)
    assert fetched is not None
    assert fetched.card_content["summary"] == "find me"

    missing = await stores.triage.get_card("nonexistent")
    assert missing is None


@pytest.mark.asyncio
async def test_triage_next_unsent(stores):
    low = TriageCard(
        card_content={"summary": "low"},
        options=[TriageOption(label="OK", action="ok")],
        relevance_score=10,
    )
    high = TriageCard(
        card_content={"summary": "high"},
        options=[TriageOption(label="OK", action="ok")],
        relevance_score=90,
    )
    await stores.triage.save_card(low)
    await stores.triage.save_card(high)

    next_card = await stores.triage.get_next_unsent()
    assert next_card is not None
    assert next_card.relevance_score == 90


# ── Job tracking ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_tracking(stores):
    job = PipelineJob(trigger=JobTrigger.MANUAL)
    await stores.jobs.save_job(job)
    fetched = await stores.jobs.get_job(job.id)
    assert fetched is not None
    assert fetched.status == JobStatus.PENDING

    job.status = JobStatus.COMPLETED
    job.items_extracted = 5
    await stores.jobs.update_job(job)
    fetched = await stores.jobs.get_job(job.id)
    assert fetched is not None
    assert fetched.status == JobStatus.COMPLETED
    assert fetched.items_extracted == 5


# ── Plans ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_crud(stores):
    plan = Plan(title="Test Plan", content="Some content", sources=["diff", "email"])
    await stores.plans.save_plan(plan)

    plans = await stores.plans.get_plans(PlanFilters())
    assert len(plans) == 1
    assert plans[0].title == "Test Plan"
    assert plans[0].sources == ["diff", "email"]

    updated = await stores.plans.update_plan(plan.id, PlanUpdate(status="active"))
    assert updated.status == "active"

    filtered = await stores.plans.get_plans(PlanFilters(status="active"))
    assert len(filtered) == 1

    empty = await stores.plans.get_plans(PlanFilters(status="draft"))
    assert len(empty) == 0


# ── Enrichment traces ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrichment_trace(stores):
    trace = EnrichmentTrace(
        item_id="item-1",
        depth="shallow",
        calls_made=2,
        time_ms=150,
        context_retrieved={"key": "value"},
    )
    await stores.enrichment.log_trace(trace)

    traces = await stores.enrichment.get_traces(TraceFilters(item_id="item-1"))
    assert len(traces) == 1
    assert traces[0].depth == "shallow"
    assert traces[0].context_retrieved == {"key": "value"}

    empty = await stores.enrichment.get_traces(TraceFilters(item_id="nonexistent"))
    assert len(empty) == 0


# ── Source configs ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_source_config_crud(stores):
    source = SourceConfig(
        adapter_type="diff",
        config={"user_phid": "PHID-USER-123"},
        schedule="*/30 * * * *",
    )
    await stores.sources.upsert_source(source)

    sources = await stores.sources.get_sources()
    assert len(sources) == 1
    assert sources[0].adapter_type == "diff"
    assert sources[0].config == {"user_phid": "PHID-USER-123"}

    fetched = await stores.sources.get_source(source.id)
    assert fetched is not None
    assert fetched.schedule == "*/30 * * * *"

    updated = await stores.sources.update_source(
        source.id, SourceConfigUpdate(enabled=False)
    )
    assert updated.enabled is False


# ── Config store ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_store(stores):
    assert await stores.config.get("missing_key") is None

    await stores.config.set("theme", "dark")
    assert await stores.config.get("theme") == "dark"

    await stores.config.set("lang", "en")
    all_config = await stores.config.get_all()
    assert all_config == {"theme": "dark", "lang": "en"}

    # Overwrite existing key
    await stores.config.set("theme", "light")
    assert await stores.config.get("theme") == "light"


# ── Ingestion queue ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingestion_queue_enqueue_dequeue(stores):
    entry = IngestionQueueEntry(
        raw_content="diff content",
        source_type="diff",
        source_id="D456",
        urgency_score=75,
        job_id="job-1",
    )
    await stores.ingestion_queue.enqueue(entry)

    depth = await stores.ingestion_queue.queue_depth()
    assert depth == 1

    dequeued = await stores.ingestion_queue.dequeue(limit=1)
    assert len(dequeued) == 1
    assert dequeued[0].id == entry.id
    assert dequeued[0].status == QueueEntryStatus.PROCESSING

    await stores.ingestion_queue.mark_completed(entry.id)

    depth = await stores.ingestion_queue.queue_depth()
    assert depth == 0


@pytest.mark.asyncio
async def test_ingestion_queue_dead_letter(stores):
    entry = IngestionQueueEntry(
        raw_content="bad content",
        source_type="email",
        source_id="E789",
        urgency_score=50,
        job_id="job-2",
        max_attempts=2,
    )
    await stores.ingestion_queue.enqueue(entry)

    # Dequeue and fail attempt 1
    dequeued = await stores.ingestion_queue.dequeue(limit=1)
    assert len(dequeued) == 1
    await stores.ingestion_queue.mark_failed(entry.id, "parse error")

    # Should still be in queue (retried), but not yet dead letter
    dead = await stores.ingestion_queue.get_dead_letters()
    assert len(dead) == 0

    # Dequeue again (need to clear next_retry_at for immediate dequeue in test)
    # mark_failed with attempt=1 set status back to queued with next_retry_at
    # For the second failure, manually dequeue by updating next_retry_at
    from workbench.storage.postgres.ingestion_queue import PgIngestionQueueStore

    pool = stores.ingestion_queue.pool
    await pool.execute(
        "UPDATE ingestion_queue SET next_retry_at = NOW() - INTERVAL '1 second' "
        "WHERE id = $1",
        entry.id,
    )
    dequeued = await stores.ingestion_queue.dequeue(limit=1)
    assert len(dequeued) == 1
    await stores.ingestion_queue.mark_failed(entry.id, "parse error again")

    # Now should be dead letter (attempt 2 >= max_attempts 2)
    dead = await stores.ingestion_queue.get_dead_letters()
    assert len(dead) == 1
    assert dead[0].error == "parse error again"

    # Retry dead letter
    await stores.ingestion_queue.retry_dead_letter(entry.id)
    dead = await stores.ingestion_queue.get_dead_letters()
    assert len(dead) == 0

    depth = await stores.ingestion_queue.queue_depth()
    assert depth == 1

    # Purge after re-dead-lettering
    dequeued = await stores.ingestion_queue.dequeue(limit=1)
    await stores.ingestion_queue.mark_failed(entry.id, "still broken")
    await pool.execute(
        "UPDATE ingestion_queue SET next_retry_at = NOW() - INTERVAL '1 second' "
        "WHERE id = $1",
        entry.id,
    )
    dequeued = await stores.ingestion_queue.dequeue(limit=1)
    await stores.ingestion_queue.mark_failed(entry.id, "still broken")
    # now attempt is 2 again with max_attempts reset to 3 after retry
    # Actually after retry, attempt=0, max_attempts stays 2
    # attempt 0->1 (fail, queued), 1->2 (fail, dead_letter)
    dead = await stores.ingestion_queue.get_dead_letters()
    assert len(dead) == 1
    await stores.ingestion_queue.purge_dead_letter(entry.id)
    dead = await stores.ingestion_queue.get_dead_letters()
    assert len(dead) == 0


@pytest.mark.asyncio
async def test_ingestion_queue_priority_ordering(stores):
    low = IngestionQueueEntry(
        raw_content="low",
        source_type="diff",
        urgency_score=10,
        job_id="job-3",
    )
    mid = IngestionQueueEntry(
        raw_content="mid",
        source_type="diff",
        urgency_score=50,
        job_id="job-3",
    )
    high = IngestionQueueEntry(
        raw_content="high",
        source_type="diff",
        urgency_score=90,
        job_id="job-3",
    )
    await stores.ingestion_queue.enqueue(low)
    await stores.ingestion_queue.enqueue(mid)
    await stores.ingestion_queue.enqueue(high)

    dequeued = await stores.ingestion_queue.dequeue(limit=3)
    assert len(dequeued) == 3
    scores = [e.urgency_score for e in dequeued]
    assert scores == [90, 50, 10], f"Expected descending urgency order, got {scores}"


@pytest.mark.asyncio
async def test_ingestion_queue_recover_stuck(stores):
    entry = IngestionQueueEntry(
        raw_content="stuck",
        source_type="diff",
        urgency_score=50,
        job_id="job-4",
    )
    await stores.ingestion_queue.enqueue(entry)
    await stores.ingestion_queue.dequeue(limit=1)  # sets to processing

    recovered = await stores.ingestion_queue.recover_stuck()
    assert recovered == 1

    depth = await stores.ingestion_queue.queue_depth()
    assert depth == 1
