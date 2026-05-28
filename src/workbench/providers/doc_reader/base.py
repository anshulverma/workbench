from abc import ABC, abstractmethod


class DocReader(ABC):
    @abstractmethod
    def can_handle(self, url: str) -> bool: ...
    @abstractmethod
    async def read(self, url: str) -> str: ...
