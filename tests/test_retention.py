# tests/test_retention.py

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from workbench.config import RetentionConfig


@pytest.mark.asyncio
async def test_retention_deletes_old_archived_items():
    from workbench.pipeline.scheduler import run_retention_cleanup

    stores = MagicMock()
    stores.items.delete_older_than = AsyncMock(return_value=5)
    stores.triage.delete_older_than = AsyncMock(return_value=3)
    stores.enrichment.delete_older_than = AsyncMock(return_value=2)
    stores.ingestion_queue.delete_dead_letters_older_than = AsyncMock(return_value=1)
    stores.ingestion_runs.delete_older_than = AsyncMock(return_value=0)

    config = RetentionConfig(archived_items_days=90)
    result = await run_retention_cleanup(stores, config)

    stores.items.delete_older_than.assert_called()
    assert result["archived_items"] == 5


@pytest.mark.asyncio
async def test_retention_skips_interaction_log():
    from workbench.pipeline.scheduler import run_retention_cleanup

    stores = MagicMock()
    stores.items.delete_older_than = AsyncMock(return_value=0)
    stores.triage.delete_older_than = AsyncMock(return_value=0)
    stores.enrichment.delete_older_than = AsyncMock(return_value=0)
    stores.ingestion_queue.delete_dead_letters_older_than = AsyncMock(return_value=0)
    stores.ingestion_runs.delete_older_than = AsyncMock(return_value=0)

    config = RetentionConfig()
    await run_retention_cleanup(stores, config)

    assert (
        not hasattr(stores.interactions, "delete_older_than")
        or not stores.interactions.delete_older_than.called
    )


@pytest.mark.asyncio
async def test_retention_returns_all_counts():
    from workbench.pipeline.scheduler import run_retention_cleanup

    stores = MagicMock()
    stores.items.delete_older_than = AsyncMock(side_effect=[10, 7])
    stores.triage.delete_older_than = AsyncMock(side_effect=[4, 6])
    stores.enrichment.delete_older_than = AsyncMock(return_value=3)
    stores.ingestion_queue.delete_dead_letters_older_than = AsyncMock(return_value=2)
    stores.ingestion_runs.delete_older_than = AsyncMock(return_value=0)

    config = RetentionConfig()
    result = await run_retention_cleanup(stores, config)

    assert result["archived_items"] == 10
    assert result["done_items"] == 7
    assert result["expired_cards"] == 4
    assert result["responded_cards"] == 6
    assert result["enrichment_traces"] == 3
    assert result["dead_letters"] == 2
    assert result["ingestion_runs"] == 0


@pytest.mark.asyncio
async def test_retention_config_defaults():
    config = RetentionConfig()
    assert config.archived_items_days == 90
    assert config.done_items_days == 90
    assert config.expired_cards_days == 30
    assert config.responded_cards_days == 90
    assert config.enrichment_traces_days == 30
    assert config.dead_letters_days == 30
    assert config.ingestion_runs_days == 30


@pytest.mark.asyncio
async def test_retention_config_custom_values():
    config = RetentionConfig(
        archived_items_days=180,
        done_items_days=60,
        expired_cards_days=14,
    )
    assert config.archived_items_days == 180
    assert config.done_items_days == 60
    assert config.expired_cards_days == 14


@pytest.mark.asyncio
async def test_retention_passes_correct_days_to_stores():
    from workbench.pipeline.scheduler import run_retention_cleanup

    stores = MagicMock()
    stores.items.delete_older_than = AsyncMock(return_value=0)
    stores.triage.delete_older_than = AsyncMock(return_value=0)
    stores.enrichment.delete_older_than = AsyncMock(return_value=0)
    stores.ingestion_queue.delete_dead_letters_older_than = AsyncMock(return_value=0)
    stores.ingestion_runs.delete_older_than = AsyncMock(return_value=0)

    config = RetentionConfig(
        archived_items_days=120,
        done_items_days=60,
        expired_cards_days=15,
        responded_cards_days=45,
        enrichment_traces_days=10,
        dead_letters_days=7,
    )
    await run_retention_cleanup(stores, config)

    stores.items.delete_older_than.assert_any_call("archived", 120)
    stores.items.delete_older_than.assert_any_call("done", 60)
    stores.triage.delete_older_than.assert_any_call("expired", 15)
    stores.triage.delete_older_than.assert_any_call("responded", 45)
    stores.enrichment.delete_older_than.assert_called_once_with(10)
    stores.ingestion_queue.delete_dead_letters_older_than.assert_called_once_with(7)
    stores.ingestion_runs.delete_older_than.assert_called_once_with(30)
