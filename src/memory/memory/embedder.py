from __future__ import annotations

import importlib
import logging
from typing import Any

from memory.config import EmbedderConfig

logger = logging.getLogger(__name__)


class OpenAIEmbedderWrapper:
    """Wraps Graphiti's OpenAIEmbedder. Default for OSS deployments with OpenAI API key."""

    def __init__(self, config: EmbedderConfig):
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

        embedder_config = OpenAIEmbedderConfig(
            embedding_model=config.model,
            api_key=config.api_key,
            embedding_dim=config.embedding_dim,
        )
        self._client = OpenAIEmbedder(embedder_config)

    @property
    def client(self):
        return self._client


class LocalEmbedder:
    """Uses sentence-transformers for local embedding. No API key needed.

    Install with: pip install memory-service[local-embedder]
    Model is downloaded from Hugging Face on first use (~80MB for all-MiniLM-L6-v2).
    """

    def __init__(self, config: EmbedderConfig):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for LocalEmbedder. "
                "Install with: pip install memory-service[local-embedder]"
            ) from None

        from graphiti_core.embedder.client import EmbedderClient

        self._model_name = config.model or "all-MiniLM-L6-v2"
        self._model = SentenceTransformer(self._model_name)
        self._dim = config.embedding_dim

        embedder_self = self

        class _Client(EmbedderClient):
            async def create(self, input_data):
                if isinstance(input_data, str):
                    input_data = [input_data]
                embeddings = embedder_self._model.encode(list(input_data), normalize_embeddings=True)
                return embeddings[0].tolist()[:embedder_self._dim]

            async def create_batch(self, input_data_list):
                embeddings = embedder_self._model.encode(input_data_list, normalize_embeddings=True)
                return [e.tolist()[:embedder_self._dim] for e in embeddings]

        self._client = _Client()

    @property
    def client(self):
        return self._client


def create_embedder(config: EmbedderConfig) -> Any:
    class_path = config.embedder_class
    module_path, class_name = class_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ImportError(
            f"Cannot import embedder '{class_path}': {e}. "
            f"Check that the package is installed."
        ) from e
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"Class '{class_name}' not found in module '{module_path}'")
    instance = cls(config)
    return instance.client if hasattr(instance, "client") else instance


def create_cross_encoder(config: EmbedderConfig) -> Any:
    if config.cross_encoder_class:
        module_path, class_name = config.cross_encoder_class.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()
    if "Local" in config.embedder_class:
        from graphiti_core.cross_encoder.bge_reranker_client import BGERerankerClient
        return BGERerankerClient()
    else:
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        return OpenAIRerankerClient()
