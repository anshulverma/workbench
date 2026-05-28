from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from workbench import __version__
from workbench.auth import BearerTokenMiddleware
from workbench.config import AppConfig, load_config
from workbench.memory.noop import NoopMemoryLayer
from workbench.registry import close_provider, create_provider
from workbench.storage.factory import create_stores

logger = logging.getLogger(__name__)


def get_config() -> AppConfig:
    config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")
    override_path = os.environ.get("WORKBENCH_CONFIG_OVERRIDE")
    return load_config(config_path, override_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    app.state.config = config

    app.state.stores = await create_stores(config)

    app.state.llm = create_provider(config.llm)

    if config.messenger:
        app.state.messenger = create_provider(config.messenger)
    else:
        app.state.messenger = None

    if config.enrichment:
        app.state.enricher = create_provider(config.enrichment)
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

    app.state.sources = []
    for source_cfg in config.sources:
        app.state.sources.append(create_provider(source_cfg))

    from workbench.pipeline.engine import PipelineEngine
    app.state.pipeline = PipelineEngine(
        app.state.stores, app.state.memory, app.state.llm, app.state.enricher
    )

    # Scheduler
    from workbench.pipeline.scheduler import WorkbenchScheduler
    app.state.scheduler = WorkbenchScheduler(
        app.state.stores, app.state.memory, app.state.pipeline,
        app.state.messenger, config,
    )
    app.state.scheduler.start()

    yield

    # Cleanup
    app.state.scheduler.scheduler.shutdown(wait=False)

    for provider in [app.state.llm, app.state.messenger, app.state.enricher,
                     app.state.memory, app.state.queue_scorer]:
        if provider:
            await close_provider(provider)
    for source in app.state.sources:
        await close_provider(source)

    if hasattr(app.state.stores, 'close'):
        await app.state.stores.close()


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(title="Workbench", version=__version__, lifespan=lifespan)
    app.add_middleware(BearerTokenMiddleware, token=config.server.api_token)

    from workbench.api import (
        config as config_api, filter_rules, health, items, jobs,
        memory, process, sources, triage,
    )
    for r in [
        health.router, items.router, triage.router, process.router,
        filter_rules.router, sources.router, config_api.router,
        memory.router, jobs.router,
    ]:
        app.include_router(r)

    return app


app = create_app()


def cli_main():
    import uvicorn
    config = get_config()
    uvicorn.run("workbench.main:app", host="0.0.0.0", port=config.server.port,
                reload=config.server.debug)
