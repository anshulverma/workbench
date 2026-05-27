# server/providers/llm/claude.py
import json
import asyncio
import os
import ssl
import httpx
from anthropic import AsyncAnthropic
from server.providers.llm.base import LLMProvider
from server.models import ExtractedItem, ItemCategory, RawItem, FilterRule, TriageCard, TriageOption, Fact

EXTRACT_PROMPT = """Extract actionable items from the following content. For each item, provide:
- summary: what needs to be done or noted
- category: one of "action_item", "meeting", "informational"
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

class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str = "claude-sonnet-4-20250514"):
        user = os.environ.get("USER", "anshulverma")
        cert_path = f"/var/facebook/credentials/{user}/agent_x509/claude_code_{user}.pem"
        ca_path = "/var/facebook/rootcanal/ca.pem"
        http_client = None
        if os.path.exists(cert_path):
            ssl_ctx = ssl.create_default_context(cafile=ca_path)
            ssl_ctx.load_cert_chain(cert_path)
            http_client = httpx.AsyncClient(verify=ssl_ctx)
        self.client = AsyncAnthropic(api_key=api_key, base_url=base_url, http_client=http_client)
        self.model = model

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
            return 50, 30  # uncertain defaults

    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard:
        # Template-based options per source type — LLM generates summary only
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
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    def _extract_json(self, text: str) -> str:
        # Find JSON in the response (may be wrapped in markdown code blocks)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()
