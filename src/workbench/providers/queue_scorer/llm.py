import json
import logging
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from workbench.providers._plugboard import record_plugboard_call
from workbench.providers.queue_scorer.base import QueueScorer

logger = logging.getLogger(__name__)

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
        base_url: str = "https://api.anthropic.com"
        model: str = "claude-haiku-4-5-20251001"
        http_client: Any = None
        on_plugboard_call: Any = None

        class Config:
            arbitrary_types_allowed = True

    def __init__(self, config: ProviderConfig):
        self.model = config.model
        self._http_client = config.http_client
        self.client = AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
            http_client=self._http_client,
        )
        self._sink = config.on_plugboard_call

    async def score_urgency(self, raw_text: str, urgency_signals: dict) -> int:
        signals_text = (
            json.dumps(urgency_signals, indent=2) if urgency_signals else "None"
        )
        prompt = URGENCY_PROMPT.format(signals=signals_text, content=raw_text[:2000])
        try:
            response = await record_plugboard_call(
                client="queue_scorer",
                model=self.model,
                sink=self._sink,
                do_call=lambda: self.client.messages.create(
                    model=self.model,
                    max_tokens=100,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            text = response.content[0].text.strip()
            if "```" in text:
                text = (
                    text.split("```json")[-1].split("```")[0]
                    if "```json" in text
                    else text.split("```")[1].split("```")[0]
                )
            data = json.loads(text.strip())
            return max(0, min(100, int(data["urgency"])))
        except Exception:
            logger.warning("Urgency scoring failed, defaulting to 50")
            return 50

    async def score_urgency_many(
        self, items: list[tuple[str, dict]], *, max_batch_size: int = 20
    ) -> list[int]:
        """Score N items' urgency in batched calls (one call per chunk).

        Items whose result is missing/malformed fall back to per-item
        score_urgency. The output cap scales with batch size (the per-item
        max_tokens=100 cannot hold N results). See ADR 0048 / spec 3.2.
        """
        results: list[int | None] = [None] * len(items)
        for start in range(0, len(items), max_batch_size):
            chunk = items[start : start + max_batch_size]
            await self._score_urgency_chunk(chunk, results, start)
        return [r if r is not None else 50 for r in results]

    async def _score_urgency_chunk(self, chunk, results, offset) -> None:
        payload = [
            {
                "index": i,
                "signals": signals or {},
                "content": (raw_text or "")[:2000],
            }
            for i, (raw_text, signals) in enumerate(chunk)
        ]
        prompt = (
            "Rate the urgency (0-100) of processing each item. Higher = more "
            "urgent. Return ONLY a JSON array, one object per input item, "
            'echoing its integer "index": '
            '[{"index": <int>, "urgency": <0-100>}].\n\n'
            f"Items:\n{json.dumps(payload, indent=2)}"
        )
        parsed: dict[int, int] = {}
        try:
            response = await record_plugboard_call(
                client="queue_scorer",
                model=self.model,
                sink=self._sink,
                item_count=len(chunk),
                do_call=lambda: self.client.messages.create(
                    model=self.model,
                    max_tokens=min(4096, 40 * len(chunk) + 100),
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            text = response.content[0].text.strip()
            if "```" in text:
                text = (
                    text.split("```json")[-1].split("```")[0]
                    if "```json" in text
                    else text.split("```")[1].split("```")[0]
                )
            for d in json.loads(text.strip()):
                parsed[int(d["index"])] = max(0, min(100, int(d["urgency"])))
        except Exception:
            logger.warning("Batch urgency parse failed; falling back per-item")

        for i, (raw_text, signals) in enumerate(chunk):
            if i in parsed:
                results[offset + i] = parsed[i]
            else:
                results[offset + i] = await self.score_urgency(raw_text, signals)

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
