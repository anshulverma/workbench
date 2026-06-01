# src/workbench/providers/messenger/google_chat.py
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from workbench.providers.messenger.base import Messenger

logger = logging.getLogger(__name__)

CHAT_API_BASE = "https://chat.googleapis.com/v1"


class GoogleChatMessenger(Messenger):
    class ProviderConfig(BaseModel):
        space_id: str
        service_account_key_path: str
        timeout_seconds: int = 30

    def __init__(self, config: ProviderConfig):
        self.space_id = config.space_id
        self._key_path = config.service_account_key_path
        self._timeout = config.timeout_seconds
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self._credentials = None

    def _ensure_credentials(self) -> None:
        if self._credentials is None:
            import google.oauth2.service_account
            import google.auth.transport.requests
            self._credentials = google.oauth2.service_account.Credentials.from_service_account_file(
                self._key_path,
                scopes=["https://www.googleapis.com/auth/chat.bot"],
            )
            self._auth_request = google.auth.transport.requests.Request()

    def _get_headers(self) -> dict[str, str]:
        self._ensure_credentials()
        if not self._credentials.valid:
            self._credentials.refresh(getattr(self, "_auth_request", None))
        return {
            "Authorization": f"Bearer {self._credentials.token}",
            "Content-Type": "application/json",
        }

    async def send_card(self, card_text: str) -> str:
        url = f"{CHAT_API_BASE}/{self.space_id}/messages"
        headers = self._get_headers()
        resp = await self._client.post(url, headers=headers, json={"text": card_text})
        resp.raise_for_status()
        msg_name = resp.json()["name"]
        logger.info("Sent triage card: %s", msg_name)
        return msg_name

    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]:
        url = f"{CHAT_API_BASE}/{self.space_id}/messages"
        headers = self._get_headers()
        resp = await self._client.get(url, headers=headers, params={"orderBy": "createTime asc"})
        resp.raise_for_status()
        messages = resp.json().get("messages", [])

        found_since = since_message_id is None
        results = []
        for msg in messages:
            if not found_since:
                if msg.get("name") == since_message_id:
                    found_since = True
                continue
            if msg.get("sender", {}).get("type") == "HUMAN":
                results.append({"text": msg.get("text", ""), "message_id": msg["name"]})
        return results

    async def close(self) -> None:
        await self._client.aclose()
