from uuid import uuid4

from pydantic import BaseModel

from workbench.providers.messenger.base import Messenger


class ConsoleMessenger(Messenger):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        pass

    async def send_card(self, card) -> str:
        from workbench.domain import CardMessage

        card_text = (
            self.render_to_text(card) if isinstance(card, CardMessage) else str(card)
        )
        msg_id = f"console-{uuid4()}"
        print(f"\n{'='*60}")
        print(card_text)
        print(f"{'='*60}")
        print("Respond via the web UI Triage page, or: make triage")
        print(
            f"  or: curl -X POST http://localhost:8421/api/triage/respond -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' -d '{{\"card_id\": \"...\", \"choice\": 1}}'"
        )
        return msg_id

    async def update_message(self, message_id: str, card) -> bool:
        from workbench.domain import CardMessage

        card_text = (
            self.render_to_text(card) if isinstance(card, CardMessage) else str(card)
        )
        print(f"[UPDATE {message_id}]")
        print(card_text)
        return True

    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]:
        return []
