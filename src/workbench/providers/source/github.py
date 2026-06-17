import asyncio
import json
import logging
from datetime import datetime

from pydantic import BaseModel

from workbench.domain import RawItem
from workbench.providers.source.base import SourceAdapter

logger = logging.getLogger(__name__)


class GitHubSourceAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        repos: list[str] = []

    def __init__(self, config: ProviderConfig):
        self.repos = config.repos

    def adapter_type(self) -> str:
        return "github"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        items = []
        search_filter = []
        if since:
            search_filter = [
                "--search",
                f"updated:>{since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            ]

        for repo in self.repos:
            prs = await self._gh_json(
                "pr",
                "list",
                "--repo",
                repo,
                *search_filter,
                "--json",
                "number,title,updatedAt,url,author",
            )
            for pr in prs:
                items.append(
                    RawItem(
                        id=f"gh-pr-{repo}-{pr['number']}",
                        source_type="github",
                        source_label=f"PR #{pr['number']} — {pr['title']}",
                        raw_text=json.dumps(pr),
                        urgency_signals={"type": "pull_request"},
                        source_ref=f"#{pr['number']}",
                        source_url=pr.get("url"),
                    )
                )

            issues = await self._gh_json(
                "issue",
                "list",
                "--repo",
                repo,
                *search_filter,
                "--json",
                "number,title,updatedAt,url,author",
            )
            for issue in issues:
                items.append(
                    RawItem(
                        id=f"gh-issue-{repo}-{issue['number']}",
                        source_type="github",
                        source_label=f"Issue #{issue['number']} — {issue['title']}",
                        raw_text=json.dumps(issue),
                        urgency_signals={"type": "issue"},
                        source_ref=f"#{issue['number']}",
                        source_url=issue.get("url"),
                    )
                )
        return items

    async def _gh_json(self, *args) -> list[dict]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                logger.warning(
                    "gh %s failed (exit %s): %s",
                    " ".join(args),
                    proc.returncode,
                    stderr.decode(errors="replace").strip(),
                )
                return []
            return json.loads(stdout.decode())
        except Exception:
            logger.warning("gh %s invocation failed", " ".join(args))
            return []
