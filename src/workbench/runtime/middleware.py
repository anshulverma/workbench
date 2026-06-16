from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

# Cap the captured error-response body so a large error payload can't bloat a
# log line. The privacy sanitizer truncates again downstream, but bound it here
# too to avoid decoding/holding more than we need on the failure path.
_MAX_ERROR_BODY = 2048


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, binds it (plus method/path/query) to the structlog
    context, and logs every request's outcome.

    The outcome log is the safety net for HTTP failures: a 4xx/5xx that never
    reaches an endpoint's own try/except (e.g. a 404 for an unmatched route, a
    401 from auth) would otherwise leave no trace in the logs. Levels by class:
    5xx/unhandled -> error, 4xx -> warning, else -> info.

    For failures (>=400) the log line additionally carries the request's query
    string, the client host, the user-agent, and the response body (FastAPI's
    ``{"detail": ...}`` or the validation-error payload) so a warning/error says
    *what* went wrong, not merely that something did. Success responses skip the
    body capture entirely, so large/static/streaming bodies stay off this path.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        query = request.url.query
        client_host = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            # Bound only when present so ordinary logs don't carry an empty key;
            # every log emitted during the request then inherits the query too.
            **({"query": query} if query else {}),
        )

        start = time.monotonic()
        try:
            response: Response = await call_next(request)
        except Exception:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            # exc_info=True renders the full traceback so the unhandled exception
            # — not just "request failed" — is what lands in the log.
            logger.error(
                "request failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
                client=client_host,
                user_agent=user_agent,
                exc_info=True,
            )
            raise

        duration_ms = round((time.monotonic() - start) * 1000, 2)
        status = response.status_code

        # On failure, capture the response body so the log shows the actual error
        # detail. BaseHTTPMiddleware hands back a streaming response, so its body
        # iterator must be drained and an equivalent Response rebuilt; restrict
        # this to >=400 to keep success responses off the buffering path.
        error_detail = None
        if status >= 400:
            response, error_detail = await _capture_body(response)

        if status >= 500:
            log = logger.error
        elif status >= 400:
            log = logger.warning
        else:
            log = logger.info

        fields = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status,
            "duration_ms": duration_ms,
        }
        if status >= 400:
            fields["client"] = client_host
            fields["user_agent"] = user_agent
            fields["error_detail"] = error_detail
        log("request completed", **fields)

        response.headers["X-Request-ID"] = request_id
        return response


async def _capture_body(response: Response) -> tuple[Response, str | None]:
    """Drain a streaming response's body so it can be logged, returning a Response
    safe to send (the original body iterator is single-use, so a rebuilt one) plus
    the decoded, truncated body text. Never raises: on any failure the original
    response is returned with a ``None`` detail so a logging problem can't turn a
    handled 4xx into a 500.
    """
    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is None:
        # Already a plain Response with a materialized .body — nothing to rebuild.
        return response, _decode(getattr(response, "body", b"") or b"")
    try:
        chunks = [chunk async for chunk in body_iterator]
    except Exception:
        return response, None
    raw = b"".join(
        c if isinstance(c, bytes) else c.encode("utf-8", "replace") for c in chunks
    )
    # Same bytes/headers, so the original content-length/content-type stay valid.
    rebuilt = Response(
        content=raw,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )
    return rebuilt, _decode(raw)


def _decode(raw: bytes) -> str | None:
    if not raw:
        return None
    text = raw.decode("utf-8", "replace")
    if len(text) > _MAX_ERROR_BODY:
        text = text[:_MAX_ERROR_BODY] + "... [truncated]"
    return text
