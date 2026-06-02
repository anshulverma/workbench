from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query

from memory import __version__
from memory.config import MemoryConfig, load_config
from memory.graphiti_layer import GraphitiMemoryLayer
from memory.llm import create_llm_client
from memory.embedder import create_embedder, create_cross_encoder
from memory.models import (
    FactsListResponse,
    HealthResponse,
    PreferenceQueryResponse,
    TriageRecordRequest,
)
from memory.logging import setup_logging
from memory.queue import PendingIngestionStore

setup_logging()
logger = logging.getLogger(__name__)


def get_config() -> MemoryConfig:
    config_path = os.environ.get("MEMORY_CONFIG", "memory-config.yml")
    override_path = os.environ.get("MEMORY_CONFIG_OVERRIDE")
    return load_config(config_path, override_path)


async def _run_ingestion_worker(
    store: PendingIngestionStore, layer: GraphitiMemoryLayer, concurrency: int = 1
):
    semaphore = asyncio.Semaphore(concurrency)
    recovered = await store.recover_stuck()
    if recovered:
        logger.info("Recovered %d stuck ingestion entries", recovered)

    while True:
        try:
            entries = await store.dequeue(limit=concurrency)
            if not entries:
                await asyncio.sleep(2)
                continue

            async def process(entry):
                async with semaphore:
                    try:
                        payload = entry["payload"]
                        await layer.record_triage(payload["card"], payload["response"])
                        await store.mark_completed(entry["id"])
                        logger.info("Fact ingestion completed for entry %s", entry["id"])
                    except Exception as e:
                        logger.error("Fact ingestion failed for entry %s: %s", entry["id"], e)
                        await store.mark_failed(entry["id"], str(e))

            await asyncio.gather(*(process(e) for e in entries))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Ingestion worker error: %s", e)
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    app.state.config = config

    log_cfg = config.logging
    setup_logging(
        level=getattr(logging, log_cfg.level.upper(), logging.INFO),
        timezone=log_cfg.timezone,
    )

    store = PendingIngestionStore(config.storage.postgres_dsn, config.queue.max_attempts)
    await store.initialize()
    app.state.store = store

    llm_client = create_llm_client(config.llm)
    embedder = create_embedder(config.embedder)
    cross_encoder = create_cross_encoder(config.embedder)

    from graphiti_core import Graphiti
    graphiti = Graphiti(
        uri=config.neo4j.uri,
        user=config.neo4j.user,
        password=config.neo4j.password,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=cross_encoder,
    )
    try:
        await graphiti.build_indices_and_constraints()
    except Exception as e:
        logger.warning("Failed to build Graphiti indices: %s", e)

    app.state.graphiti = graphiti
    app.state.layer = GraphitiMemoryLayer(graphiti=graphiti)

    worker_task = asyncio.create_task(
        _run_ingestion_worker(store, app.state.layer, config.queue.worker_concurrency)
    )

    logger.info("Memory service %s ready on port %d", __version__, config.server.port)

    yield

    logger.info("Shutting down...")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await graphiti.close()
    await store.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Memory Service", version=__version__, lifespan=lifespan)

    @app.post("/record/triage", status_code=202)
    async def record_triage(request: TriageRecordRequest):
        store: PendingIngestionStore = app.state.store
        entry_id = await store.enqueue(request)
        return {"status": "queued", "entry_id": entry_id}

    @app.get("/query/preferences", response_model=PreferenceQueryResponse)
    async def query_preferences(context: str = Query(...)):
        layer: GraphitiMemoryLayer = app.state.layer
        facts = await layer.query_preferences(context)
        return PreferenceQueryResponse(facts=facts)

    @app.get("/health", response_model=HealthResponse)
    async def health():
        neo4j_status = "unknown"
        pg_status = "unknown"
        graphiti_status = "unknown"

        try:
            await app.state.graphiti.driver.health_check()
            neo4j_status = "connected"
        except Exception:
            neo4j_status = "disconnected"

        try:
            await app.state.store.pool.fetchval("SELECT 1")
            pg_status = "connected"
        except Exception:
            pg_status = "disconnected"

        graphiti_status = "initialized" if app.state.graphiti else "not initialized"

        status = "ok" if neo4j_status == "connected" and pg_status == "connected" else "degraded"
        return HealthResponse(
            status=status, neo4j=neo4j_status, postgres=pg_status, graphiti=graphiti_status
        )

    @app.get("/facts", response_model=FactsListResponse)
    async def list_facts():
        layer: GraphitiMemoryLayer = app.state.layer
        facts = await layer.query_preferences("")
        return FactsListResponse(facts=facts, total=len(facts))

    @app.post("/record/entity", status_code=501)
    async def record_entity():
        return {"error": "Not implemented — Phase 1c"}

    @app.post("/record/decision", status_code=501)
    async def record_decision():
        return {"error": "Not implemented — Phase 1c"}

    @app.get("/query/entity", status_code=501)
    async def query_entity():
        return {"error": "Not implemented — Phase 1c"}

    @app.get("/query/relationships", status_code=501)
    async def query_relationships():
        return {"error": "Not implemented — Phase 1c"}

    return app


app = create_app()
