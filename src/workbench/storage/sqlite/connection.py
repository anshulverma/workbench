import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    category TEXT NOT NULL,
    origin TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    raw_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_status_priority ON items(status, priority);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    content TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS triage_cards (
    id TEXT PRIMARY KEY,
    item_id TEXT,
    card_content TEXT NOT NULL DEFAULT '{}',
    options TEXT NOT NULL DEFAULT '[]',
    sent_at TEXT,
    responded_at TEXT,
    response TEXT
);
CREATE INDEX IF NOT EXISTS idx_triage_pending ON triage_cards(responded_at);

CREATE TABLE IF NOT EXISTS interaction_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    source_type TEXT NOT NULL,
    item_id TEXT,
    item_summary TEXT NOT NULL,
    triage_card_full TEXT NOT NULL DEFAULT '{}',
    enrichment_context TEXT NOT NULL DEFAULT '{}',
    options_presented TEXT NOT NULL DEFAULT '[]',
    option_chosen TEXT NOT NULL DEFAULT '',
    todo_created TEXT,
    enrichment_depth TEXT NOT NULL DEFAULT 'none',
    enrichment_calls INTEGER NOT NULL DEFAULT 0,
    enrichment_time_ms INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS filter_rules (
    id TEXT PRIMARY KEY,
    source_type TEXT,
    pattern TEXT NOT NULL,
    action TEXT NOT NULL,
    priority TEXT,
    created_from_interaction_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS enrichment_trace (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    depth TEXT NOT NULL,
    calls_made INTEGER NOT NULL,
    time_ms INTEGER NOT NULL,
    context_retrieved TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed (
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (source_type, source_id)
);

CREATE TABLE IF NOT EXISTS source_configs (
    id TEXT PRIMARY KEY,
    adapter_type TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    schedule TEXT NOT NULL DEFAULT '*/15 * * * *',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    input_hash TEXT NOT NULL DEFAULT '',
    items_extracted INTEGER NOT NULL DEFAULT 0,
    items_included INTEGER NOT NULL DEFAULT 0,
    items_triaged INTEGER NOT NULL DEFAULT 0,
    items_dropped INTEGER NOT NULL DEFAULT 0,
    items_failed INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


async def create_connection(db_path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.executescript(SCHEMA)
    await db.commit()
    return db
