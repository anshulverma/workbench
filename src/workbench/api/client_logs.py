from __future__ import annotations

import json
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/client-logs", tags=["client-logs"])

MAX_EVENTS_PER_BATCH = 50


class ClientLogEvent(BaseModel):
    level: Literal["error", "warn", "info"]
    kind: Literal["uncaught", "unhandledrejection", "react", "api", "console"]
    message: str = Field(max_length=4000)
    stack: str | None = Field(default=None, max_length=16000)
    component_stack: str | None = Field(default=None, max_length=16000)
    source: str | None = Field(default=None, max_length=2000)
    line: int | None = None
    col: int | None = None
    url: str | None = Field(default=None, max_length=2000)
    ts: int
    request_id: str | None = Field(default=None, max_length=200)
    count: int = 1
    extra: dict[str, Any] | None = None


class ClientLogBatch(BaseModel):
    events: list[ClientLogEvent]


_LEVEL_METHOD = {"error": "error", "warn": "warning", "info": "info"}


@router.post("", status_code=204)
async def ingest_client_logs(batch: ClientLogBatch) -> Response:
    logger = structlog.get_logger("workbench.client")
    if len(batch.events) > MAX_EVENTS_PER_BATCH:
        raise HTTPException(status_code=413, detail="too many events")
    for e in batch.events:
        method = getattr(logger, _LEVEL_METHOD[e.level])
        # Serialize `extra` to a JSON string so SanitizingProcessor (which only
        # redacts str values) can redact any PII inside it; a raw dict would be
        # skipped and bypass redaction.
        extra_json = json.dumps(e.extra, default=str) if e.extra is not None else None
        method(
            f"client_{e.level}",
            kind=e.kind,
            client_message=e.message,
            stack=e.stack,
            component_stack=e.component_stack,
            source=e.source,
            line=e.line,
            col=e.col,
            page_url=e.url,
            request_id=e.request_id,
            count=e.count,
            extra_json=extra_json,
            client_ts=e.ts,
        )
    return Response(status_code=204)
