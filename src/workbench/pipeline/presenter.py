from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from pydantic import ValidationError

from workbench.domain import CardMessage, CardSection, ExtractedItem, TriageCard
from workbench.pipeline.triage import format_card_for_chat

logger = logging.getLogger(__name__)


class CardPresenter(ABC):
    @abstractmethod
    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage: ...


class PlainCardPresenter(CardPresenter):
    """Universal fallback. Wraps legacy format_card_for_chat output."""

    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage:
        body = format_card_for_chat(card, position=1, total=1)
        return CardMessage(
            header=card.card_content.get("summary", "Item to triage"),
            sections=[CardSection(title="", body=body)],
            options=list(card.options),
        )


class CompositeCardPresenter(CardPresenter):
    def __init__(
        self, by_source_type: dict[str, CardPresenter], default: CardPresenter
    ):
        self._by_source_type = by_source_type
        self._default = default

    def render(self, card: TriageCard, item: ExtractedItem) -> CardMessage:
        source_type = item.raw_item.source_type
        delegate = self._by_source_type.get(source_type, self._default)
        if delegate is self._default:
            if source_type not in self._by_source_type:
                logger.info(
                    "presenter_fallback source_type=%s item_id=%s reason=no_delegate",
                    source_type,
                    item.raw_item.id,
                )
            return self._default.render(card, item)
        try:
            return delegate.render(card, item)
        except ValidationError as exc:
            logger.warning(
                "presenter_content_invalid source_type=%s presenter=%s item_id=%s exc=%s",
                source_type,
                type(delegate).__name__,
                item.raw_item.id,
                exc,
            )
            return self._default.render(card, item)
        except Exception as exc:
            logger.warning(
                "presenter_failure source_type=%s presenter=%s item_id=%s exc=%s",
                source_type,
                type(delegate).__name__,
                item.raw_item.id,
                exc,
            )
            return self._default.render(card, item)


def build_composite_presenter(presentation_config) -> "CompositeCardPresenter":
    """Build a CompositeCardPresenter from the presentation.providers list.

    Each entry: {source_type, class, config?}. Disabled (config.enabled is False)
    entries are skipped. Unimportable class strings raise at startup (hard error).
    """
    from workbench.providers.registry import create_provider

    by_source_type: dict[str, CardPresenter] = {}
    for entry in presentation_config.providers:
        entry = dict(entry)
        source_type = entry.pop("source_type")
        provider_config = entry.pop("config", {}) or {}
        if provider_config.get("enabled", True) is False:
            continue
        section = {"class": entry["class"], **provider_config}
        by_source_type[source_type] = create_provider(section)
    return CompositeCardPresenter(by_source_type, default=PlainCardPresenter())
