from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


class AdapterStateStore(ABC):
    @abstractmethod
    async def get_state(self, adapter_name: str) -> dict | None:
        ...

    @abstractmethod
    async def save_state(self, adapter_name: str, state: dict) -> None:
        ...

    @abstractmethod
    async def delete_state(self, adapter_name: str) -> None:
        ...


class PgAdapterStateStore(AdapterStateStore):
    def __init__(self, pool):
        self.pool = pool

    async def get_state(self, adapter_name: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT state FROM adapter_state WHERE adapter_name = $1",
            adapter_name,
        )
        if not row:
            return None
        state = row["state"]
        return json.loads(state) if isinstance(state, str) else state

    async def save_state(self, adapter_name: str, state: dict) -> None:
        await self.pool.execute(
            """INSERT INTO adapter_state (adapter_name, state, updated_at)
               VALUES ($1, $2::jsonb, $3)
               ON CONFLICT (adapter_name) DO UPDATE SET
                 state = EXCLUDED.state,
                 updated_at = EXCLUDED.updated_at""",
            adapter_name, json.dumps(state), datetime.now(timezone.utc),
        )

    async def delete_state(self, adapter_name: str) -> None:
        await self.pool.execute(
            "DELETE FROM adapter_state WHERE adapter_name = $1",
            adapter_name,
        )
