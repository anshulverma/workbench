from abc import ABC, abstractmethod


class Messenger(ABC):
    @abstractmethod
    async def send_card(self, card_text: str) -> str: ...
    @abstractmethod
    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]: ...

    async def close(self) -> None:
        pass
