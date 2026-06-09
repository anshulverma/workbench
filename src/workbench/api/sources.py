"""Source management API: CRUD + manual poll + adapter introspection.

Source create/edit/delete write definitions back to ``config.yml`` via Config
Write-Back (ruamel round-trip) and apply a Targeted Hot-Reload of the live
adapter without a restart. Sequence under a single ``app.state.reload_lock``:
validate -> instantiate -> write YAML -> copy-on-write swap into
``app.state.sources`` + scheduler. If instantiation fails, NOTHING is written.

``adapter_type`` is restricted to a server-side allowlist; a raw dotted class
path is never accepted from the client (import-gadget guard).
"""

from __future__ import annotations

import importlib
import inspect
import os

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from workbench.config_writer import delete_source as yaml_delete_source
from workbench.config_writer import write_source as yaml_write_source
from workbench.domain import JobTrigger, SourceConfig, SourceConfigUpdate
from workbench.registry import close_provider

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["sources"])

# Import-gadget guard: short adapter_type -> dotted class path. The client never
# supplies a class path; only these four short names are accepted.
ADAPTER_ALLOWLIST = {
    "github": "workbench.providers.source.github.GitHubSourceAdapter",
    "email": "workbench.providers.source.gmail.GmailAdapter",
    "calendar": "workbench.providers.source.gcalendar.GCalendarAdapter",
    "chat": "workbench.providers.source.gchat.GChatAdapter",
}


def _load_adapter_cls(adapter_type: str):
    class_path = ADAPTER_ALLOWLIST[adapter_type]
    module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _requires_connection(cls) -> bool:
    return "connection" in inspect.signature(cls.__init__).parameters


class CreateSourceBody(BaseModel):
    adapter_type: str
    config: dict = {}
    schedule: str = "*/15 * * * *"
    enabled: bool = True
    connection: str | None = None


def _validate_cron(schedule: str, tz: str) -> None:
    try:
        from zoneinfo import ZoneInfo

        from apscheduler.triggers.cron import CronTrigger

        CronTrigger.from_crontab(schedule, timezone=ZoneInfo(tz))
    except Exception as e:
        raise HTTPException(422, f"Invalid cron schedule: {e}")


def _validate_config(cls, config: dict) -> None:
    if hasattr(cls, "ProviderConfig"):
        try:
            cls.ProviderConfig(**config)
        except ValidationError as e:
            raise HTTPException(422, {"config_errors": e.errors()})


def _config_path(request: Request) -> str:
    path = getattr(request.app.state, "config_path", None)
    return path or os.environ.get("WORKBENCH_CONFIG", "config.yml")


def _instantiate(
    request: Request, adapter_type: str, config: dict, connection_name: str | None
):
    """Instantiate the live adapter, wrapped with metrics instrumentation.

    Raises HTTPException(422) if a required connection is missing/unknown. A
    ValidationError / ImportError propagates so the caller writes nothing.
    """
    cls = _load_adapter_cls(adapter_type)
    connections = getattr(request.app.state, "connections", {})
    kwargs: dict = {}
    if _requires_connection(cls):
        if not connection_name or connection_name not in connections:
            raise HTTPException(
                422,
                f"adapter_type '{adapter_type}' requires a defined connection; "
                f"'{connection_name}' is not configured "
                f"(connections are YAML-only + restart).",
            )
        kwargs["connection"] = connections[connection_name]
    typed = cls.ProviderConfig(**config) if hasattr(cls, "ProviderConfig") else None
    adapter = cls(typed, **kwargs) if typed is not None else cls(**kwargs)

    metrics = getattr(request.app.state, "metrics", None)
    if metrics is not None:
        from workbench.instrumentation import InstrumentedSourceAdapter

        adapter = InstrumentedSourceAdapter(adapter, adapter_type, metrics)
    return adapter


@router.get("/sources/adapter-types")
async def adapter_types(request: Request):
    """Per allowlisted adapter_type: ProviderConfig JSON schema + connection need."""
    result = []
    for name in ADAPTER_ALLOWLIST:
        cls = _load_adapter_cls(name)
        schema = (
            cls.ProviderConfig.model_json_schema()
            if hasattr(cls, "ProviderConfig")
            else {}
        )
        result.append(
            {
                "adapter_type": name,
                "json_schema": schema,
                "requires_connection": _requires_connection(cls),
            }
        )
    return result


@router.get("/sources")
async def list_sources(request: Request):
    stores = request.app.state.stores
    return await stores.sources.get_sources()


