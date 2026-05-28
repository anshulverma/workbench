from abc import ABC, abstractmethod
from typing import Any


class QueueScorer(ABC):
    @abstractmethod
    async def score_urgency(self, raw_text: str, urgency_signals: dict[str, Any]) -> int:
        ...

    async def close(self) -> None:
        pass
