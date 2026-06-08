import logging
import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str = None):
        super().__init__(app)
        self._token = token

    def _resolve_token(self, request: Request | None = None) -> str | None:
        if self._token is not None:
            return self._token
        if request is not None:
            try:
                config = request.app.state.config
                self._token = config.server.api_token
                return self._token
            except AttributeError:
                pass
        try:
            from workbench.config import load_config

            config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")
            override_path = os.environ.get("WORKBENCH_CONFIG_OVERRIDE")
            config = load_config(config_path, override_path)
            self._token = config.server.api_token
            return self._token
        except (SystemExit, Exception):
            logger.error("Failed to load API token from config", exc_info=True)
            return None

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/health", "/health/live", "/health/ready", "/metrics"):
            return await call_next(request)
        if path.startswith("/ui") or path == "/api/auth/token":
            return await call_next(request)
        token = self._resolve_token(request)
        if token and request.headers.get("Authorization", "") != f"Bearer {token}":
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})
        return await call_next(request)
