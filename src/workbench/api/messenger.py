"""Messenger info/edit API (Task C1, ADRs 0013 + 0016).

GET /api/messenger   -- always 200; {configured, type, class, config} envelope
                        (+ {reachable, checked_at} with ?check=true).
PATCH /api/messenger -- write the messenger node back to config.yml (preserving
                        ${oc.env:...} secret interpolations) and hot-swap the
                        live messenger plus the scheduler / alert-manager refs.

Output discipline: the serialized ``config`` is built from an explicit
allowlist of non-secret fields, then passed through ``redact_secrets`` as a
fail-closed backstop. A secret value (e.g. service_account_key_path) must never
appear in any response, and is never accepted from the request body.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from workbench.config_writer import write_messenger
from workbench.redaction import _is_secret_key, redact_secrets
from workbench.registry import close_provider, create_provider

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["messenger"])

# Map provider class names to short, stable type labels (spec section 7.1).
_MESSENGER_TYPES = {
    "GoogleChatMessenger": "google_chat",
    "ConsoleMessenger": "console",
}

# Map short type labels back to dotted provider class paths (PATCH input).
_TYPE_TO_CLASS = {
    "google_chat": "workbench.providers.messenger.google_chat.GoogleChatMessenger",
    "console": "workbench.providers.messenger.console.ConsoleMessenger",
}

# allowlist-on-output: only these config fields are ever serialized, per type.
# Defaults to the GoogleChat allowlist; Console exposes nothing.
_ALLOWED_BY_TYPE: dict[str, tuple[str, ...]] = {
    "google_chat": ("space_id", "timeout_seconds"),
    "console": (),
}
_DEFAULT_ALLOWED = ("space_id", "timeout_seconds")


def _read_field(inner, field: str):
    """Read an allowlisted field from a messenger, tolerating both shapes.

    The real GoogleChatMessenger stores config as flat attributes (space_id,
    _timeout); the typed ProviderConfig (and test doubles) expose a _config
    object. timeout_seconds maps to the flat _timeout attribute.
    """
    cfg = getattr(inner, "_config", None)
    if cfg is not None and hasattr(cfg, field):
        return getattr(cfg, field)
    if hasattr(inner, field):
        return getattr(inner, field)
    if field == "timeout_seconds" and hasattr(inner, "_timeout"):
        return getattr(inner, "_timeout")
    return None


def _allowlisted_config(inner, type_label: str) -> dict:
    allowed = _ALLOWED_BY_TYPE.get(type_label, _DEFAULT_ALLOWED)
    out: dict = {}
    for field in allowed:
        # Never serialize a field whose name itself looks secret.
        if _is_secret_key(field):
            continue
        value = _read_field(inner, field)
        if value is not None:
            out[field] = value
    # Fail-closed backstop: scrub anything secret-shaped that slipped through.
    return redact_secrets(out)


@router.get("/messenger")
async def get_messenger(request: Request, check: bool = Query(False)):
    messenger = getattr(request.app.state, "messenger", None)
    if messenger is None:
        return {"configured": False, "type": "none", "class": None, "config": {}}

    # Messengers may be wrapped by an Instrumented* decorator; unwrap to inspect.
    inner = getattr(messenger, "_inner", messenger)
    type_label = _MESSENGER_TYPES.get(type(inner).__name__, type(inner).__name__)
    data = {
        "configured": True,
        "type": type_label,
        "class": type(inner).__qualname__,
        "config": _allowlisted_config(inner, type_label),
    }

    if check:
        data["checked_at"] = datetime.now(timezone.utc).isoformat()
        if hasattr(inner, "is_reachable"):
            # Best-effort probe; never crash the read path.
            try:
                data["reachable"] = bool(await inner.is_reachable())
            except Exception:
                data["reachable"] = False
                data["note"] = "reachability probe failed"
        elif type_label == "console":
            # Console writes to stdout: always reachable.
            data["reachable"] = True
        else:
            # No cheap reachability check available (e.g. GoogleChat).
            data["reachable"] = None
            data["note"] = "no reachability probe available for this messenger"
    return data


class MessengerPatchBody(BaseModel):
    """Editable, non-secret messenger config.

    ``class`` may be a dotted provider path; ``type`` may be a short label
    (google_chat / console). Secret fields are rejected in the handler.
    """

    class_: str | None = None
    type: str | None = None
    space_id: str | None = None
    timeout_seconds: int | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    def __init__(self, **data):
        # Accept the reserved word "class" from JSON bodies.
        if "class" in data and "class_" not in data:
            data["class_"] = data.pop("class")
        super().__init__(**data)


@router.patch("/messenger")
async def patch_messenger(body: MessengerPatchBody, request: Request):
    config_path = getattr(request.app.state, "config_path", None) or os.environ.get(
        "WORKBENCH_CONFIG", "config.yml"
    )
    lock = getattr(request.app.state, "reload_lock", None)

    raw = body.model_dump(exclude_none=True)
    raw.pop("class_", None)
    raw.pop("type", None)

    # Reject any secret-shaped field from the browser (ADR 0013): secrets stay
    # as ${oc.env:...} references in YAML and are never accepted resolved.
    for key in raw:
        if _is_secret_key(str(key)):
            raise HTTPException(422, f"Secret field '{key}' may not be set via the API")

    # Resolve the target provider class: explicit dotted class, short type, or
    # the existing messenger's class.
    class_path = body.class_
    if not class_path and body.type:
        class_path = _TYPE_TO_CLASS.get(body.type)
        if class_path is None:
            raise HTTPException(422, f"Unknown messenger type '{body.type}'")
    if not class_path:
        current = getattr(request.app.state, "config", None)
        existing = getattr(current, "messenger", None) if current else None
        class_path = (existing or {}).get("class") if existing else None
    if not class_path:
        raise HTTPException(422, "No messenger class or type specified")

    # The provider section: class + non-secret fields. Carry forward existing
    # secret interpolations (service_account_key_path) from the live config so
    # instantiation can validate; write_messenger preserves them on disk.
    section: dict = {"class": class_path}
    current = getattr(request.app.state, "config", None)
    existing = (getattr(current, "messenger", None) or {}) if current else {}
    if existing.get("class") == class_path:
        for k, v in existing.items():
            if k == "class":
                continue
            section[k] = v
    section.update(raw)

    if lock is None:
        import asyncio

        lock = asyncio.Lock()

    async with lock:
        # validate -> instantiate (nothing written if this fails) ...
        try:
            new_messenger = create_provider(dict(section))
        except Exception as e:
            logger.warning("messenger_validation_failed", error=str(e))
            raise HTTPException(422, f"Invalid messenger config: {e}") from e

        # ... write YAML (only safe, provided fields) ...
        write_messenger(config_path, raw | {"class": class_path})

        # ... close the old provider, then copy-on-write swap.
        old = getattr(request.app.state, "messenger", None)
        request.app.state.messenger = new_messenger
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            if hasattr(scheduler, "set_messenger"):
                scheduler.set_messenger(new_messenger)
            else:  # pragma: no cover - defensive
                scheduler.messenger = new_messenger
                if hasattr(scheduler, "alert_manager"):
                    scheduler.alert_manager._messenger = new_messenger
        if old is not None and old is not new_messenger:
            await close_provider(old)

    logger.info("messenger_updated", fields=list(raw.keys()), provider=class_path)
    return {
        "status": "updated",
        "type": _MESSENGER_TYPES.get(
            type(new_messenger).__name__, type(new_messenger).__name__
        ),
        "config": _allowlisted_config(
            new_messenger,
            _MESSENGER_TYPES.get(
                type(new_messenger).__name__, type(new_messenger).__name__
            ),
        ),
    }
