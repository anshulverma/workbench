import json
import asyncio
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from workbench.providers.llm.base import LLMProvider
from workbench.models import ExtractedItem, ItemCategory, RawItem, FilterRule, TriageCard, TriageOption, Fact

EXTRACT_PROMPT = """Extract actionable items from the following content. For each item, provide:
- summary: what needs to be done or noted
- category: one of "action_item", "meeting", "plan_seed", "informational"
- source_context: relevant surrounding context

Return a JSON array of objects with these fields. Return [] if nothing actionable.

Content type: {source_type}
Content:
{raw_text}"""

SCORE_PROMPT = """Score this item for relevance and confidence (0-100 each).

Item: {summary}
Source: {source_type}

User preferences:
{preferences}

Filter rules:
{rules}

Return JSON: {{"relevance": <0-100>, "confidence": <0-100>}}"""


class AnthropicLLM(LLMProvider):
    class ProviderConfig(BaseModel):
        api_key: str
        base_url: str = "https://api.anthropic.com"
        model: str = "claude-sonnet-4-20250514"
        http_client: Any = None

        class Config:
            arbitrary_types_allowed = True

    def __init__(self, config: ProviderConfig):
        self._http_client = config.http_client
        self.client = AsyncAnthropic(
            api_key=config.api_key, base_url=config.base_url,
            http_client=self._http_client,
        )
        self.model = config.model

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()

    async def extract(self, raw_text: str, source_type: str) -> list[ExtractedItem]:
        raw_item = RawItem(id="", source_type=source_type, source_label="", raw_text=raw_text)
        response = await self._call_with_retry(
            EXTRACT_PROMPT.format(source_type=source_type, raw_text=raw_text[:10000])
        )
        try:
            items_data = json.loads(self._extract_json(response))
            return [
                ExtractedItem(
                    summary=d["summary"],
                    category=ItemCategory(d.get("category", "action_item")),
                    source_context=d.get("source_context", ""),
                    raw_item=raw_item,
                )
                for d in items_data
            ]
        except (json.JSONDecodeError, KeyError):
            return []

    async def score_relevance(self, item: ExtractedItem, preference_facts: list[Fact], rules: list[FilterRule]) -> tuple[int, int]:
        prefs_text = "\n".join(f"- {f.content}" for f in preference_facts) if preference_facts else "No preferences yet."
        rules_text = "\n".join(f"- {r.pattern} → {r.action}" for r in rules) if rules else "No rules yet."
        response = await self._call_with_retry(
            SCORE_PROMPT.format(
                summary=item.summary,
                source_type=item.raw_item.source_type,
                preferences=prefs_text,
                rules=rules_text,
            )
        )
        try:
            scores = json.loads(self._extract_json(response))
            return int(scores["relevance"]), int(scores["confidence"])
        except (json.JSONDecodeError, KeyError):
            return 50, 30

    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard:
        summary = item.summary
        options = self._template_options(source_type)
        return TriageCard(
            card_content={"summary": summary, "source_type": source_type, "enrichment": enrichment_context},
            options=options,
        )

    def _template_options(self, source_type: str) -> list[TriageOption]:
        base = [
            TriageOption(label="Add todo (P1)", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Add todo (P2)", action="add_todo", details={"priority": "P2"}),
            TriageOption(label="Skip", action="skip"),
        ]
        if source_type == "diff":
            base.append(TriageOption(label="Never surface diffs like this", action="mute_pattern"))
        elif source_type == "email":
            base.append(TriageOption(label="Never surface emails like this", action="mute_pattern"))
        else:
            base.append(TriageOption(label="Never surface items like this", action="mute_pattern"))
        return base

    async def _call_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        for attempt in range(max_retries):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except Exception:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    def _extract_json(self, text: str) -> str:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()
