import asyncio
import json
from pydantic import BaseModel
from workbench.providers.messenger.base import Messenger


class GoogleChatMessenger(Messenger):

    class ProviderConfig(BaseModel):
        space_id: str
        google_api_script: str = "src/workbench/lib/google_api.py"

    def __init__(self, config: ProviderConfig):
        self.space_id = config.space_id
        self.script = config.google_api_script

    async def send_card(self, card_text: str) -> str:
        result = await self._run({"action": "send_message", "space_id": self.space_id, "text": card_text, "as_bot": True})
        if result.get("success"):
            return result["data"].get("name", "")
        raise RuntimeError(f"Failed to send message: {result.get('error', 'unknown')}")

    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]:
        result = await self._run({"action": "list_messages", "space_id": self.space_id})
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

    async def _run(self, params: dict) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", self.script, json.dumps(params),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return {"success": False, "error": "Timeout after 30s"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        if proc.returncode != 0:
            return {"success": False, "error": stderr.decode()}
        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}
