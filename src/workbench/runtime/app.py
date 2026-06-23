from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import FastAPI

from workbench import __version__
from workbench.domain.llm_calls import LlmCallRecord, LlmSubcall
from workbench.runtime.auth import BearerTokenMiddleware
from workbench.config import AppConfig, load_config
from workbench.telemetry.instrumentation import InstrumentedLLMProvider
from workbench.telemetry.logging import setup_logging
from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.telemetry.privacy import SanitizingProcessor
from workbench.telemetry.metrics import create_metrics
from workbench.telemetry.usage_aggregator import UsageAggregator
from workbench.runtime.middleware import CorrelationIdMiddleware
from workbench.providers.registry import (
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


def _to_llm_record(rec) -> LlmCallRecord | None:
    """Map a PlugboardCallRecord (transport view) to a persistable LlmCallRecord.

    Returns None for context-less calls (pipeline calls are always wrapped with
    an LLMCallContext; a missing context is defensive and means "don't persist").

    ``started_at`` is computed at sink time as ``now - latency``: the sink runs
    synchronously in the LLM call's task right after the call returns, so this
    closely approximates the real call-start. Do NOT defer this to the writer
    task (write-time would be wrong). See ADR 0057.
    """
    if rec.context is None:
        logger.debug("plugboard record has no context; skipping llm_calls persist")
        return None

    started_at = datetime.now(timezone.utc) - timedelta(seconds=rec.latency_s or 0.0)
    subcalls = [
        LlmSubcall(
            item=s["item"],
            prompt=s.get("prompt", ""),
            completion=s.get("completion", ""),
            structured=s.get("structured"),
            tokens_in=(s.get("tokens_in") or 0),
            tokens_out=s.get("tokens_out"),
        )
        for s in (rec.subcalls or [])
    ]
    # Single (non-batch) calls populate input_prompt/completion/structured on the
    # record rather than subcalls; synthesize one subcall so the popup renders a
    # body (without this, single calls show no Input/Completion at all).
    if not subcalls and (
        rec.input_prompt is not None
        or rec.completion is not None
        or rec.structured is not None
    ):
        item_label = (
            rec.context.item_paths[0] if rec.context and rec.context.item_paths else "—"
        )
        subcalls = [
            LlmSubcall(
                item=item_label,
                prompt=rec.input_prompt or "",
                completion=rec.completion or "",
                structured=rec.structured,
                tokens_in=rec.input_tokens or 0,
                tokens_out=(None if rec.error_type else rec.output_tokens),
            )
        ]
    return LlmCallRecord(
        started_at=started_at,
        origin=rec.context.origin,
        purpose=rec.context.purpose,
        stage=rec.context.stage,
        model=rec.model,
        temperature=rec.temperature,
        status="error" if rec.error_type else "ok",
        error_type=rec.error_type,
        batch=rec.item_count,
        items=(
            list(rec.context.item_paths)
            if rec.context and rec.context.item_paths
            else [s["item"] for s in (rec.subcalls or [])]
        ),
        tokens_in=rec.input_tokens,
        tokens_out=None if rec.error_type else rec.output_tokens,
        cache_read_tokens=rec.cache_read_tokens,
        cache_write_tokens=rec.cache_write_tokens,
        latency_ms=round((rec.latency_s or 0.0) * 1000),
        system_prompt=rec.system_prompt,
        subcalls=subcalls,
        tokens_estimated=rec.tokens_estimated,
        is_fallback=rec.is_fallback,
        correlation_id=(rec.context.correlation_id if rec.context else None),
        raw_request=rec.raw_request,
        raw_response=rec.raw_response,
    )


async def _drain_once(
    queue: asyncio.Queue, store, *, entity_links=None, max_batch: int = 50
) -> None:
    """Drain one batch from ``queue`` and persist via ``store.save_many``.

    Blocks on the first item, then opportunistically drains up to ``max_batch``
    more without blocking. None entries are filtered out. ``task_done`` is called
    for every item consumed (including Nones) so ``queue.join()`` stays accurate.
    A failed ``save_many`` drops the batch rather than crashing the loop.
    """
    first = await queue.get()
    batch = [first]
    try:
        for _ in range(max_batch):
            batch.append(queue.get_nowait())
    except asyncio.QueueEmpty:
        pass

    records = [r for r in batch if r is not None]
    try:
        if records:
            await store.save_many(records, entity_links=entity_links)
    except Exception:
        logger.exception("llm_calls writer failed; dropping batch")
    finally:
        for _ in batch:
            queue.task_done()


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

    # Always build the composite enricher. It honors both explicit per-source
    # `providers` and the `default` enricher. The config normalizer rewrites the
    # simple `enrichment: {class: X}` form into `{providers: [], default: {class:
    # X}}` (config/models.py::_normalize_enrichment); gating only on `providers`
    # (the previous behavior) silently dropped a configured default — e.g. the
    # Meta composite enricher — and fell back to the no-op StubEnricher, so diffs
    # were never deep-fetched and no triage card ever got curated hunks. With no
    # enrichment configured, `default` resolves to StubEnricher, so the composite
    # degrades to the same no-op behavior as before.
    app.state.enricher = create_composite_enricher(
        config.enrichment, connections=connections
    )

    if config.memory:
        app.state.memory = create_provider(config.memory)
    else:
        app.state.memory = NoopMemoryLayer()

    if config.queue.scorer:
        app.state.queue_scorer = create_provider(config.queue.scorer)
    else:
        app.state.queue_scorer = None

    # Wire the plugboard transport-view sink onto the underlying providers.
    # The main LLM is wrapped by InstrumentedLLMProvider, so target its _inner.
    # The sink is attached when metrics OR llm_tracking is enabled: metrics own
    # the Prometheus/aggregator branch (gated on metrics.enabled), llm_tracking
    # owns the async DB-enqueue branch. Providers never import
    # workbench.telemetry.metrics; the sink (a closure here) owns all of that
    # knowledge. The sink runs synchronously in the LLM call's task and must
    # never block or raise (ADR 0049/0057).
    app.state.summary_task = None
    app.state.llm_writer_task = None
    app.state.llm_write_q = None
    app.state.llm_dropped = 0

    stores = app.state.stores
    if config.llm_tracking.enabled and stores.llm_calls is not None:
        app.state.llm_write_q = asyncio.Queue(maxsize=1000)

    if config.metrics.enabled or config.llm_tracking.enabled:
        _m = app.state.metrics
        if config.metrics.enabled:
            app.state.usage_agg = UsageAggregator()

        def _plugboard_sink(rec):
            if config.metrics.enabled:
                app.state.usage_agg.record(rec)
                _m.plugboard_calls.labels(client=rec.client, model=rec.model).inc()
                _m.plugboard_call_seconds.labels(
                    client=rec.client, model=rec.model
                ).observe(rec.latency_s)
                if rec.error_type:
                    _m.plugboard_errors.labels(
                        client=rec.client, model=rec.model, error_type=rec.error_type
                    ).inc()
                else:
                    for direction, n in (
                        ("input", rec.input_tokens),
                        ("output", rec.output_tokens),
                        ("cache_read", rec.cache_read_tokens),
                        ("cache_write", rec.cache_write_tokens),
                    ):
                        if n:
                            _m.plugboard_tokens.labels(
                                client=rec.client,
                                model=rec.model,
                                direction=direction,
                            ).inc(n)
                if rec.item_count:
                    _m.plugboard_items.labels(client=rec.client, model=rec.model).inc(
                        rec.item_count
                    )

            # Async DB-enqueue branch: map to an LlmCallRecord and hand off to
            # the writer task. Non-blocking; drop on overload (ADR 0057).
            #
            # This sink runs synchronously inside record_plugboard_call AFTER a
            # successful LLM call and before its response is returned. If anything
            # here raises (e.g. _to_llm_record hitting a malformed subcall or a
            # pydantic ValidationError), it must NOT turn a successful LLM call
            # into a failure -- so the entire mapping+enqueue is guarded and
            # tracking failures are logged and dropped, never propagated.
            q = app.state.llm_write_q
            if q is not None:
                try:
                    record = _to_llm_record(rec)
                    if record is not None:
                        q.put_nowait(record)
                except asyncio.QueueFull:
                    logger.warning("llm_calls write queue full; dropping record")
                    app.state.llm_dropped += 1
                except Exception:
                    logger.exception("llm_calls tracking failed; dropping record")
                    app.state.llm_dropped += 1

        app.state.plugboard_sink = _plugboard_sink
        inner_llm = getattr(app.state.llm, "_inner", app.state.llm)
        inner_llm._sink = _plugboard_sink
        if app.state.queue_scorer is not None:
            app.state.queue_scorer._sink = _plugboard_sink

        # Async llm_calls writer task: drain the bounded queue in batches and
        # persist via save_many. A DB failure drops the batch, never the loop.
        if app.state.llm_write_q is not None:
            _q = app.state.llm_write_q

            async def _llm_writer_loop():
                try:
                    while True:
                        await _drain_once(
                            _q,
                            app.state.stores.llm_calls,
                            entity_links=app.state.stores.entity_links,
                            max_batch=50,
                        )
                except asyncio.CancelledError:
                    return

            app.state.llm_writer_task = asyncio.create_task(_llm_writer_loop())

        # Periodic batched structured-log summary of plugboard usage (spec 3.6):
        # drain the aggregator every summary_interval_seconds and emit one
        # llm_usage_summary line; skip empty intervals.
        if config.metrics.enabled and config.metrics.summary_log:
            _interval = config.metrics.summary_interval_seconds

            async def _summary_loop():
                while True:
                    await asyncio.sleep(_interval)
                    snapshot = app.state.usage_agg.drain()
                    if not snapshot:
                        continue
                    usage = {
                        f"{client}/{model}": counts
                        for (client, model), counts in snapshot.items()
                    }
                    logger.info(
                        "llm_usage_summary",
                        process="workbench",
                        interval_seconds=_interval,
                        usage=usage,
                    )

            app.state.summary_task = asyncio.create_task(_summary_loop())

    app.state.sources = create_providers_from_list(
        config.sources, connections=connections, metrics=app.state.metrics
    )

    # Targeted Hot-Reload plumbing: a single lock serializes source/messenger
    # config write-back + swap; config_path is the base YAML we edit.
    app.state.reload_lock = asyncio.Lock()
    app.state.config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")

    # Sync YAML sources (config.yml is the source of truth) into source_configs
    # so get_sources() reflects the live set. Stable ids are written back to YAML.
    from workbench.config.writer import write_source as _yaml_write_source
    from workbench.domain import SourceConfig as _SourceConfig
    from workbench.domain import SourceRelevanceConfig as _SourceRelevanceConfig
    from workbench.providers.registry import source_id_for as _source_id_for

    # Per-source relevance/noise thresholds keyed by adapter_type (== the
    # ingested item source_type), loaded from YAML for the PipelineEngine
    # (ADR0044). Absent -> the global PipelineConfig thresholds apply.
    source_thresholds: dict = {}
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
        relevance = None
        raw_relevance = raw.get("relevance")
        if raw_relevance:
            try:
                relevance = _SourceRelevanceConfig(**dict(raw_relevance))
                source_thresholds[adapter_type] = relevance
            except Exception:
                logger.warning(
                    "Invalid per-source relevance config; using global thresholds",
                    source_id=sid,
                )
        sc = _SourceConfig(
            id=sid,
            adapter_type=adapter_type,
            config=raw.get("config", {}),
            schedule=raw.get("schedule", "*/15 * * * *"),
            enabled=raw.get("enabled", True),
            relevance=relevance,
        )
        await app.state.stores.sources.upsert_source(sc)

    from workbench.pipeline.engine import PipelineEngine

    # Presentation layer: CompositeCardPresenter + per-source content generators
    # built from the `presentation` config (ADR 0023/0024/0029).
    from workbench.pipeline.presenter import build_composite_presenter
    from workbench.pipeline.content_generator import build_content_generators

    app.state.presenter = build_composite_presenter(config.presentation)
    app.state.content_generators = build_content_generators(config.presentation)

    app.state.pipeline = PipelineEngine(
        app.state.stores,
        app.state.memory,
        app.state.llm,
        app.state.enricher,
        queue_scorer=app.state.queue_scorer,
        content_generators=app.state.content_generators,
        triage_expiry_days=config.triage.expiry_days,
        record_drop_decisions=config.pipeline.record_drop_decisions,
        include_threshold=config.pipeline.include_threshold,
        drop_threshold=config.pipeline.drop_threshold,
        confidence_threshold=config.pipeline.confidence_threshold,
        batch_relevance=config.batching.enabled and config.batching.score_relevance,
        max_batch_size=config.batching.max_batch_size,
        source_thresholds=source_thresholds,
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
    from workbench.domain import SourceConfig
    from workbench.providers.registry import source_id_for

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
    app.state.scheduler.presenter = app.state.presenter
    # Change-monitoring: register per-source-type ChangeDetectors from config.
    app.state.scheduler._change_detectors = build_change_detectors(config.sources)
    app.state.scheduler.start()
    logger.info("Workbench ready", version=__version__, port=config.server.port)

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
    summary_task = getattr(app.state, "summary_task", None)
    if summary_task is not None:
        summary_task.cancel()
        try:
            await summary_task
        except asyncio.CancelledError:
            pass
    llm_writer_task = getattr(app.state, "llm_writer_task", None)
    if llm_writer_task is not None:
        llm_writer_task.cancel()
        try:
            await llm_writer_task
        except asyncio.CancelledError:
            pass

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
        client_logs,
        config as config_api,
        connections,
        debug,
        enrichers,
        feedback,
        filter_rules,
        funnel,
        health,
        identity,
        items,
        jobs,
        llm,
        loopbacks,
        memory,
        messenger,
        process,
        queue,
        search,
        sources,
        stats,
        topology,
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
        topology.router,
        search.router,
        feedback.router,
        enrichers.router,
        loopbacks.router,
        funnel.router,
        llm.router,
        client_logs.router,
    ]:
        app.include_router(r)

    # Prometheus metrics endpoint (unauthenticated, excluded from schema)
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from starlette.responses import Response

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        from starlette.responses import RedirectResponse

        return RedirectResponse(url="/ui/")

    ui_dir = os.path.join(os.path.dirname(__file__), "../../../ui/dist")
    if os.path.exists(ui_dir):
        from starlette.staticfiles import StaticFiles

        app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")

    return app


app = create_app()


def cli_main():
    import uvicorn

    config = get_config()
    uvicorn.run(
        "workbench.runtime.app:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.debug,
        # None for both leaves uvicorn on plain HTTP; set together to serve TLS.
        ssl_certfile=config.server.ssl_certfile,
        ssl_keyfile=config.server.ssl_keyfile,
    )
