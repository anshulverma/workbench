"""Replay workbench interaction_log into the memory service to rebuild the knowledge graph."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

import asyncpg
import httpx

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
QUEUE_DEPTH_THRESHOLD = 20
QUEUE_POLL_INTERVAL = 2


async def get_interactions(dsn: str) -> list[dict]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT id, triage_card_full, choice_index, timestamp "
            "FROM interaction_log ORDER BY timestamp ASC"
        )
        return [
            {
                "id": r["id"],
                "triage_card_full": json.loads(r["triage_card_full"]) if isinstance(r["triage_card_full"], str) else r["triage_card_full"],
                "choice_index": r.get("choice_index"),
                "timestamp": r["timestamp"],
            }
            for r in rows
        ]
    finally:
        await conn.close()


async def reset_memory_graph(client: httpx.AsyncClient, base_url: str) -> None:
    resp = await client.post(f"{base_url}/admin/reset-graph")
    resp.raise_for_status()
    logger.info("Graph reset complete")


async def get_queue_depth(client: httpx.AsyncClient, base_url: str) -> int:
    resp = await client.get(f"{base_url}/admin/queue-depth")
    resp.raise_for_status()
    return resp.json().get("depth", 0)


async def replay_interactions(
    interactions: list[dict],
    client: httpx.AsyncClient,
    base_url: str,
) -> int:
    total = len(interactions)
    replayed = 0

    for i, entry in enumerate(interactions):
        choice_index = entry.get("choice_index")
        card = entry.get("triage_card_full", {})

        # Skip entries without choice_index or incomplete card
        if choice_index is None:
            logger.warning(
                "Skipping interaction %s: no choice_index (pre-Phase 1c row)",
                entry["id"],
            )
            continue
        if not card.get("id") or not card.get("options"):
            logger.warning(
                "Skipping interaction %s: incomplete card dict",
                entry["id"],
            )
            continue

        payload = {
            "card": card,
            "response": {"card_id": card["id"], "choice": choice_index},
        }
        resp = await client.post(f"{base_url}/record/triage", json=payload)
        resp.raise_for_status()
        replayed += 1

        # Poll queue depth between batches
        if replayed % BATCH_SIZE == 0:
            depth = await get_queue_depth(client, base_url)
            logger.info("Replayed %d/%d interactions, queue depth: %d", replayed, total, depth)
            while depth > QUEUE_DEPTH_THRESHOLD:
                await asyncio.sleep(QUEUE_POLL_INTERVAL)
                depth = await get_queue_depth(client, base_url)
                logger.info("Waiting for queue to drain, depth: %d", depth)

    logger.info("Replayed %d/%d interactions total", replayed, total)
    return replayed


async def main(workbench_dsn: str, memory_url: str, reset: bool = False) -> None:
    base_url = memory_url.rstrip("/")

    async with httpx.AsyncClient(timeout=30) as client:
        if reset:
            logger.info("Resetting memory graph...")
            await reset_memory_graph(client, base_url)

        logger.info("Reading interaction log from workbench PG...")
        interactions = await get_interactions(workbench_dsn)
        logger.info("Found %d interactions", len(interactions))

        if not interactions:
            logger.info("Nothing to replay")
            return

        replayed = await replay_interactions(interactions, client, base_url)
        logger.info("Rebuild complete: %d interactions replayed", replayed)


def cli():
    parser = argparse.ArgumentParser(description="Rebuild memory graph from workbench interaction log")
    parser.add_argument("--workbench-dsn", required=True, help="Workbench PostgreSQL DSN")
    parser.add_argument("--memory-url", required=True, help="Memory service base URL")
    parser.add_argument("--reset", action="store_true", help="Wipe graph before rebuild")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main(args.workbench_dsn, args.memory_url, args.reset))


if __name__ == "__main__":
    cli()
