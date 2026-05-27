# server/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from server.config import Settings
from server.auth import BearerTokenMiddleware
from server.storage.factory import create_stores
from server.memory.noop import NoopMemoryLayer
from server.providers.llm.claude import ClaudeProvider
from server.providers.enrichment.stub import StubEnricher
from server.pipeline.engine import PipelineEngine
from server.pipeline.scheduler import WorkbenchScheduler
from server.providers.messenger.google_chat import GoogleChatMessenger
from server.api import items, triage, process, filter_rules, sources, config, memory, jobs

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.stores = await create_stores(settings)
    app.state.memory = NoopMemoryLayer()
    app.state.llm = ClaudeProvider(
        settings.anthropic_api_key, settings.anthropic_base_url
    )
    app.state.enricher = StubEnricher()
    app.state.pipeline = PipelineEngine(
        app.state.stores, app.state.memory, app.state.llm, app.state.enricher
    )
    messenger = None
    if settings.gchat_space_id:
        messenger = GoogleChatMessenger(settings.gchat_space_id, settings.google_api_script)
    app.state.scheduler = WorkbenchScheduler(
        app.state.stores, app.state.memory, app.state.pipeline, messenger, settings
    )
    app.state.scheduler.start()
    yield


app = FastAPI(title="Workbench", version="0.1.0", lifespan=lifespan)
app.add_middleware(BearerTokenMiddleware, token=settings.api_token)


@app.get("/health")
async def health():
    return {"status": "ok"}


for r in [
    items.router,
    triage.router,
    process.router,
    filter_rules.router,
    sources.router,
    config.router,
    memory.router,
    jobs.router,
]:
    app.include_router(r)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.port)
