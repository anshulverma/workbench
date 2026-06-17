from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime
from html.parser import HTMLParser

from pydantic import BaseModel

from workbench.domain import RawItem
from workbench.providers.source.base import SourceAdapter


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def get_text(self) -> str:
        return "".join(self.text)


def _strip_html(html: str) -> str:
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType", "").startswith("text/plain") and payload.get(
        "body", {}
    ).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            "utf-8", errors="replace"
        )

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            html = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
            return _strip_html(html)

    if payload.get("body", {}).get("data"):
        raw = base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            "utf-8", errors="replace"
        )
        if payload.get("mimeType", "").startswith("text/html"):
            return _strip_html(raw)
        return raw

    return ""


def _clean_body(body: str) -> str:
    lines = body.split("\n")
    cleaned = []
    for line in lines:
        if line.strip().startswith(">"):
            continue
        if line.strip() == "--":
            break
        cleaned.append(line)
    text = "\n".join(cleaned).strip()
    return text[:4000]


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_attachments(payload: dict) -> list[dict]:
    attachments = []
    for part in payload.get("parts", []):
        if part.get("filename"):
            header_names = {h.get("name", "") for h in part.get("headers", [])}
            attachments.append(
                {
                    "filename": part["filename"],
                    "mime_type": part.get("mimeType", ""),
                    "size_bytes": int(part.get("body", {}).get("size", 0)),
                    "attachment_id": part.get("body", {}).get("attachmentId", ""),
                    "inline": "Content-ID" in header_names,
                }
            )
    return attachments


class GmailAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        label_filters: list[str] = ["INBOX", "UNREAD"]
        max_results: int = 50

    def __init__(self, config: ProviderConfig, connection=None):
        self._config = config
        self._connection = connection

    def adapter_type(self) -> str:
        return "email"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self._connection:
            return []

        query = " ".join(f"label:{lbl}" for lbl in self._config.label_filters)
        if since:
            query += f" after:{int(since.timestamp())}"

        def _fetch():
            result = (
                self._connection.gmail.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=self._config.max_results,
                )
                .execute()
            )
            return result.get("messages", [])

        message_stubs = await asyncio.to_thread(_fetch)
        items: list[RawItem] = []
        for stub in message_stubs:
            msg_id = stub["id"]

            def _get_message(mid=msg_id):
                return (
                    self._connection.gmail.users()
                    .messages()
                    .get(
                        userId="me",
                        id=mid,
                        format="full",
                    )
                    .execute()
                )

            msg = await asyncio.to_thread(_get_message)
            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            subject = _get_header(headers, "Subject")
            sender = _get_header(headers, "From")
            to = _get_header(headers, "To")
            cc = _get_header(headers, "Cc")

            body = _clean_body(_extract_body(payload))
            attachments = _extract_attachments(payload)

            recipients_to = [r.strip() for r in to.split(",") if r.strip()]
            recipients_cc = [r.strip() for r in cc.split(",") if r.strip()]

            raw_text = json.dumps(
                {
                    "subject": subject,
                    "sender": sender,
                    "recipients_to": recipients_to,
                    "recipients_cc": recipients_cc,
                    "body": body,
                    "snippet": msg.get("snippet", ""),
                    "thread_id": msg.get("threadId", ""),
                    "attachments": attachments,
                }
            )

            urgency_signals = {
                "sender": sender,
                "is_direct": len(recipients_to) == 1 and not recipients_cc,
                "cc_count": len(recipients_cc),
                "thread_depth": 0,
                "has_attachments": len(attachments) > 0,
                "labels": msg.get("labelIds", []),
            }

            items.append(
                RawItem(
                    id=f"email_{msg_id}",
                    source_type="email",
                    source_label=f"Email: {subject[:80]}",
                    raw_text=raw_text,
                    urgency_signals=urgency_signals,
                    source_url=f"https://mail.google.com/mail/u/0/#all/{msg_id}",
                )
            )

        return items
