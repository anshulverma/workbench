import asyncio
import tempfile
import os
import pytest
from server.storage.sqlite import create_sqlite_stores
from server.models import (
    Item, ItemCategory, ItemOrigin, Priority, ItemStatus, ItemFilters, ItemUpdate,
    FilterRule, InteractionEntry, TriageCard, TriageOption, TriageResponse,
    PipelineJob, JobTrigger, JobStatus,
    Plan, PlanFilters, PlanUpdate,
    EnrichmentTrace, TraceFilters,
    SourceConfig, SourceConfigUpdate,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def stores():
    loop = asyncio.new_event_loop()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        s = loop.run_until_complete(create_sqlite_stores(db_path))
        yield s
    finally:
        loop.close()
        os.unlink(db_path)


def test_item_crud(stores):
    loop = asyncio.new_event_loop()
    try:
        item = Item(source_type="diff", source_id="D123", summary="test", category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL, priority=Priority.P1)
        saved = loop.run_until_complete(stores.items.save_item(item))
        assert saved.id == item.id

        fetched = loop.run_until_complete(stores.items.get_item(item.id))
        assert fetched.summary == "test"

        updated = loop.run_until_complete(stores.items.update_item(item.id, ItemUpdate(priority=Priority.P0)))
        assert updated.priority == Priority.P0

        loop.run_until_complete(stores.items.archive_item(item.id))
        archived = loop.run_until_complete(stores.items.get_item(item.id))
        assert archived.status == ItemStatus.ARCHIVED
    finally:
        loop.close()


def test_item_filters(stores):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(stores.items.save_item(Item(source_type="diff", source_id="D1", summary="a", category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL, priority=Priority.P0)))
        loop.run_until_complete(stores.items.save_item(Item(source_type="email", source_id="E1", summary="b", category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.MANUAL, priority=Priority.P3)))
        results = loop.run_until_complete(stores.items.get_items(ItemFilters(priority=Priority.P0)))
        assert len(results) == 1
        assert results[0].source_id == "D1"
    finally:
        loop.close()


def test_filter_rules(stores):
    loop = asyncio.new_event_loop()
    try:
        rule = FilterRule(pattern="CI bot comments", action="drop")
        loop.run_until_complete(stores.filter_rules.add_rule(rule))
        rules = loop.run_until_complete(stores.filter_rules.get_rules())
        assert len(rules) == 1
        assert rules[0].pattern == "CI bot comments"
    finally:
        loop.close()


def test_filter_rules_by_source(stores):
    loop = asyncio.new_event_loop()
    try:
        rule1 = FilterRule(source_type="diff", pattern="CI bot", action="drop")
        rule2 = FilterRule(source_type="email", pattern="newsletter", action="drop")
        loop.run_until_complete(stores.filter_rules.add_rule(rule1))
        loop.run_until_complete(stores.filter_rules.add_rule(rule2))
        diff_rules = loop.run_until_complete(stores.filter_rules.get_source_rules("diff"))
        assert len(diff_rules) == 1
        assert diff_rules[0].pattern == "CI bot"
    finally:
        loop.close()


def test_processed_dedup(stores):
    loop = asyncio.new_event_loop()
    try:
        assert not loop.run_until_complete(stores.processed.is_processed("diff", "D123_100"))
        loop.run_until_complete(stores.processed.mark_processed("diff", "D123_100"))
        assert loop.run_until_complete(stores.processed.is_processed("diff", "D123_100"))
    finally:
        loop.close()


def test_interaction_log(stores):
    loop = asyncio.new_event_loop()
    try:
        entry = InteractionEntry(source_type="diff", item_summary="test", option_chosen="1")
        loop.run_until_complete(stores.interactions.append(entry))
        assert loop.run_until_complete(stores.interactions.count()) == 1
        entries = loop.run_until_complete(stores.interactions.get_all())
        assert entries[0].option_chosen == "1"
    finally:
        loop.close()


def test_interaction_get_since(stores):
    loop = asyncio.new_event_loop()
    try:
        for i in range(5):
            entry = InteractionEntry(source_type="diff", item_summary=f"item {i}", option_chosen=str(i))
            loop.run_until_complete(stores.interactions.append(entry))
        entries = loop.run_until_complete(stores.interactions.get_since(cursor=2, limit=2))
        assert len(entries) == 2
        assert entries[0].item_summary == "item 2"
    finally:
        loop.close()


def test_triage_card_lifecycle(stores):
    loop = asyncio.new_event_loop()
    try:
        card = TriageCard(card_content={"summary": "test"}, options=[TriageOption(label="Skip", action="skip")])
        loop.run_until_complete(stores.triage.save_card(card))
        pending = loop.run_until_complete(stores.triage.get_pending())
        assert len(pending) == 1
        loop.run_until_complete(stores.triage.record_response(card.id, TriageResponse(card_id=card.id, choice=1)))
        pending = loop.run_until_complete(stores.triage.get_pending())
        assert len(pending) == 0
    finally:
        loop.close()


def test_triage_get_card(stores):
    loop = asyncio.new_event_loop()
    try:
        card = TriageCard(card_content={"summary": "find me"}, options=[TriageOption(label="OK", action="ok")])
        loop.run_until_complete(stores.triage.save_card(card))
        fetched = loop.run_until_complete(stores.triage.get_card(card.id))
        assert fetched is not None
        assert fetched.card_content["summary"] == "find me"
        missing = loop.run_until_complete(stores.triage.get_card("nonexistent"))
        assert missing is None
    finally:
        loop.close()


def test_job_tracking(stores):
    loop = asyncio.new_event_loop()
    try:
        job = PipelineJob(trigger=JobTrigger.MANUAL)
        loop.run_until_complete(stores.jobs.save_job(job))
        fetched = loop.run_until_complete(stores.jobs.get_job(job.id))
        assert fetched.status == JobStatus.PENDING
        job.status = JobStatus.COMPLETED
        job.items_extracted = 5
        loop.run_until_complete(stores.jobs.update_job(job))
        fetched = loop.run_until_complete(stores.jobs.get_job(job.id))
        assert fetched.status == JobStatus.COMPLETED
        assert fetched.items_extracted == 5
    finally:
        loop.close()


def test_plan_crud(stores):
    loop = asyncio.new_event_loop()
    try:
        plan = Plan(title="Test Plan", content="Some content", sources=["diff", "email"])
        loop.run_until_complete(stores.plans.save_plan(plan))

        plans = loop.run_until_complete(stores.plans.get_plans(PlanFilters()))
        assert len(plans) == 1
        assert plans[0].title == "Test Plan"
        assert plans[0].sources == ["diff", "email"]

        updated = loop.run_until_complete(stores.plans.update_plan(plan.id, PlanUpdate(status="active")))
        assert updated.status == "active"

        filtered = loop.run_until_complete(stores.plans.get_plans(PlanFilters(status="active")))
        assert len(filtered) == 1

        empty = loop.run_until_complete(stores.plans.get_plans(PlanFilters(status="draft")))
        assert len(empty) == 0
    finally:
        loop.close()


def test_enrichment_trace(stores):
    loop = asyncio.new_event_loop()
    try:
        trace = EnrichmentTrace(item_id="item-1", depth="shallow", calls_made=2, time_ms=150, context_retrieved={"key": "value"})
        loop.run_until_complete(stores.enrichment.log_trace(trace))

        traces = loop.run_until_complete(stores.enrichment.get_traces(TraceFilters(item_id="item-1")))
        assert len(traces) == 1
        assert traces[0].depth == "shallow"
        assert traces[0].context_retrieved == {"key": "value"}

        empty = loop.run_until_complete(stores.enrichment.get_traces(TraceFilters(item_id="nonexistent")))
        assert len(empty) == 0
    finally:
        loop.close()


def test_source_config_crud(stores):
    loop = asyncio.new_event_loop()
    try:
        source = SourceConfig(adapter_type="diff", config={"user_phid": "PHID-USER-123"}, schedule="*/30 * * * *")
        loop.run_until_complete(stores.sources.save_source(source))

        sources = loop.run_until_complete(stores.sources.get_sources())
        assert len(sources) == 1
        assert sources[0].adapter_type == "diff"
        assert sources[0].config == {"user_phid": "PHID-USER-123"}

        updated = loop.run_until_complete(stores.sources.update_source(source.id, SourceConfigUpdate(enabled=False)))
        assert updated.enabled is False

        loop.run_until_complete(stores.sources.delete_source(source.id))
        sources = loop.run_until_complete(stores.sources.get_sources())
        assert len(sources) == 0
    finally:
        loop.close()


def test_config_store(stores):
    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(stores.config.get("missing_key")) is None

        loop.run_until_complete(stores.config.set("theme", "dark"))
        assert loop.run_until_complete(stores.config.get("theme")) == "dark"

        loop.run_until_complete(stores.config.set("lang", "en"))
        all_config = loop.run_until_complete(stores.config.get_all())
        assert all_config == {"theme": "dark", "lang": "en"}

        # Overwrite existing key
        loop.run_until_complete(stores.config.set("theme", "light"))
        assert loop.run_until_complete(stores.config.get("theme")) == "light"
    finally:
        loop.close()
