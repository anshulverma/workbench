from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from workbench import __version__
from workbench.auth import BearerTokenMiddleware
from workbench.config import AppConfig, load_config
from workbench.instrumentation import InstrumentedLLMProvider
from workbench.logging import setup_logging
from workbench.memory.noop import NoopMemoryLayer
from workbench.privacy import SanitizingProcessor
from workbench.metrics import create_metrics
from workbench.middleware import CorrelationIdMiddleware
from workbench.registry import (
    close_provider,
    create_provider,
    create_providers_from_list,
    create_composite_enricher,
)
from workbench.storage.factory import create_stores

setup_logging()
logger = structlog.get_logger(__name__)


def get_config() -> AppConfig:
    config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")
    override_path = os.environ.get("WORKBENCH_CONFIG_OVERRIDE")
    return load_config(config_path, override_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    app.state.config = config

    log_cfg = config.logging
    log_dir = log_cfg.log_dir or os.environ.get("WORKBENCH_LOG_DIR", "logs")
    sanitizer = SanitizingProcessor(config.privacy)
    setup_logging(
        log_format=log_cfg.format,
        log_dir=log_dir,
        level=getattr(logging, log_cfg.level.upper(), logging.INFO),
        max_bytes=log_cfg.max_bytes,
        max_age_days=log_cfg.max_age_days,
        timezone=log_cfg.timezone,
        extra_processors=[sanitizer],
    )
    logger.info(
        "Config loaded (version=%s, port=%d)", config.version, config.server.port
    )

    app.state.metrics = create_metrics()

    app.state.stores = await create_stores(config)
    logger.info("Storage connected")

    # Initialize shared connections
    connections = {}
    for name, conn_cfg in config.connections.items():
        conn = create_provider(conn_cfg)
        await conn.initialize()
        connections[name] = conn
        logger.info("Connection '%s' initialized", name)
    app.state.connections = connections

    app.state.llm = InstrumentedLLMProvider(
        create_provider(config.llm), app.state.metrics
    )

    if config.messenger:
        app.state.messenger = create_provider(config.messenger)
    else:
        app.state.messenger = None

    if config.enrichment.providers:
        app.state.enricher = create_composite_enricher(
            config.enrichment, connections=connections
        )
    else:
        from workbench.providers.enrichment.stub import StubEnricher

        app.state.enricher = StubEnricher()

    if config.memory:
        app.state.memory = create_provider(config.memory)
    else:
        app.state.memory = NoopMemoryLayer()

    if config.queue.scorer:
        app.state.queue_scorer = create_provider(config.queue.scorer)
    else:
        app.state.queue_scorer = None

    app.state.sources = create_providers_from_list(
        config.sources, connections=connections, metrics=app.state.metrics
    )

    # Targeted Hot-Reload plumbing: a single lock serializes source/messenger
    # config write-back + swap; config_path is the base YAML we edit.
    app.state.reload_lock = asyncio.Lock()
    app.state.config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")

    # Sync YAML sources (config.yml is the source of truth) into source_configs
    # so get_sources() reflects the live set. Stable ids are written back to YAML.
    from workbench.config_writer import write_source as _yaml_write_source
    from workbench.models import SourceConfig as _SourceConfig
    from workbench.registry import source_id_for as _source_id_for

    for raw in config.sources:
        sid = raw.get("id")
        if not sid:
            sid = _source_id_for(raw)
            node = dict(raw)
            node["id"] = sid
            try:
                _yaml_write_source(app.state.config_path, node)
            except Exception:
                logger.warning("Could not write back source id to YAML", source_id=sid)
        adapter_type = raw.get("adapter_type")
        if not adapter_type:
            adapter_type = raw.get("class", "unknown").rsplit(".", 1)[-1]
        sc = _SourceConfig(
            id=sid,
            adapter_type=adapter_type,
            config=raw.get("config", {}),
            schedule=raw.get("schedule", "*/15 * * * *"),
            enabled=raw.get("enabled", True),
        )
        await app.state.stores.sources.upsert_source(sc)

    from workbench.pipeline.engine import PipelineEngine

    app.state.pipeline = PipelineEngine(
        app.state.stores,
        app.state.memory,
        app.state.llm,
        app.state.enricher,
        queue_scorer=app.state.queue_scorer,
    )

    # Ingestion queue worker
    from workbench.pipeline.worker import IngestionQueueWorker

    worker = IngestionQueueWorker(
        app.state.stores,
        app.state.pipeline,
        concurrency=config.queue.worker_concurrency,
    )
    worker.start()
    app.state.worker = worker

    # Build per-source SourceConfig rows (YAML is the source of truth) with
    # DETERMINISTIC ids, and a stable source_id -> live adapter mapping. The
    # scheduler registers one CronTrigger Source Job per enabled source.
    from workbench.models import SourceConfig
    from workbench.registry import source_id_for

    db_sources: list[SourceConfig] = []
    source_by_id: dict[str, object] = {}
    for section, adapter in zip(config.sources, app.state.sources):
        sid = source_id_for(section)
        inner = getattr(adapter, "_inner", adapter)
        try:
            adapter_type = inner.adapter_type()
        except Exception:
            adapter_type = section.get("class", "unknown").rsplit(".", 1)[-1]
        sc = SourceConfig(
            id=sid,
            adapter_type=adapter_type,
            config=section.get("config", {}),
            schedule=section.get("schedule", "*/15 * * * *"),
            enabled=section.get("enabled", True),
        )
        # Attach the stable id to the live adapter for downstream mapping.
        try:
            adapter._source_id = sid  # type: ignore[attr-defined]
        except Exception:
            pass
        db_sources.append(sc)
        source_by_id[sid] = adapter

    # Scheduler
    from workbench.pipeline.scheduler import (
        WorkbenchScheduler,
        build_change_detectors,
    )

    app.state.scheduler = WorkbenchScheduler(
        app.state.stores,
        app.state.memory,
        app.state.pipeline,
        app.state.messenger,
        config,
        sources=app.state.sources,
        llm=app.state.llm,
    )
    app.state.scheduler._db_sources = db_sources
    app.state.scheduler._source_by_id = source_by_id
    # Change-monitoring: register per-source-type ChangeDetectors from config.
    app.state.scheduler._change_detectors = build_change_detectors(config.sources)
    app.state.scheduler.start()
    logger.info("Workbench %s ready on port %d", __version__, config.server.port)

    yield

    logger.info("Shutting down...")

    # Stop background work FIRST, before tearing down providers or the DB pool,
    # so the scheduler's interval jobs and the queue worker stop issuing queries
    # against a connection pool that is about to close. worker.stop() is awaited
    # so the loop has fully unwound before we proceed.
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown()
    if hasattr(app.state, "worker"):
        await app.state.worker.stop()

    for provider in [
        app.state.llm,
        app.state.messenger,
        app.state.enricher,
        app.state.memory,
        app.state.queue_scorer,
    ]:
        if provider:
            await close_provider(provider)
    for source in app.state.sources:
        await close_provider(source)

    for conn in app.state.connections.values():
        await close_provider(conn)

    # Close the DB pool last -- everything that uses it has now stopped.
    if hasattr(app.state, "stores"):
        await app.state.stores.close()

    logger.info("Shutdown complete")

    if hasattr(app.state.stores, "close"):
        await app.state.stores.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Workbench", version=__version__, lifespan=lifespan)
    app.add_middleware(BearerTokenMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    from workbench.api import (
        actions,
        activity,
        auth_token,
        config as config_api,
        connections,
        debug,
        filter_rules,
        health,
        identity,
        items,
        jobs,
        memory,
        messenger,
        process,
        queue,
        sources,
        stats,
        triage,
    )

    for r in [
        health.router,
        items.router,
        triage.router,
        process.router,
        filter_rules.router,
        sources.router,
        config_api.router,
        memory.router,
        identity.router,
        jobs.router,
        queue.router,
        actions.router,
        auth_token.router,
        debug.router,
        stats.router,
        activity.router,
        messenger.router,
        connections.router,
    ]:
        app.include_router(r)

    # Prometheus metrics endpoint (unauthenticated, excluded from schema)
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from starlette.responses import Response

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    ui_dir = os.path.join(os.path.dirname(__file__), "../../ui/dist")
    if os.path.exists(ui_dir):
        from starlette.staticfiles import StaticFiles

        app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")

    return app


app = create_app()


def cli_main():
    import uvicorn

    config = get_config()
    uvicorn.run(
        "workbench.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.debug,
    )
