from abc import ABC, abstractmethod
from datetime import datetime
from workbench.models import RawItem


class SourceAdapter(ABC):
    @abstractmethod
    async def poll(self, since: datetime | None = None) -> list[RawItem]: ...
    @abstractmethod
    def adapter_type(self) -> str: ...

    def supports_monitoring(self) -> bool:
        """Whether this source produces mutable entities (diffs, tasks, PRs)
        that should be re-checked after initial triage. Default False;
        override to True in monitoring-capable adapters."""
        return False

    def stable_id(self, raw_item: RawItem) -> str:
        """A source identifier that survives updates (e.g. D12345). Default
        returns raw_item.id unchanged; override to strip volatile components
        (e.g. trailing timestamps) from the source id."""
        return raw_item.id

    def poll_returns_complete_set(self) -> bool:
        """Whether poll() returns ALL active entities regardless of `since`.
        When True, items absent from poll results are treated as terminal
        (disappeared). Default False — watermark-filtered adapters must not
        override this."""
        return False

    async def close(self) -> None:
        pass
