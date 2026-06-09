from abc import ABC, abstractmethod

from workbench.domain import CardMessage


class Messenger(ABC):
    @abstractmethod
    async def send_card(self, card: "CardMessage | str") -> str: ...
    @abstractmethod
    async def poll_responses(
        self, since_message_id: str | None = None
    ) -> list[dict]: ...

    def render_to_text(self, card: CardMessage) -> str:
        """Default flatten for console / non-rich transports."""
        lines = [f"*{card.header}*", ""]
        for section in card.sections:
            if section.title:
                lines.append(f"*{section.title}*")
            lines.append(section.body)
            lines.append("")
        for link in card.links:
            lines.append(f"{link.label}: {link.url}")
        if card.links:
            lines.append("")
        for i, opt in enumerate(card.options, 1):
            lines.append(f"{i}. {opt.label}")
        if card.options:
            lines.append("")
            lines.append("_Or just reply with what you'd like to do._")
        return "\n".join(lines)

    async def update_message(self, message_id: str, card: "CardMessage | str") -> bool:
        """Update an existing message in-place. Returns True on success.
        Default returns False (update not supported). Messengers that support
        in-place editing override this; on False the caller falls back to
        send_card and re-persists the new bot_message_id (ADR 0031)."""
        return False

    async def close(self) -> None:
        pass
