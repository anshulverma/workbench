# tests/test_github_enricher.py
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from workbench.providers.enrichment.github import GitHubEnricher
from workbench.models import EntityKnowledge, ExtractedItem, ItemCategory, RawItem, EnrichmentBudget


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


@pytest.fixture
def mock_memory():
    m = AsyncMock()
    m.query_entity = AsyncMock(return_value=None)
    m.record_entity = AsyncMock()
    return m


@pytest.mark.asyncio
async def test_enrich_queries_memory_for_author(enricher, mock_memory):
    item = _make_item()
    mock_memory.query_entity.return_value = EntityKnowledge(
        entity_type="person", entity_id="alice", facts={"team": "infra", "role": "tech lead"}
    )
    gh_view_output = {
        "files": [{"path": "auth.py"}],
        "reviewDecision": "",
        "labels": [],
        "statusCheckRollup": [],
    }

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, return_value=gh_view_output):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget(), memory=mock_memory)

    ctx = result["context"]
    assert ctx["author_team"] == "infra"
    assert ctx["author_role"] == "tech lead"
    mock_memory.query_entity.assert_awaited_once_with("person", "alice")


@pytest.mark.asyncio
async def test_enrich_records_entities_in_memory(enricher, mock_memory):
    item = _make_item()
    gh_view_output = {
        "files": [{"path": "auth.py"}],
        "reviewDecision": "",
        "labels": [{"name": "security"}],
        "statusCheckRollup": [],
    }

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, return_value=gh_view_output):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget(), memory=mock_memory)

    # Should record person entity for the author
    calls = mock_memory.record_entity.await_args_list
    person_calls = [c for c in calls if c.args[0] == "person"]
    repo_calls = [c for c in calls if c.args[0] == "repo"]

    assert len(person_calls) == 1
    assert person_calls[0].args[1] == "alice"
    assert person_calls[0].args[2]["login"] == "alice"

    assert len(repo_calls) == 1
    assert repo_calls[0].args[1] == "owner/repo"
    assert repo_calls[0].args[2]["name"] == "owner/repo"
    assert repo_calls[0].args[2]["labels"] == "security"


@pytest.mark.asyncio
async def test_enrich_works_without_memory(enricher):
    """Verify existing behavior is preserved when memory=None."""
    item = _make_item()
    gh_view_output = {
        "files": [{"path": "auth.py"}],
        "reviewDecision": "APPROVED",
        "labels": [],
        "statusCheckRollup": [],
    }

    with patch.object(enricher, "_gh_json", new_callable=AsyncMock, return_value=gh_view_output):
        result = await enricher.enrich(item, "shallow", EnrichmentBudget())

    ctx = result["context"]
    assert ctx["author"] == "alice"
    assert ctx["files_changed"] == 1
    assert result["calls_made"] == 1


def test_provider_config():
    config = GitHubEnricher.ProviderConfig()
    assert config is not None
