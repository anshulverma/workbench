# src/workbench/providers/enrichment/github.py
from __future__ import annotations

import asyncio
import json
import logging
import time
from urllib.parse import urlparse

from pydantic import BaseModel

from workbench.models import ExtractedItem, EnrichmentBudget
from workbench.providers.enrichment.base import ContextEnricher

logger = logging.getLogger(__name__)


class GitHubEnricher(ContextEnricher):

    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        self.config = config

    async def enrich(self, item: ExtractedItem, depth: str, budget: EnrichmentBudget) -> dict:
        if item.raw_item.source_type != "github":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        start = time.monotonic()
        context = {}
        calls_made = 0

        # Extract basic info from the raw_text JSON (always available)
        try:
            raw_data = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            raw_data = {}

        author = raw_data.get("author", {})
        if isinstance(author, dict):
            context["author"] = author.get("login", "unknown")
        elif isinstance(author, str):
            context["author"] = author

        # Determine if this is a PR or issue from the source ID or URL
        source_id = item.raw_item.id
        url = raw_data.get("url", "")
        is_pr = "/pull/" in url or "gh-pr-" in source_id

        # Parse repo and number from URL
        repo, number = self._parse_url(url)
        if not repo or not number:
            repo, number = self._parse_source_id(source_id)

        if repo and number:
            try:
                if is_pr:
                    details = await self._gh_json(
                        "pr", "view", str(number), "--repo", repo,
                        "--json", "files,reviewDecision,labels,statusCheckRollup",
                    )
                    calls_made = 1
                    files = details.get("files", [])
                    context["files_changed"] = len(files)
                    review = details.get("reviewDecision", "")
                    if review:
                        context["review_status"] = review.lower()
                    labels = details.get("labels", [])
                    if labels:
                        context["labels"] = ", ".join(l.get("name", "") for l in labels)
                    checks = details.get("statusCheckRollup", [])
                    if checks:
                        conclusions = [c.get("conclusion", "") for c in checks]
                        if all(c == "SUCCESS" for c in conclusions):
                            context["ci"] = "passing"
                        elif any(c == "FAILURE" for c in conclusions):
                            context["ci"] = "failing"
                        else:
                            context["ci"] = "pending"
                else:
                    details = await self._gh_json(
                        "issue", "view", str(number), "--repo", repo,
                        "--json", "labels,assignees,comments",
                    )
                    calls_made = 1
                    labels = details.get("labels", [])
                    if labels:
                        context["labels"] = ", ".join(l.get("name", "") for l in labels)
                    assignees = details.get("assignees", [])
                    if assignees:
                        context["assignees"] = ", ".join(a.get("login", "") for a in assignees)
                    comments = details.get("comments", [])
                    context["comment_count"] = len(comments)
            except Exception as e:
                logger.warning("GitHub enrichment failed for %s: %s", source_id, e)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}

    def _parse_url(self, url: str) -> tuple[str | None, str | None]:
        try:
            parts = urlparse(url).path.strip("/").split("/")
            # owner/repo/pull/123 or owner/repo/issues/123
            if len(parts) >= 4 and parts[2] in ("pull", "issues"):
                return f"{parts[0]}/{parts[1]}", parts[3]
        except Exception:
            pass
        return None, None

    def _parse_source_id(self, source_id: str) -> tuple[str | None, str | None]:
        # gh-pr-owner/repo-123 or gh-issue-owner/repo-123
        for prefix in ("gh-pr-", "gh-issue-"):
            if source_id.startswith(prefix):
                rest = source_id[len(prefix):]
                # Last segment after the last dash is the number
                last_dash = rest.rfind("-")
                if last_dash > 0:
                    return rest[:last_dash], rest[last_dash + 1:]
        return None, None

    async def _gh_json(self, *args) -> dict:
        proc = await asyncio.create_subprocess_exec(
            "gh", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(f"gh command failed: {' '.join(args)}")
        return json.loads(stdout.decode())
