from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ProviderConfig(BaseModel):
    pass


def create_provider(
    section: dict[str, Any],
    connections: dict[str, Any] | None = None,
    state_store: Any | None = None,
) -> Any:
    section = dict(section)
    class_path = section.pop("class")
    connection_name = section.pop("connection", None)
    module_path, class_name = class_path.rsplit(".", 1)

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ImportError(
            f"Cannot import provider '{class_path}': {e}. "
            f"Check that the package is installed."
        ) from e

    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"Class '{class_name}' not found in module '{module_path}'")

    resolved_connection = None
    if connection_name and connections is not None:
        resolved_connection = connections.get(connection_name)
        if resolved_connection is None:
            raise ValueError(f"Connection '{connection_name}' not found in connections config")

    sig = inspect.signature(cls.__init__)
    kwargs: dict[str, Any] = {}
    if "connection" in sig.parameters and resolved_connection is not None:
        kwargs["connection"] = resolved_connection
    if "state_store" in sig.parameters and state_store is not None:
        kwargs["state_store"] = state_store

    if hasattr(cls, "ProviderConfig"):
        typed_config = cls.ProviderConfig(**section)
        return cls(typed_config, **kwargs)
    else:
        if section:
            kwargs.update(section)
        return cls(**kwargs) if kwargs else cls()


def create_providers_from_list(
    sections: list[dict[str, Any]],
    connections: dict[str, Any] | None = None,
    state_store: Any | None = None,
) -> list[Any]:
    return [create_provider(s, connections=connections, state_store=state_store) for s in sections]


def create_composite_enricher(
    config,
    connections: dict[str, Any] | None = None,
    metrics: Any | None = None,
):
    from workbench.providers.enrichment.composite import CompositeEnricher
    from workbench.models import EnrichmentBudget

    enrichers = {}
    budgets = {}
    for entry in config.providers:
        entry = dict(entry)
        source_types = entry.pop("source_types", [])
        budget_dict = entry.pop("budget", None)
        provider = create_provider(entry, connections=connections)
        for st in source_types:
            enrichers[st] = provider
        if budget_dict:
            budget = EnrichmentBudget(**budget_dict)
            for st in source_types:
                budgets[st] = budget

    default = create_provider(dict(config.default), connections=connections) if config.default else None
    return CompositeEnricher(enrichers, default=default, budgets=budgets)


async def close_provider(provider: Any) -> None:
    if hasattr(provider, "close"):
        try:
            await provider.close()
        except Exception as e:
            logger.warning(f"Error closing provider {type(provider).__name__}: {e}")
