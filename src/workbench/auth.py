import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str = None):
        super().__init__(app)
        self._token = token

    @property
    def token(self) -> str | None:
        if self._token is not None:
            return self._token
        try:
            from workbench.config import load_config
            config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")
            override_path = os.environ.get("WORKBENCH_CONFIG_OVERRIDE")
            config = load_config(config_path, override_path)
            self._token = config.server.api_token
            return self._token
        except (SystemExit, Exception):
            return None

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        token = self.token
        if token and request.headers.get("Authorization", "") != f"Bearer {token}":
            return JSONResponse(
                status_code=401, content={"detail": "Invalid token"}
            )
        return await call_next(request)
