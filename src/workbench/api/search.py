"""Global search API (Design Section 4, ADR0037).

GET /api/search?q=&limit= — bearer-authed (global middleware). Returns a
grouped envelope of SearchHits across items, action items, sources, and
(degradably) preference facts:

    {
      "q": "<echo>",
      "groups": {
        "items":   [SearchHit, ...],
        "actions": [SearchHit, ...],
        "sources": [SearchHit, ...],
        "facts":   [SearchHit, ...]   # OMITTED when memory is noop/unreachable
      },
      "truncated": bool   # true if any group hit the per-group cap
    }

SearchHit = {id, kind, label, sublabel?, route}.

Matching is parameterized ILIKE with %/_/\ wildcards escaped so user input is
always treated literally. Ranking (in Python) is exact -> prefix -> substring,
then recency. Facts are proxied from the memory layer and silently dropped
(degraded, not an error) when memory is a NoopMemoryLayer or unreachable.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Query, Request

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["search"])

# limit defaults to 20, hard-capped at 50 (ADR0037). Queries shorter than this
# are treated as empty (client handles the empty-query state; spec §4).
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50
_MIN_QUERY_LEN = 2


def _escape_ilike(term: str) -> str:
    """Escape ILIKE wildcards so the term is matched literally.

    Order matters: escape the escape char first, then the wildcards.
    Used with ``ILIKE '%' || $1 || '%' ESCAPE '\\'``.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _rank_key(label: str, q_lower: str):
    """Sort key: lower rank tiers first (exact, prefix, substring), then most
    recent. Recency is supplied separately as a secondary key by the caller.
    """
    label_lower = label.lower()
    if label_lower == q_lower:
        return 0
    if label_lower.startswith(q_lower):
        return 1
    return 2


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(""),
    limit: int = Query(_DEFAULT_LIMIT),
):
    """Global ILIKE search, grouped envelope. Empty/short q -> empty groups."""
    q = (q or "").strip()
    limit = max(1, min(limit, _MAX_LIMIT))

    # Empty-query contract: return well-formed empty groups (client owns the
    # "type to search" state). Facts group is still omitted (degraded default).
    if len(q) < _MIN_QUERY_LEN:
        return {
            "q": q,
            "groups": {"items": [], "actions": [], "sources": []},
            "truncated": False,
        }

    stores = request.app.state.stores
    pool = stores.items.pool
    escaped = _escape_ilike(q)
    q_lower = q.lower()
    truncated = False

    # Fetch one extra row per group so we can detect truncation precisely.
    fetch_n = limit + 1

    # --- Items (non-action) -------------------------------------------------
    item_rows = await pool.fetch(
        """
        SELECT id, summary, status, source_type, priority, created_at
          FROM items
         WHERE action_source IS NULL
           AND summary ILIKE '%' || $1 || '%' ESCAPE '\\'
         ORDER BY created_at DESC
         LIMIT $2
        """,
        escaped,
        fetch_n,
    )
    items_hits = [
        {
            "id": r["id"],
            "kind": "item",
            "label": r["summary"],
            "sublabel": f"{r['source_type']} · {r['priority']}",
            "route": "/triage" if r["status"] == "pending_triage" else "/",
            "_created_at": r["created_at"],
        }
        for r in item_rows
    ]

    # --- Action items (items with action_source set) ------------------------
    action_rows = await pool.fetch(
        """
        SELECT id, summary, status, source_type, priority, created_at
          FROM items
         WHERE action_source IS NOT NULL
           AND summary ILIKE '%' || $1 || '%' ESCAPE '\\'
         ORDER BY created_at DESC
         LIMIT $2
        """,
        escaped,
        fetch_n,
    )
    actions_hits = [
        {
            "id": r["id"],
            "kind": "action",
            "label": r["summary"],
            "sublabel": f"{r['source_type']} · {r['priority']}",
            "route": "/actions",
            "_created_at": r["created_at"],
        }
        for r in action_rows
    ]

    # --- Sources (id or adapter_type) ---------------------------------------
    source_rows = await pool.fetch(
        """
        SELECT id, adapter_type, created_at
          FROM source_configs
         WHERE id ILIKE '%' || $1 || '%' ESCAPE '\\'
            OR adapter_type ILIKE '%' || $1 || '%' ESCAPE '\\'
         ORDER BY created_at DESC
         LIMIT $2
        """,
        escaped,
        fetch_n,
    )
    sources_hits = [
        {
            "id": r["id"],
            "kind": "source",
            "label": r["adapter_type"],
            "sublabel": r["id"],
            "route": "/sources",
            "_created_at": r["created_at"],
        }
        for r in source_rows
    ]

    groups: dict[str, list[dict]] = {
        "items": items_hits,
        "actions": actions_hits,
        "sources": sources_hits,
    }

    # --- Facts (degradable) -------------------------------------------------
    # Proxied from the memory layer; omitted entirely when memory is a noop
    # layer or unreachable. Never surfaces as an error (ADR0037).
    memory = getattr(request.app.state, "memory", None)
    facts_hits = await _facts_group(memory, q_lower)
    if facts_hits is not None:
        groups["facts"] = facts_hits

    # Rank within each group (exact -> prefix -> substring, then recency) and
    # truncate to the cap, recording whether any group overflowed.
    for key, hits in groups.items():
        hits.sort(key=lambda h: (_rank_key(h["label"], q_lower), -_recency(h)))
        if len(hits) > limit:
            truncated = True
        del hits[limit:]
        for h in hits:
            h.pop("_created_at", None)

    return {"q": q, "groups": groups, "truncated": truncated}


def _recency(hit: dict) -> float:
    ts = hit.get("_created_at")
    if ts is None:
        return 0.0
    try:
        return ts.timestamp()
    except Exception:
        return 0.0


async def _facts_group(memory, q_lower: str) -> list[dict] | None:
    """Return facts SearchHits, or None to OMIT the group (degraded).

    None signals "facts unavailable" (noop memory, unreachable, or error) so
    the caller drops the group key entirely rather than emitting an empty list.
    """
    if memory is None:
        return None
    if getattr(memory, "memory_type", "noop") == "noop":
        return None
    try:
        available = await memory.is_available()
    except Exception:
        logger.warning("search: memory.is_available failed; omitting facts")
        return None
    if not available:
        return None
    try:
        facts = await memory.list_facts()
    except Exception:
        logger.warning("search: memory.list_facts failed; omitting facts")
        return None

    hits = []
    for f in facts:
        content = getattr(f, "content", "") or ""
        if q_lower not in content.lower():
            continue
        hits.append(
            {
                "id": getattr(f, "id", None) or content[:64],
                "kind": "fact",
                "label": content,
                "sublabel": getattr(f, "source", None) or None,
                "route": "/knowledge",
                "_created_at": getattr(f, "timestamp", None),
            }
        )
    return hits
