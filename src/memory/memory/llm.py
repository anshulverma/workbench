from __future__ import annotations

import importlib
import logging
from typing import Any

from memory.config import LLMConfig

logger = logging.getLogger(__name__)


class DefaultLLMClient:
    """Wraps Graphiti's AnthropicClient. Default LLM client for OSS deployments."""

    def __init__(self, config: LLMConfig):
        from graphiti_core.llm_client.anthropic_client import AnthropicClient
        from graphiti_core.llm_client.config import LLMConfig as GraphitiLLMConfig

        graphiti_config = GraphitiLLMConfig(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
        )
        self._client = AnthropicClient(config=graphiti_config)

    @property
    def client(self) -> Any:
        return self._client


def create_llm_client(config: LLMConfig) -> Any:
    class_path = config.client_class
    module_path, class_name = class_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ImportError(
            f"Cannot import LLM client '{class_path}': {e}. "
            f"Check that the package is installed."
        ) from e
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"Class '{class_name}' not found in module '{module_path}'")
    instance = cls(config)
    return instance.client if hasattr(instance, "client") else instance
