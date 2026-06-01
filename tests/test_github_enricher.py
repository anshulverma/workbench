# tests/test_github_enricher.py
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from workbench.providers.enrichment.github import GitHubEnricher
from workbench.models import ExtractedItem, ItemCategory, RawItem, EnrichmentBudget


def _make_item(source_type="github", raw_text=None, source_id="gh-pr-owner/repo-42"):
    if raw_text is None:
        raw_text = json.dumps({
            "number": 42,
            "title": "Fix auth flow",
            "url": "https://github.com/owner/repo/pull/42",
            "author": {"login": "alice"},
        })
    return ExtractedItem(
        summary="Fix auth flow",
        category=ItemCategory.ACTION_ITEM,
        source_context="",
        raw_item=RawItem(
            id=source_id,
            source_type=source_type,
            source_label="PR #42",
            raw_text=raw_text,
        ),
    )


@pytest.fixture
def enricher():
    return GitHubEnricher()


@pytest.mark.asyncio
async def test_enrich_github_pr(enricher):
    item = _make_item()
    gh_view_output = json.dumps({
        "files": [{"path": "auth.py"}, {"path": "tests/test_auth.py"}],
        "reviewDecision": "CHANGES_REQUESTED",
        "labels": [{"name": "security"}, {"name": "auth"}],
        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
    })

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, return_value=json.loads(gh_view_output)):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget())

    ctx = result["context"]
    assert ctx["author"] == "alice"
    assert ctx["files_changed"] == 2
    assert ctx["review_status"] == "changes_requested"
    assert "security" in ctx["labels"]
    assert result["calls_made"] == 1


@pytest.mark.asyncio
async def test_enrich_github_issue(enricher):
    item = _make_item(
        source_id="gh-issue-owner/repo-10",
        raw_text=json.dumps({
            "number": 10,
            "title": "Bug report",
            "url": "https://github.com/owner/repo/issues/10",
            "author": {"login": "bob"},
        }),
    )
    gh_view_output = {
        "labels": [{"name": "bug"}],
        "assignees": [{"login": "carol"}],
        "comments": [{"body": "looking into it"}],
    }

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, return_value=gh_view_output):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget())

    ctx = result["context"]
    assert ctx["author"] == "bob"
    assert ctx["assignees"] == "carol"
    assert ctx["comment_count"] == 1


@pytest.mark.asyncio
async def test_enrich_non_github_returns_stub(enricher):
    item = _make_item(source_type="email", raw_text="raw email body")
    result = await enricher.enrich(item, "shallow", EnrichmentBudget())
    assert result["calls_made"] == 0
    assert result["context"] == {}


@pytest.mark.asyncio
async def test_enrich_handles_gh_cli_failure(enricher):
    item = _make_item()

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, side_effect=Exception("gh not found")):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget())

    assert result["calls_made"] == 0
    ctx = result["context"]
    # Should still have author from raw_text even if gh view fails
    assert ctx["author"] == "alice"


def test_provider_config():
    config = GitHubEnricher.ProviderConfig()
    assert config is not None
