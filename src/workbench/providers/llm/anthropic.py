import json
import asyncio
import logging
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from workbench.providers.llm.base import LLMProvider
from workbench.models import ExtractedItem, ItemCategory, RawItem, FilterRule, TriageCard, TriageOption, Fact, InterpretedResponse, SystemAction, UserTodo

logger = logging.getLogger(__name__)

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

    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str, *, memory_context: dict | None = None) -> TriageCard:
        summary = item.summary
        options = self._template_options(source_type)

        # If memory_context is available, use LLM to generate a richer card body
        if memory_context:
            card_body = await self._generate_card_body(
                summary, source_type, enrichment_context, memory_context
            )
        else:
            card_body = summary

        return TriageCard(
            card_content={
                "card_body": card_body,
                "summary": summary,
                "source_type": source_type,
                "enrichment": enrichment_context,
            },
            options=options,
        )

    async def _generate_card_body(
        self, summary: str, source_type: str,
        enrichment_context: dict, memory_context: dict,
    ) -> str:
        entity_lines = []
        for key, facts in memory_context.get("entity_facts", {}).items():
            fact_str = ", ".join(f"{k}: {v}" for k, v in facts.items())
            entity_lines.append(f"  {key}: {fact_str}")

        pref_lines = [
            f"  - {p}" for p in memory_context.get("preference_facts", [])
        ]

        prompt = f"""Generate a concise triage card body (1-3 sentences) for this item.
Include relevant context about people, teams, and user preferences.

Item: {summary}
Source type: {source_type}
Enrichment context: {enrichment_context}

Known entities:
{chr(10).join(entity_lines) if entity_lines else '  (none)'}

User preference history:
{chr(10).join(pref_lines) if pref_lines else '  (none)'}

Write a brief, informative description that helps the user decide what to do.
Return ONLY the card body text, no JSON wrapping."""

        try:
            return await self._call_with_retry(prompt)
        except Exception:
            return summary

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

    async def interpret_triage_response(self, card: TriageCard, raw_text: str) -> InterpretedResponse:
        """Interpret free-text triage response using Anthropic tool use."""
        summary = card.card_content.get("summary", card.card_content.get("card_body", ""))
        source_type = card.card_content.get("source_type", "unknown")
        options_text = "\n".join(
            f"  {i}. {o.label} (action={o.action})"
            for i, o in enumerate(card.options, 1)
        )

        # FIX 5: Full Anthropic tool use prompt with constrained enums
        tools = [
            {
                "name": "interpret_response",
                "description": "Parse a user's free-text triage response into structured actions.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "system_actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "action": {
                                        "type": "string",
                                        "enum": [
                                            "add_todo", "skip", "mute_pattern",
                                            "defer",
                                        ],
                                    },
                                    "details": {
                                        "type": "object",
                                        "properties": {
                                            "priority": {
                                                "type": "string",
                                                "enum": ["P0", "P1", "P2", "P3"],
                                            },
                                            "hours": {"type": "integer"},
                                        },
                                    },
                                },
                                "required": ["action"],
                            },
                        },
                        "user_todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "summary": {"type": "string"},
                                    "action_category": {
                                        "type": "string",
                                        "enum": [
                                            "delegation", "communication",
                                            "scheduling", "review",
                                            "creation", "update",
                                        ],
                                    },
                                },
                                "required": ["summary", "action_category"],
                            },
                        },
                        "explanation": {"type": "string"},
                    },
                    "required": ["system_actions", "explanation"],
                },
            }
        ]

        messages = [
            {
                "role": "user",
                "content": (
                    f"The user is triaging this item:\n"
                    f"  Summary: {summary}\n"
                    f"  Source: {source_type}\n"
                    f"  Options presented:\n{options_text}\n\n"
                    f"Instead of choosing a number, the user replied:\n"
                    f'  "{raw_text}"\n\n'
                    f"Parse this into system actions and any user todos. "
                    f"Use the interpret_response tool."
                ),
            }
        ]

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                tools=tools,
                tool_choice={"type": "tool", "name": "interpret_response"},
                messages=messages,
            )

            # Extract tool use result
            for block in response.content:
                if block.type == "tool_use" and block.name == "interpret_response":
                    result = block.input
                    return InterpretedResponse(
                        system_actions=[
                            SystemAction(
                                action=a["action"],
                                details=a.get("details", {}),
                            )
                            for a in result.get("system_actions", [])
                        ],
                        user_todos=[
                            UserTodo(
                                summary=t["summary"],
                                action_category=t["action_category"],
                            )
                            for t in result.get("user_todos", [])
                        ],
                        explanation=result.get("explanation", ""),
                    )

            # Fallback if no tool use block found
            return InterpretedResponse(
                system_actions=[
                    SystemAction(action="add_todo", details={"priority": "P2"})
                ],
                explanation=f"Could not parse response, defaulting to P2 todo: {raw_text}",
            )
        except Exception as e:
            logger.warning("interpret_triage_response failed: %s", e)
            return InterpretedResponse(
                system_actions=[
                    SystemAction(action="add_todo", details={"priority": "P2"})
                ],
                explanation=f"LLM interpretation failed, defaulting to P2 todo: {raw_text}",
            )

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
