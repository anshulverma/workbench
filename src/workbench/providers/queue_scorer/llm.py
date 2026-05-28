import json
import os
import ssl

import httpx
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from workbench.providers.queue_scorer.base import QueueScorer

URGENCY_PROMPT = """Rate the urgency of processing this content on a scale of 0-100.
Higher = more urgent (needs immediate attention).
Lower = can wait (informational, low priority).

Consider these signals from the source system:
{signals}

Content (first 2000 chars):
{content}

Return only a JSON object: {{"urgency": <0-100>}}"""


class LLMQueueScorer(QueueScorer):
    class ProviderConfig(BaseModel):
        api_key: str
        base_url: str = "https://plugboard.x2p.facebook.net"
        model: str = "claude-haiku-4-5-20251001"

    def __init__(self, config: ProviderConfig):
        self.model = config.model
        user = os.environ.get("USER", "anshulverma")
        cert_path = f"/var/facebook/credentials/{user}/agent_x509/claude_code_{user}.pem"
        ca_path = "/var/facebook/rootcanal/ca.pem"
        self._http_client = None
        if os.path.exists(cert_path):
            ssl_ctx = ssl.create_default_context(cafile=ca_path)
            ssl_ctx.load_cert_chain(cert_path)
            self._http_client = httpx.AsyncClient(verify=ssl_ctx)
        self.client = AsyncAnthropic(
            api_key=config.api_key, base_url=config.base_url,
            http_client=self._http_client,
        )

    async def score_urgency(self, raw_text: str, urgency_signals: dict) -> int:
        signals_text = json.dumps(urgency_signals, indent=2) if urgency_signals else "None"
        prompt = URGENCY_PROMPT.format(signals=signals_text, content=raw_text[:2000])
        try:
            response = await self.client.messages.create(
                model=self.model, max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if "```" in text:
                text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())
            return max(0, min(100, int(data["urgency"])))
        except Exception:
            return 50

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
