import asyncio
import json
from datetime import datetime

from pydantic import BaseModel

from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter


class GitHubSourceAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        repos: list[str] = []

    def __init__(self, config: ProviderConfig):
        self.repos = config.repos

    def adapter_type(self) -> str:
        return "github"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        items = []
        for repo in self.repos:
            prs = await self._gh_json("pr", "list", "--repo", repo,
                                       "--json", "number,title,updatedAt,url,author")
            for pr in prs:
                items.append(RawItem(
                    id=f"gh-pr-{repo}-{pr['number']}",
                    source_type="github",
                    source_label=f"PR #{pr['number']} — {pr['title']}",
                    raw_text=json.dumps(pr),
                    urgency_signals={"type": "pull_request"},
                ))

            issues = await self._gh_json("issue", "list", "--repo", repo,
                                          "--json", "number,title,updatedAt,url,author")
            for issue in issues:
                items.append(RawItem(
                    id=f"gh-issue-{repo}-{issue['number']}",
                    source_type="github",
                    source_label=f"Issue #{issue['number']} — {issue['title']}",
                    raw_text=json.dumps(issue),
                    urgency_signals={"type": "issue"},
                ))
        return items

    async def _gh_json(self, *args) -> list[dict]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                return []
            return json.loads(stdout.decode())
        except Exception:
            return []
