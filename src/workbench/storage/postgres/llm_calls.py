from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import asyncpg

from workbench.domain.llm_calls import LlmCallRecord, LlmSubcall
from workbench.storage.base import LlmCallStore


class PgLlmCallStore(LlmCallStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def save_many(self, records: list[LlmCallRecord]) -> None:
        if not records:
            return
        await self.pool.executemany(
            """INSERT INTO llm_calls
               (started_at,origin,purpose,stage,model,temperature,status,error_type,
                batch,items,tokens_in,tokens_out,cache_read_tokens,cache_write_tokens,
                latency_ms,system_prompt,subcalls,tokens_estimated,is_fallback)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14,$15,$16,$17::jsonb,$18,$19)""",
            [
                (
                    r.started_at,
                    r.origin,
                    r.purpose,
                    r.stage,
                    r.model,
                    r.temperature,
                    r.status,
                    r.error_type,
                    r.batch,
                    json.dumps(r.items),
                    r.tokens_in,
                    r.tokens_out,
                    r.cache_read_tokens,
                    r.cache_write_tokens,
                    r.latency_ms,
                    r.system_prompt,
                    json.dumps([s.model_dump() for s in r.subcalls]),
                    r.tokens_estimated,
                    r.is_fallback,
                )
                for r in records
            ],
        )

    @staticmethod
    def _row(rec) -> LlmCallRecord:
        d = dict(rec)
        d.pop("created_at", None)
        items = d["items"]
        subs = d["subcalls"]
        d["items"] = json.loads(items) if isinstance(items, str) else items
        subs = json.loads(subs) if isinstance(subs, str) else subs
        d["subcalls"] = [LlmSubcall(**s) for s in subs]
        return LlmCallRecord(**d)

    async def list_calls(
        self,
        *,
        limit,
        before=None,
        stage=None,
        status=None,
        origin=None,
        q=None,
    ) -> list[LlmCallRecord]:
        clauses, args = ["1=1"], []
        if before:
            args.extend(before)
            clauses.append(f"(started_at, id) < (${len(args)-1}, ${len(args)})")
        if stage:
            args.append(stage)
            clauses.append(f"stage = ${len(args)}")
        if status:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        if origin:
            args.append(origin)
            clauses.append(f"origin = ${len(args)}")
        if q:
            args.append(q)
            clauses.append(
                f"(origin || ' ' || purpose || ' ' || model) ILIKE '%' || ${len(args)} || '%'"
            )
        args.append(limit)
        rows = await self.pool.fetch(
            f"SELECT * FROM llm_calls WHERE {' AND '.join(clauses)} "
            f"ORDER BY started_at DESC, id DESC LIMIT ${len(args)}",
            *args,
        )
        return [self._row(r) for r in rows]

    async def get_by_id(self, call_id) -> LlmCallRecord | None:
        r = await self.pool.fetchrow("SELECT * FROM llm_calls WHERE id=$1", call_id)
        return self._row(r) if r else None

    async def count_since(self, since) -> int:
        return await self.pool.fetchval(
            "SELECT COUNT(*) FROM llm_calls WHERE created_at >= $1", since
        )

    async def metrics_24h(self) -> dict:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        r = await self.pool.fetchrow(
            """SELECT COUNT(*) AS calls,
                      AVG(latency_ms) FILTER (WHERE status='ok') AS avg_ms,
                      COUNT(*) FILTER (WHERE status='error')::float / NULLIF(COUNT(*),0) AS err,
                      COUNT(*) FILTER (WHERE batch>1)::float / NULLIF(COUNT(*),0) AS batched
               FROM llm_calls WHERE created_at >= $1""",
            since,
        )
        return {
            "calls_24h": r["calls"],
            "avg_latency_ms": float(r["avg_ms"]) if r["avg_ms"] is not None else None,
            "error_rate": float(r["err"] or 0.0),
            "batched_pct": float(r["batched"] or 0.0),
        }

    async def delete_older_than(self, days) -> int:
        res = await self.pool.execute(
            "DELETE FROM llm_calls WHERE created_at < NOW() - INTERVAL '1 day' * $1",
            days,
        )
        return int(res.split()[-1])

    async def prune_to_max_rows(self, max_rows) -> int:
        res = await self.pool.execute(
            "DELETE FROM llm_calls WHERE id IN "
            "(SELECT id FROM llm_calls ORDER BY started_at DESC OFFSET $1)",
            max_rows,
        )
        return int(res.split()[-1])
