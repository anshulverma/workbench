from server.storage.base import Stores
from server.pipeline.engine import PipelineEngine
from server.models import ItemFilters, JobTrigger


class WorkbenchMCPTools:
    def __init__(self, stores: Stores, pipeline: PipelineEngine):
        self.stores = stores
        self.pipeline = pipeline

    async def workbench_process(self, text: str, source_type: str = "manual") -> dict:
        job = await self.pipeline.process(text, source_type, JobTrigger.MANUAL)
        return {"job_id": job.id, "status": job.status.value}

    async def workbench_items(self, priority: str = None, status: str = None) -> list[dict]:
        items = await self.stores.items.get_items(ItemFilters(priority=priority, status=status))
        return [i.model_dump() for i in items]

    async def workbench_triage_pending(self) -> list[dict]:
        cards = await self.stores.triage.get_pending()
        return [c.model_dump() for c in cards]

    async def workbench_status(self) -> dict:
        items = await self.stores.items.get_items(ItemFilters())
        pending = await self.stores.triage.get_pending()
        return {
            "total_items": len(items),
            "pending_triage": len(pending),
            "active_items": len([i for i in items if i.status.value == "active"]),
        }
