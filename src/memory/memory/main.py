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
from memory.metrics import create_metrics
from memory.instrumentation import instrument_llm_client, MemoryUsageAggregator
from memory.embedder import create_embedder, create_cross_encoder
from memory.models import (
    DecisionRecordRequest,
    EntityRecordRequest,
    EntityResponse,
    FactsListResponse,
    FactUpdateRequest,
    HealthResponse,
    PreferenceQueryResponse,
    QueueDepthResponse,
    RelationshipsResponse,
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
    store: PendingIngestionStore,
    layer: GraphitiMemoryLayer,
    concurrency: int = 1,
    metrics=None,
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
                        entry_type = entry.get("type", "triage")
                        if entry_type == "decision":
                            await layer.record_decision(
                                payload["item_summary"],
                                payload["decision"],
                                payload["reason"],
                                payload.get("source_type", "unknown"),
                                store,
                            )
                        else:
                            await layer.record_triage(
                                payload["card"], payload["response"]
                            )
                        await store.mark_completed(entry["id"])
                        if metrics is not None:
                            metrics.episodes_ingested.labels(type=entry_type).inc()
                        logger.info(
                            "Ingestion completed for %s entry %s",
                            entry_type,
                            entry["id"],
                        )
                    except Exception as e:
                        logger.error(
                            "Ingestion failed for entry %s: %s", entry["id"], e
                        )
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
        log_dir=log_cfg.log_dir or os.environ.get("MEMORY_LOG_DIR", "/app/logs"),
        max_bytes=log_cfg.max_bytes,
        backup_count=log_cfg.backup_count,
    )

    store = PendingIngestionStore(
        config.storage.postgres_dsn, config.queue.max_attempts
    )
    await store.initialize()
    app.state.store = store

    llm_client = create_llm_client(config.llm)

    # Plugboard observability (ADR 0050): wrap the Graphiti LLM client in place
    # to count calls/latency/errors (tokens best-effort). Separate process =>
    # own registry. Gated on metrics.enabled.
    if config.metrics.enabled:
        app.state.metrics = create_metrics()
        app.state.usage_agg = MemoryUsageAggregator()
        llm_client = instrument_llm_client(
            llm_client,
            app.state.metrics,
            config.llm.model,
            aggregator=app.state.usage_agg,
        )
    else:
        app.state.metrics = None
        app.state.usage_agg = None

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
        _run_ingestion_worker(
            store,
            app.state.layer,
            config.queue.worker_concurrency,
            metrics=app.state.metrics,
        )
    )

    # Periodic plugboard usage summary (process=memory); skip empty intervals.
    summary_task = None
    if config.metrics.enabled and config.metrics.summary_log:
        _interval = config.metrics.summary_interval_seconds

        async def _summary_loop():
            while True:
                await asyncio.sleep(_interval)
                snapshot = app.state.usage_agg.drain()
                if not snapshot:
                    continue
                logger.info(
                    "llm_usage_summary process=memory interval_seconds=%d usage=%s",
                    _interval,
                    snapshot,
                )

        summary_task = asyncio.create_task(_summary_loop())

    logger.info("Memory service %s ready on port %d", __version__, config.server.port)

    yield

    logger.info("Shutting down...")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    if summary_task is not None:
        summary_task.cancel()
        try:
            await summary_task
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

        status = (
            "ok"
            if neo4j_status == "connected" and pg_status == "connected"
            else "degraded"
        )
        return HealthResponse(
            status=status,
            neo4j=neo4j_status,
            postgres=pg_status,
            graphiti=graphiti_status,
        )

    @app.get("/facts", response_model=FactsListResponse)
    async def list_facts():
        layer: GraphitiMemoryLayer = app.state.layer
        facts = await layer.query_preferences("")
        return FactsListResponse(facts=facts, total=len(facts))

    @app.delete("/facts/{fact_id}", status_code=204)
    async def delete_fact(fact_id: str):
        layer: GraphitiMemoryLayer = app.state.layer
        try:
            await layer.delete_fact(fact_id)
        except KeyError:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Fact not found")

    @app.patch("/facts/{fact_id}", status_code=200)
    async def update_fact(fact_id: str, request: FactUpdateRequest):
        layer: GraphitiMemoryLayer = app.state.layer
        try:
            await layer.update_fact(fact_id, request.content)
        except KeyError:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Fact not found")
        return {"status": "updated", "id": fact_id, "content": request.content}

    @app.post("/record/entity", status_code=200)
    async def record_entity(request: EntityRecordRequest):
        layer: GraphitiMemoryLayer = app.state.layer
        store: PendingIngestionStore = app.state.store
        graph_uuid = await layer.record_entity(
            request.entity_type, request.entity_id, request.facts, store
        )
        # record_entity is synchronous and bypasses the ingestion worker, so the
        # type=entity episode metric must be incremented here (ADR 0050).
        metrics = getattr(app.state, "metrics", None)
        if metrics is not None:
            metrics.episodes_ingested.labels(type="entity").inc()
        return {
            "status": "ok",
            "entity_type": request.entity_type,
            "entity_id": request.entity_id,
            "graph_uuid": graph_uuid,
        }

    @app.post("/record/decision", status_code=202)
    async def record_decision(request: DecisionRecordRequest):
        store: PendingIngestionStore = app.state.store
        entry_id = await store.enqueue(request, entry_type="decision")
        return {"status": "queued", "entry_id": entry_id}

    @app.get("/query/entity", response_model=EntityResponse)
    async def query_entity(entity_type: str = Query(...), entity_id: str = Query(...)):
        layer: GraphitiMemoryLayer = app.state.layer
        store: PendingIngestionStore = app.state.store
        entity = await layer.query_entity(entity_type, entity_id, store)
        if entity is None:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=404,
                content={"detail": "Entity not found"},
            )
        return EntityResponse(
            entity_type=entity["entity_type"],
            entity_id=entity["entity_id"],
            facts=entity["facts"],
        )

    @app.get("/query/relationships", response_model=RelationshipsResponse)
    async def query_relationships(
        entity_type: str = Query(...), entity_id: str = Query(...)
    ):
        layer: GraphitiMemoryLayer = app.state.layer
        store: PendingIngestionStore = app.state.store
        relationships = await layer.query_relationships(entity_type, entity_id, store)
        return RelationshipsResponse(relationships=relationships)

    @app.post("/admin/reset-graph")
    async def admin_reset_graph():
        if os.environ.get("MEMORY_ADMIN_ENABLED", "false") != "true":
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={"detail": "Admin endpoints are disabled"},
            )
        graphiti = app.state.graphiti
        store: PendingIngestionStore = app.state.store
        # Wipe Neo4j
        try:
            await graphiti.driver.execute_query("MATCH (n) DETACH DELETE n")
        except Exception as e:
            logger.error("Failed to wipe Neo4j: %s", e)
            raise
        # Clear all graph_uuids in PG
        await store.clear_all_graph_uuids()
        return {"status": "ok", "message": "Graph reset complete"}

    @app.get("/admin/queue-depth", response_model=QueueDepthResponse)
    async def admin_queue_depth():
        store: PendingIngestionStore = app.state.store
        depth = await store.queue_depth()
        dead_letters = await store.dead_letter_count()
        return QueueDepthResponse(depth=depth, dead_letters=dead_letters)

    @app.post("/admin/identity/merge")
    async def admin_merge_identities(
        entity_type: str = Query(...),
        winner_id: str = Query(...),
        loser_id: str = Query(...),
    ):
        if os.environ.get("MEMORY_ADMIN_ENABLED", "false") != "true":
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={"detail": "Admin endpoints are disabled"},
            )
        store: PendingIngestionStore = app.state.store
        merged = await store.late_discovery_merge(entity_type, winner_id, loser_id)
        if not merged:
            return {
                "status": "noop",
                "reason": "already same canonical or winner not found",
            }
        return {"status": "merged", "canonical": winner_id}

    @app.post("/admin/identity/split")
    async def admin_split_identity(
        entity_type: str = Query(...),
        source_id: str = Query(...),
    ):
        if os.environ.get("MEMORY_ADMIN_ENABLED", "false") != "true":
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={"detail": "Admin endpoints are disabled"},
            )
        store: PendingIngestionStore = app.state.store
        await store.admin_split(entity_type, source_id)
        return {"status": "split", "source_id": source_id}

    @app.get("/admin/identity/list")
    async def admin_list_identities(
        entity_type: str = Query(...),
        canonical_id: str = Query(...),
    ):
        if os.environ.get("MEMORY_ADMIN_ENABLED", "false") != "true":
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={"detail": "Admin endpoints are disabled"},
            )
        store: PendingIngestionStore = app.state.store
        aliases = await store.list_identities(entity_type, canonical_id)
        return {"canonical_id": canonical_id, "aliases": aliases, "total": len(aliases)}

    # Prometheus metrics endpoint (unauthenticated, like /health; ADR 0051).
    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
        from starlette.responses import Response

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
