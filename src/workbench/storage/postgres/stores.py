from workbench.storage.base import Stores
from workbench.storage.postgres.config import PgConfigStore
from workbench.storage.postgres.enrichment import PgEnrichmentTraceStore
from workbench.storage.postgres.filter_rules import PgFilterRuleStore
from workbench.storage.postgres.ingestion_queue import PgIngestionQueueStore
from workbench.storage.postgres.interactions import PgInteractionStore
from workbench.storage.postgres.items import PgItemStore
from workbench.storage.postgres.jobs import PgJobStore
from workbench.storage.postgres.plans import PgPlanStore
from workbench.storage.postgres.pool import create_pool
from workbench.storage.postgres.processed import PgProcessedStore
from workbench.storage.postgres.sources import PgSourceConfigStore
from workbench.storage.postgres.triage import PgTriageStore


async def create_postgres_stores(dsn: str) -> Stores:
    pool = await create_pool(dsn)

    async def close():
        await pool.close()

    return Stores(
        items=PgItemStore(pool),
        triage=PgTriageStore(pool),
        plans=PgPlanStore(pool),
        interactions=PgInteractionStore(pool),
        filter_rules=PgFilterRuleStore(pool),
        enrichment=PgEnrichmentTraceStore(pool),
        sources=PgSourceConfigStore(pool),
        processed=PgProcessedStore(pool),
        config=PgConfigStore(pool),
        jobs=PgJobStore(pool),
        ingestion_queue=PgIngestionQueueStore(pool),
        close_fn=close,
    )
