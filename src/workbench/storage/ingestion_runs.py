from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import asyncpg

from workbench.models import IngestionRun


class IngestionRunStore(ABC):
    @abstractmethod
    async def start_run(self, source_id: str) -> str: ...
    @abstractmethod
    async def finish_run(self, run_id: str, raw_enqueued: int) -> None: ...
    @abstractmethod
    async def error_run(self, run_id: str, error: str) -> None: ...
    @abstractmethod
    async def latest_for_source(self, source_id: str) -> IngestionRun | None: ...
    @abstractmethod
    async def recent_for_source(
        self, source_id: str, limit: int = 20
    ) -> list[IngestionRun]: ...
    @abstractmethod
    async def timeseries(
        self, days: int, bucket: str
    ) -> list[tuple[datetime, int]]: ...
    @abstractmethod
    async def success_rate(self, days: int) -> float | None: ...
    @abstractmethod
    async def delete_older_than(self, days: int) -> int: ...


class PgIngestionRunStore(IngestionRunStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def start_run(self, source_id: str) -> str:
        run_id = str(uuid.uuid4())
        await self.pool.execute(
            "INSERT INTO ingestion_runs (id, source_id, started_at, status, raw_enqueued) "
            "VALUES ($1, $2, $3, 'running', 0)",
            run_id,
            source_id,
            datetime.now(timezone.utc),
        )
        return run_id

    async def finish_run(self, run_id: str, raw_enqueued: int) -> None:
        await self.pool.execute(
            "UPDATE ingestion_runs SET status = 'success', finished_at = $1, "
            "raw_enqueued = $2 WHERE id = $3",
            datetime.now(timezone.utc),
            raw_enqueued,
            run_id,
        )

    async def error_run(self, run_id: str, error: str) -> None:
        await self.pool.execute(
            "UPDATE ingestion_runs SET status = 'error', finished_at = $1, error = $2 "
            "WHERE id = $3",
            datetime.now(timezone.utc),
            error,
            run_id,
        )

    async def latest_for_source(self, source_id: str) -> IngestionRun | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM ingestion_runs WHERE source_id = $1 "
            "ORDER BY started_at DESC LIMIT 1",
            source_id,
        )
        return self._row(row) if row else None

    async def recent_for_source(
        self, source_id: str, limit: int = 20
    ) -> list[IngestionRun]:
        rows = await self.pool.fetch(
            "SELECT * FROM ingestion_runs WHERE source_id = $1 "
            "ORDER BY started_at DESC LIMIT $2",
            source_id,
            limit,
        )
        return [self._row(r) for r in rows]

    async def timeseries(self, days: int, bucket: str) -> list[tuple[datetime, int]]:
        if bucket not in ("day", "hour", "week"):
            bucket = "day"
        rows = await self.pool.fetch(
            f"SELECT date_trunc('{bucket}', started_at) AS ts, "
            "COALESCE(SUM(raw_enqueued), 0) AS total FROM ingestion_runs "
            "WHERE started_at >= NOW() - INTERVAL '1 day' * $1 "
            "GROUP BY ts ORDER BY ts",
            days,
        )
        return [(r["ts"], int(r["total"])) for r in rows]

    async def success_rate(self, days: int) -> float | None:
        """success_runs / total_runs over the window (ADR0040).

        Counts only finished runs (status in success/error); excludes still
        'running' rows. Returns ``None`` when there are no finished runs in the
        window so the UI renders "n/a" instead of a fabricated figure.
        """
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) FILTER (WHERE status = 'success') AS ok, "
            "COUNT(*) FILTER (WHERE status IN ('success', 'error')) AS total "
            "FROM ingestion_runs "
            "WHERE started_at >= NOW() - INTERVAL '1 day' * $1",
            days,
        )
        total = int(row["total"])
        if total == 0:
            return None
        return int(row["ok"]) / total

    async def delete_older_than(self, days: int) -> int:
        result = await self.pool.execute(
            "DELETE FROM ingestion_runs WHERE started_at < NOW() - INTERVAL '1 day' * $1",
            days,
        )
        return int(result.split()[-1])

    @staticmethod
    def _row(row: asyncpg.Record) -> IngestionRun:
        return IngestionRun(
            id=row["id"],
            source_id=row["source_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            raw_enqueued=row["raw_enqueued"],
            error=row["error"],
        )
