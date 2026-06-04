from abc import ABC, abstractmethod
from pydantic import BaseModel


class Connection(ABC):
    class ProviderConfig(BaseModel):
        pass

    @abstractmethod
    async def initialize(self) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...

    @abstractmethod
    def is_healthy(self) -> bool:
        ...
