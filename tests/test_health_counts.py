import pytest

from workbench.domain import IngestionQueueEntry, QueueEntryStatus


async def _enqueue(stores, status, n):
    for i in range(n):
        e = IngestionQueueEntry(
            raw_content=f"c{i}",
            source_type="github",
            job_id=1,
            status=QueueEntryStatus(status),
        )
        await stores.ingestion_queue.enqueue(e)


@pytest.mark.asyncio
async def test_count_dead_letters_uses_count(stores):
    await _enqueue(stores, "dead_letter", 3)
    await _enqueue(stores, "queued", 2)
    assert await stores.ingestion_queue.count_dead_letters() == 3
