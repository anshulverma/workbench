# server/storage/factory.py
from server.config import Settings
from server.storage.base import Stores

async def create_stores(settings: Settings) -> Stores:
    if settings.storage_backend == "sqlite":
        from server.storage.sqlite import create_sqlite_stores
        return await create_sqlite_stores(settings.sqlite_path)
    raise ValueError(f"Unknown storage backend: {settings.storage_backend}")
