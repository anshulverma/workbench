from workbench.config import AppConfig
from workbench.storage.base import Stores


async def create_stores(config: AppConfig) -> Stores:
    from workbench.storage.postgres import create_postgres_stores
    return await create_postgres_stores(config.storage.postgres_dsn)
