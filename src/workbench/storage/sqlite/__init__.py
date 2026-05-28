from workbench.storage.base import Stores
from workbench.storage.sqlite.connection import create_connection
from workbench.storage.sqlite.items import SqliteItemStore
from workbench.storage.sqlite.triage import SqliteTriageStore
from workbench.storage.sqlite.plans import SqlitePlanStore
from workbench.storage.sqlite.interactions import SqliteInteractionStore
from workbench.storage.sqlite.filter_rules import SqliteFilterRuleStore
from workbench.storage.sqlite.enrichment import SqliteEnrichmentTraceStore
from workbench.storage.sqlite.sources import SqliteSourceConfigStore
from workbench.storage.sqlite.processed import SqliteProcessedStore
from workbench.storage.sqlite.config import SqliteConfigStore
from workbench.storage.sqlite.jobs import SqliteJobStore


async def create_sqlite_stores(db_path: str) -> Stores:
    db = await create_connection(db_path)
    return Stores(
        items=SqliteItemStore(db),
        triage=SqliteTriageStore(db),
        plans=SqlitePlanStore(db),
        interactions=SqliteInteractionStore(db),
        filter_rules=SqliteFilterRuleStore(db),
        enrichment=SqliteEnrichmentTraceStore(db),
        sources=SqliteSourceConfigStore(db),
        processed=SqliteProcessedStore(db),
        config=SqliteConfigStore(db),
        jobs=SqliteJobStore(db),
    )
