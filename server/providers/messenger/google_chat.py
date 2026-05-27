import json
import subprocess
from server.providers.messenger.base import Messenger


class GoogleChatMessenger(Messenger):
    def __init__(self, space_id: str, google_api_script: str):
        self.space_id = space_id
        self.script = google_api_script

    async def send_card(self, card_text: str) -> str:
        result = self._run({"action": "send_message", "space_id": self.space_id, "text": card_text, "as_bot": True})
        if result.get("success"):
            return result["data"].get("name", "")
        raise RuntimeError(f"Failed to send message: {result.get('error', 'unknown')}")

    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]:
        result = self._run({"action": "list_messages", "space_id": self.space_id})
        if not result.get("success"):
            return []
        messages = result["data"].get("messages", [])
        human_msgs = [m for m in messages if m.get("sender_type") == "HUMAN"]
        if since_message_id:
            # Return only messages after the given message
            found = False
            filtered = []
            for m in human_msgs:
                if found:
                    filtered.append(m)
                if m.get("name") == since_message_id:
                    found = True
            return filtered
        return human_msgs

    def _run(self, params: dict) -> dict:
        result = subprocess.run(
            ["python3", self.script, json.dumps(params)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}
