import json
import subprocess
from datetime import datetime
from server.providers.source.base import SourceAdapter
from server.models import RawItem


class GmailAdapter(SourceAdapter):
    def adapter_type(self) -> str:
        return "email"

    async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]:
        google_api_script = config.get("google_api_script", "")
        if not google_api_script:
            return []
        # Gmail polling via Google API proxy — to be refined during e2e testing
        # For now, returns empty list
        return []
