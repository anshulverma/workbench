from __future__ import annotations

import asyncio
import os

from pydantic import BaseModel

from workbench.providers.connection.base import Connection

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    Credentials = None
    Request = None
    build = None


class GoogleConnection(Connection):
    class ProviderConfig(BaseModel):
        credentials_path: str
        token_path: str
        scopes: list[str]

    def __init__(self, config: GoogleConnection.ProviderConfig, **kwargs):
        self._config = config
        self._credentials: Credentials | None = None
        self._gmail_service = None
        self._calendar_service = None
        self._chat_service = None
        self._initialized = False

    async def initialize(self) -> None:
        if not os.path.exists(self._config.token_path):
            raise FileNotFoundError(
                f"Google OAuth token not found at {self._config.token_path}. "
                f"Run the OAuth consent flow first to create the token file."
            )

        def _load():
            creds = Credentials.from_authorized_user_file(
                self._config.token_path, self._config.scopes,
            )
            if not creds.valid and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(self._config.token_path, "w") as f:
                    f.write(creds.to_json())
            return creds

        self._credentials = await asyncio.to_thread(_load)
        self._initialized = True

    @property
    def gmail(self):
        if self._gmail_service is None:
            self._gmail_service = build("gmail", "v1", credentials=self._credentials)
        return self._gmail_service

    @property
    def calendar(self):
        if self._calendar_service is None:
            self._calendar_service = build("calendar", "v3", credentials=self._credentials)
        return self._calendar_service

    @property
    def chat(self):
        if self._chat_service is None:
            self._chat_service = build("chat", "v1", credentials=self._credentials)
        return self._chat_service

    async def close(self) -> None:
        self._gmail_service = None
        self._calendar_service = None
        self._chat_service = None
        self._initialized = False

    def is_healthy(self) -> bool:
        return self._initialized and self._credentials is not None and (
            self._credentials.valid or self._credentials.refresh_token is not None
        )
