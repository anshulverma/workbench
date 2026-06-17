# GitHub adapter source-link plumbing: poll() stamps each RawItem with a
# human-readable source_ref (#<number>) and the canonical source_url (the `url`
# the gh CLI already returns), so triage cards can link back to the PR/issue.

import pytest
from unittest.mock import AsyncMock, patch

from workbench.providers.source.github import GitHubSourceAdapter


def _adapter():
    return GitHubSourceAdapter(GitHubSourceAdapter.ProviderConfig(repos=["o/r"]))


@pytest.mark.asyncio
async def test_poll_sets_source_ref_and_url_for_prs_and_issues():
    adapter = _adapter()

    async def fake_gh(*args):
        if args[0] == "pr":
            return [
                {"number": 42, "title": "Add auth", "url": "https://gh/o/r/pull/42"}
            ]
        return [{"number": 7, "title": "Bug", "url": "https://gh/o/r/issues/7"}]

    with patch.object(adapter, "_gh_json", AsyncMock(side_effect=fake_gh)):
        items = await adapter.poll()

    by_ref = {i.source_ref: i for i in items}
    assert by_ref["#42"].source_url == "https://gh/o/r/pull/42"
    assert by_ref["#7"].source_url == "https://gh/o/r/issues/7"
