from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter
from workbench.providers.source.github import GitHubSourceAdapter


class _Minimal(SourceAdapter):
    async def poll(self, since=None):
        return []

    def adapter_type(self) -> str:
        return "minimal"


class _Monitoring(SourceAdapter):
    async def poll(self, since=None):
        return []

    def adapter_type(self) -> str:
        return "mon"

    def supports_monitoring(self) -> bool:
        return True

    def stable_id(self, raw_item: RawItem) -> str:
        return raw_item.id.split("_")[0]

    def poll_returns_complete_set(self) -> bool:
        return True


def _raw(rid: str) -> RawItem:
    return RawItem(id=rid, source_type="x", source_label="l", raw_text="{}")


def test_minimal_inherits_defaults():
    a = _Minimal()
    assert a.supports_monitoring() is False
    assert a.poll_returns_complete_set() is False
    assert a.stable_id(_raw("D123_456")) == "D123_456"


def test_monitoring_subclass_overrides():
    a = _Monitoring()
    assert a.supports_monitoring() is True
    assert a.poll_returns_complete_set() is True
    assert a.stable_id(_raw("D123_456")) == "D123"


def test_existing_github_adapter_instantiates_and_inherits_defaults():
    a = GitHubSourceAdapter(GitHubSourceAdapter.ProviderConfig())
    assert a.supports_monitoring() is False
    assert a.poll_returns_complete_set() is False
    assert a.stable_id(_raw("gh-pr-owner-1")) == "gh-pr-owner-1"
