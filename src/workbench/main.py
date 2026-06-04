from __future__ import annotations

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
from workbench.metrics import create_metrics
from workbench.middleware import CorrelationIdMiddleware
from workbench.registry import close_provider, create_provider, create_providers_from_list, create_composite_enricher
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
    setup_logging(
        log_format=log_cfg.format,
        log_dir=log_dir,
        level=getattr(logging, log_cfg.level.upper(), logging.INFO),
        max_bytes=log_cfg.max_bytes,
        max_age_days=log_cfg.max_age_days,
        timezone=log_cfg.timezone,
    )
    logger.info("Config loaded (version=%s, port=%d)", config.version, config.server.port)

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

    app.state.llm = InstrumentedLLMProvider(create_provider(config.llm), app.state.metrics)

    if config.messenger:
        app.state.messenger = create_provider(config.messenger)
    else:
        app.state.messenger = None

    if config.enrichment.providers:
        app.state.enricher = create_composite_enricher(config.enrichment, connections=connections)
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

    app.state.sources = create_providers_from_list(config.sources, connections=connections, metrics=app.state.metrics)

    from workbench.pipeline.engine import PipelineEngine
    app.state.pipeline = PipelineEngine(
        app.state.stores, app.state.memory, app.state.llm, app.state.enricher,
        queue_scorer=app.state.queue_scorer,
    )

    # Ingestion queue worker
    from workbench.pipeline.worker import IngestionQueueWorker
    worker = IngestionQueueWorker(
        app.state.stores, app.state.pipeline,
        concurrency=config.queue.worker_concurrency,
    )
    worker.start()
    app.state.worker = worker

    # Scheduler
    from workbench.pipeline.scheduler import WorkbenchScheduler
    app.state.scheduler = WorkbenchScheduler(
        app.state.stores, app.state.memory, app.state.pipeline,
        app.state.messenger, config, sources=app.state.sources,
    )
    app.state.scheduler.start()
    logger.info("Workbench %s ready on port %d", __version__, config.server.port)

    yield

    logger.info("Shutting down...")

    # Cleanup
    if hasattr(app.state, 'worker'):
        app.state.worker.stop()
    app.state.scheduler.scheduler.shutdown(wait=False)

    for provider in [app.state.llm, app.state.messenger, app.state.enricher,
                     app.state.memory, app.state.queue_scorer]:
        if provider:
            await close_provider(provider)
    for source in app.state.sources:
        await close_provider(source)

    for conn in app.state.connections.values():
        await close_provider(conn)

    if hasattr(app.state.stores, 'close'):
        await app.state.stores.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Workbench", version=__version__, lifespan=lifespan)
    app.add_middleware(BearerTokenMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    from workbench.api import (
        actions, auth_token,
        config as config_api, filter_rules, health, items, jobs,
        memory, process, queue, sources, triage,
    )
    for r in [
        health.router, items.router, triage.router, process.router,
        filter_rules.router, sources.router, config_api.router,
        memory.router, jobs.router, queue.router,
        actions.router, auth_token.router,
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
    uvicorn.run("workbench.main:app", host="0.0.0.0", port=config.server.port,
                reload=config.server.debug)
