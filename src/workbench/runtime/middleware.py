from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, binds it (plus method/path) to the structlog
    context, and logs every request's outcome.

    The outcome log is the safety net for HTTP failures: a 4xx/5xx that never
    reaches an endpoint's own try/except (e.g. a 404 for an unmatched route, a
    401 from auth) would otherwise leave no trace in the logs. Levels by class:
    5xx/unhandled -> error, 4xx -> warning, else -> info.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        start = time.monotonic()
        try:
            response: Response = await call_next(request)
        except Exception:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "request failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = round((time.monotonic() - start) * 1000, 2)
        status = response.status_code
        if status >= 500:
            log = logger.error
        elif status >= 400:
            log = logger.warning
        else:
            log = logger.info
        log(
            "request completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status,
            duration_ms=duration_ms,
        )

        response.headers["X-Request-ID"] = request_id
        return response
