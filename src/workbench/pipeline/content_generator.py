from __future__ import annotations

from abc import ABC, abstractmethod

from workbench.domain import ChangeContext, ExtractedItem


class CardContentGenerator(ABC):
    @abstractmethod
    async def generate(
        self,
        llm,
        item: ExtractedItem,
        enrichment_context: dict,
        *,
        memory_context: dict | None = None,
        change_context: ChangeContext | None = None,
    ) -> dict:
        """Return a card_content envelope dict.

        Envelope keys:
          content_schema: discriminator (e.g. "diff.v1") — present only when sections valid.
          sections: serialized typed content (omitted on refusal/parse-fail).
          card_body / summary: legacy plain-fallback fields (always present).
        change_context, when present, makes the copy/options change-aware (ADR 0030,0032).
        """


def build_content_generators(presentation_config) -> dict:
    """Build {source_type: CardContentGenerator} from presentation.providers.

    Each entry may carry a `content_generator` class string; entries without one
    fall through to the LLM default in generate_card."""
    from workbench.providers.registry import create_provider

    generators: dict = {}
    for entry in presentation_config.providers:
        gen_class = entry.get("content_generator")
        if not gen_class:
            continue
        source_type = entry["source_type"]
        generators[source_type] = create_provider({"class": gen_class})
    return generators
