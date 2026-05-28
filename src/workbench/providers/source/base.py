from abc import ABC, abstractmethod
from datetime import datetime
from workbench.models import RawItem


class SourceAdapter(ABC):
    @abstractmethod
    async def poll(self, since: datetime | None = None) -> list[RawItem]: ...
    @abstractmethod
    def adapter_type(self) -> str: ...

    async def close(self) -> None:
        pass
