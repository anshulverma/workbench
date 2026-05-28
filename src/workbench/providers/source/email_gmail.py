import json
from datetime import datetime
from pydantic import BaseModel
from workbench.providers.source.base import SourceAdapter
from workbench.models import RawItem


class GmailAdapter(SourceAdapter):

    class ProviderConfig(BaseModel):
        google_api_script: str = ""

    def __init__(self, config: ProviderConfig):
        self.google_api_script = config.google_api_script

    def adapter_type(self) -> str:
        return "email"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self.google_api_script:
            return []
        # Gmail polling via Google API proxy — to be refined during e2e testing
        # For now, returns empty list
        return []
