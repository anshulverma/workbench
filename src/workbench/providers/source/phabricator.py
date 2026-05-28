import asyncio
import json
from datetime import datetime
from pydantic import BaseModel
from workbench.providers.source.base import SourceAdapter
from workbench.models import RawItem


class PhabricatorAdapter(SourceAdapter):

    class ProviderConfig(BaseModel):
        user_phid: str = ""

    def __init__(self, config: ProviderConfig):
        self.user_phid = config.user_phid

    def adapter_type(self) -> str:
        return "diff"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self.user_phid:
            return []

        items = []
        # Fetch diffs authored by user
        items.extend(await self._query_diffs({"authorPHIDs": [self.user_phid]}, since))
        # Fetch diffs where user is reviewer
        items.extend(await self._query_diffs({"reviewerPHIDs": [self.user_phid]}, since))
        return items

    async def _query_diffs(self, constraints: dict, since: datetime | None) -> list[RawItem]:
        if since:
            constraints["modifiedStart"] = int(since.timestamp())
        params = {"constraints": constraints, "limit": 50}
        result = await self._conduit_call("differential.revision.search", params)
        if not result:
            return []
        items = []
        for rev in result.get("data", []):
            rev_id = rev["id"]
            fields = rev.get("fields", {})
            mod_time = fields.get("dateModified", 0)
            # Extract urgency signals from diff status
            urgency_signals = {}
            status = fields.get("status", {})
            status_value = status.get("value", "") if isinstance(status, dict) else str(status)
            if status_value:
                urgency_signals["status"] = status_value
            items.append(RawItem(
                id=f"D{rev_id}_{mod_time}",
                source_type="diff",
                source_label=f"D{rev_id} — {fields.get('title', '')}",
                raw_text=json.dumps(fields),
                urgency_signals=urgency_signals,
            ))
        return items

    async def _conduit_call(self, method: str, params: dict) -> dict | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "arc", "call-conduit", method,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=json.dumps(params).encode()),
                timeout=30,
            )
            if proc.returncode != 0:
                return None
            return json.loads(stdout.decode()).get("response", {})
        except Exception:
            return None