@router.post("/sources")
async def create_source(body: CreateSourceBody, request: Request):
    if body.adapter_type not in ADAPTER_ALLOWLIST:
        raise HTTPException(422, f"Unknown adapter_type '{body.adapter_type}'")
    cls = _load_adapter_cls(body.adapter_type)
    _validate_cron(body.schedule, request.app.state.config.logging.timezone)
    _validate_config(cls, body.config)

    source = SourceConfig(
        adapter_type=body.adapter_type,
        config=body.config,
        schedule=body.schedule,
        enabled=body.enabled,
    )

    lock = request.app.state.reload_lock
    async with lock:
        # validate -> instantiate -> write YAML -> swap. If instantiate raises,
        # we have written nothing.
        adapter = _instantiate(request, body.adapter_type, body.config, body.connection)
        try:
            adapter._source_id = source.id  # type: ignore[attr-defined]
        except Exception:
            pass
        node: dict = {
            "id": source.id,
            "adapter_type": source.adapter_type,
            "config": source.config,
            "schedule": source.schedule,
            "enabled": source.enabled,
        }
        if body.connection:
            node["connection"] = body.connection
        yaml_write_source(_config_path(request), node)
        await request.app.state.stores.sources.upsert_source(source)
        # copy-on-write swap so the scheduler poll loop never sees a mid-mutation list
        request.app.state.sources = list(request.app.state.sources) + [adapter]
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            scheduler._db_sources = list(scheduler._db_sources) + [source]
            scheduler.add_source_job(source, adapter)

    logger.info(
        "source_created",
        source_id=source.id,
        adapter_type=source.adapter_type,
    )
    return source


@router.patch("/sources/{source_id}")
async def update_source(source_id: str, updates: SourceConfigUpdate, request: Request):
    stores = request.app.state.stores
    source = await stores.sources.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if updates.adapter_type is not None and updates.adapter_type != source.adapter_type:
        raise HTTPException(422, "adapter_type is immutable")

    cls = _load_adapter_cls(source.adapter_type)
    new_config = updates.config if updates.config is not None else source.config
    new_schedule = updates.schedule if updates.schedule is not None else source.schedule
    new_enabled = updates.enabled if updates.enabled is not None else source.enabled
    # Per-source relevance/noise thresholds (ADR0044). None on the patch body
    # means "leave unchanged"; the field is validated/ordered by the pydantic
    # SourceRelevanceConfig model, so an invalid payload already 422s.
    new_relevance = (
        updates.relevance if updates.relevance is not None else source.relevance
    )
    _validate_cron(new_schedule, request.app.state.config.logging.timezone)
    _validate_config(cls, new_config)

    lock = request.app.state.reload_lock
    async with lock:
        adapter = _instantiate(
            request, source.adapter_type, new_config, updates.connection
        )
        node = {
            "id": source.id,
            "adapter_type": source.adapter_type,
            "config": new_config,
            "schedule": new_schedule,
            "enabled": new_enabled,
        }
        if updates.connection:
            node["connection"] = updates.connection
        if new_relevance is not None:
            node["relevance"] = new_relevance.model_dump()
        yaml_write_source(_config_path(request), node)
        updated = await stores.sources.update_source(
            source_id,
            SourceConfigUpdate(
                config=new_config,
                schedule=new_schedule,
                enabled=new_enabled,
                relevance=new_relevance,
            ),
        )
        # Replace the live adapter in app.state.sources (copy-on-write).
        old = getattr(adapter, "_source_id", None)
        new_list = [
            a
            for a in request.app.state.sources
            if getattr(a, "_source_id", None) != source_id
        ]
        try:
            adapter._source_id = source_id  # type: ignore[attr-defined]
        except Exception:
            pass
        request.app.state.sources = new_list + [adapter]
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            # reschedule_source_job removes any old job and re-adds only if enabled.
            scheduler.reschedule_source_job(updated, adapter)
        # Targeted Hot-Reload of relevance/noise thresholds (ADR0044/ADR0013):
        # mutate the live PipelineEngine so subsequent ingestion re-routes with
        # the new thresholds, no restart. Keyed by source_type (== adapter_type).
        pipeline = getattr(request.app.state, "pipeline", None)
        if pipeline is not None and hasattr(pipeline, "set_source_thresholds"):
            pipeline.set_source_thresholds(source.adapter_type, new_relevance)

    logger.info("source_updated", source_id=source_id)
    return updated


@router.delete("/sources/{source_id}")
async def remove_source(source_id: str, request: Request):
    stores = request.app.state.stores
    source = await stores.sources.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    lock = request.app.state.reload_lock
    async with lock:
        yaml_delete_source(_config_path(request), source_id)
        await stores.sources.pool.execute(
            "DELETE FROM source_configs WHERE id = $1", source_id
        )
        removed = None
        new_list = []
        for a in request.app.state.sources:
            if getattr(a, "_source_id", None) == source_id:
                removed = a
            else:
                new_list.append(a)
        request.app.state.sources = new_list
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            if removed is None:
                removed = scheduler._source_by_id.get(source_id)
            scheduler.remove_source_job(source_id)
            scheduler._db_sources = [
                s for s in scheduler._db_sources if s.id != source_id
            ]
        if removed is not None:
            await close_provider(removed)
        # Drop the per-source watermark so a re-created source starts clean.
        try:
            await stores.config.pool.execute(
                "DELETE FROM config WHERE key = $1",
                f"source_last_polled:{source_id}",
            )
        except Exception:
            pass

    logger.info("source_deleted", source_id=source_id)
    return {"status": "deleted"}


@router.post("/sources/{source_id}/poll")
async def poll_source_now(source_id: str, request: Request):
    stores = request.app.state.stores
    source = await stores.sources.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(503, "Scheduler not available")
    await scheduler._poll_one_source(source_id, JobTrigger.MANUAL)
    latest = await stores.ingestion_runs.latest_for_source(source_id)
    return {
        "status": "polled",
        "source_id": source_id,
        "run_id": latest.id if latest else None,
        "run_status": latest.status if latest else None,
    }
