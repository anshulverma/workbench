from __future__ import annotations

import importlib
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ProviderConfig(BaseModel):
    pass


def create_provider(section: dict[str, Any]) -> Any:
    section = dict(section)
    class_path = section.pop("class")
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

    if hasattr(cls, "ProviderConfig"):
        typed_config = cls.ProviderConfig(**section)
        return cls(typed_config)
    else:
        return cls(**section) if section else cls()


def create_providers_from_list(sections: list[dict[str, Any]]) -> list[Any]:
    return [create_provider(s) for s in sections]


async def close_provider(provider: Any) -> None:
    if hasattr(provider, "close"):
        try:
            await provider.close()
        except Exception as e:
            logger.warning(f"Error closing provider {type(provider).__name__}: {e}")
