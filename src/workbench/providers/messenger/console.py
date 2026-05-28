from uuid import uuid4

from pydantic import BaseModel

from workbench.providers.messenger.base import Messenger


class ConsoleMessenger(Messenger):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        pass

    async def send_card(self, card_text: str) -> str:
        msg_id = f"console-{uuid4()}"
        print(f"\n{'='*60}")
        print(card_text)
        print(f"{'='*60}")
        print("Respond via: workbench triage")
        print(f"  or: curl -X POST http://localhost:8421/api/triage/respond -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' -d '{{\"card_id\": \"...\", \"choice\": 1}}'")
        return msg_id

    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]:
        return []
