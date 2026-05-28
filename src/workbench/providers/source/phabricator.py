import subprocess
import json
from datetime import datetime
from workbench.providers.source.base import SourceAdapter
from workbench.models import RawItem


class PhabricatorAdapter(SourceAdapter):
    def adapter_type(self) -> str:
        return "diff"

    async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]:
        user_phid = config.get("user_phid", "")
        if not user_phid:
            return []

        items = []
        # Fetch diffs authored by user
        items.extend(await self._query_diffs({"authorPHIDs": [user_phid]}, since))
        # Fetch diffs where user is reviewer
        items.extend(await self._query_diffs({"reviewerPHIDs": [user_phid]}, since))
        return items

    async def _query_diffs(self, constraints: dict, since: datetime | None) -> list[RawItem]:
        if since:
            constraints["modifiedStart"] = int(since.timestamp())
        params = {"constraints": constraints, "limit": 50}
        result = self._conduit_call("differential.revision.search", params)
        if not result:
            return []
        items = []
        for rev in result.get("data", []):
            rev_id = rev["id"]
            mod_time = rev["fields"].get("dateModified", 0)
            items.append(RawItem(
                id=f"D{rev_id}_{mod_time}",
                source_type="diff",
                source_label=f"D{rev_id} — {rev['fields'].get('title', '')}",
                raw_text=json.dumps(rev["fields"]),
            ))
        return items

    def _conduit_call(self, method: str, params: dict) -> dict | None:
        try:
            result = subprocess.run(
                ["arc", "call-conduit", method],
                input=json.dumps(params),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return None
            return json.loads(result.stdout).get("response", {})
        except Exception:
            return None
