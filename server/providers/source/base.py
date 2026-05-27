from abc import ABC, abstractmethod
from datetime import datetime
from server.models import RawItem


class SourceAdapter(ABC):
    @abstractmethod
    async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]: ...
    @abstractmethod
    def adapter_type(self) -> str: ...
