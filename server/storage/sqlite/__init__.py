from server.storage.base import Stores
from server.storage.sqlite.connection import create_connection
from server.storage.sqlite.items import SqliteItemStore
from server.storage.sqlite.triage import SqliteTriageStore
from server.storage.sqlite.plans import SqlitePlanStore
from server.storage.sqlite.interactions import SqliteInteractionStore
from server.storage.sqlite.filter_rules import SqliteFilterRuleStore
from server.storage.sqlite.enrichment import SqliteEnrichmentTraceStore
from server.storage.sqlite.sources import SqliteSourceConfigStore
from server.storage.sqlite.processed import SqliteProcessedStore
from server.storage.sqlite.config import SqliteConfigStore
from server.storage.sqlite.jobs import SqliteJobStore


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
