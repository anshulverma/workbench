# Step 2: Database Schema and Models

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [01-docker-stack.md](01-docker-stack.md)

## Goal

SQLAlchemy models for all tables and Alembic migrations that create them. The server connects to PostgreSQL on startup and verifies the schema.

## Files to Create

```
server/
  database.py                -- async engine, session factory, base model
  models/
    __init__.py              -- re-exports all models
    user.py                  -- users, workspaces, workspace_members
    item.py                  -- items
    plan.py                  -- plans
    triage.py                -- triage_cards
    interaction.py           -- interaction_log
    filter_rule.py           -- filter_rules, email_filters
    preference.py            -- preferences
    enrichment.py            -- enrichment_trace
    source.py                -- source_configs, processed
    config.py                -- workspace_config
  migrations/
    env.py                   -- Alembic env configuration
    versions/
      001_initial_schema.py  -- initial migration
  alembic.ini
```

## database.py

- Create async SQLAlchemy engine from `Settings.database_url`
- Create `async_sessionmaker` for dependency injection
- Define `Base = declarative_base()`
- Provide `get_db()` async generator for FastAPI `Depends`

## Models

### Core Tables

**users**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK, default uuid4 |
| email | String(255) | unique, not null |
| name | String(255) | not null |
| password_hash | String(255) | not null |
| created_at | DateTime | default utcnow |

**workspaces**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | String(255) | not null |
| created_at | DateTime | default utcnow |

**workspace_members**
| Column | Type | Notes |
|--------|------|-------|
| workspace_id | UUID | FK → workspaces, PK |
| user_id | UUID | FK → users, PK |
| role | String(50) | "owner" or "member" |

### Per-Workspace Tables

All per-workspace tables have a `workspace_id` UUID FK with cascading delete.

**items**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workspace_id | UUID | FK |
| source_type | String(50) | meeting, email, social, task, code_review |
| source_id | String(255) | original ID from the source system |
| summary | Text | not null |
| priority | String(10) | P0, P1, P2, P3, pending |
| status | String(20) | active, completed, archived |
| created_at | DateTime | |
| updated_at | DateTime | |

**plans**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workspace_id | UUID | FK |
| title | String(500) | not null |
| status | String(20) | draft, reviewed, finalized |
| content | Text | full plan markdown |
| sources | JSONB | list of source references |
| created_at | DateTime | |

**triage_cards**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workspace_id | UUID | FK |
| item_id | UUID | FK → items, nullable (card may precede item creation) |
| card_content | JSONB | full triage card as presented |
| options | JSONB | array of option strings |
| sent_at | DateTime | |
| responded_at | DateTime | nullable |
| response | Text | nullable, the chosen option |

**interaction_log**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workspace_id | UUID | FK |
| timestamp | DateTime | |
| source_type | String(50) | |
| item_id | UUID | nullable |
| item_summary | Text | |
| triage_card_full | JSONB | complete triage card |
| enrichment_context | JSONB | context gathered before triage |
| options_presented | JSONB | array of options shown |
| option_chosen | Text | |
| todo_created | JSONB | nullable, details of any todo created |
| enrichment_depth | String(10) | shallow or deep |
| enrichment_calls | Integer | API calls used |
| enrichment_time_ms | Integer | time spent enriching |

**filter_rules**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workspace_id | UUID | FK |
| pattern | Text | natural language pattern |
| action | String(20) | include or drop |
| priority | String(10) | nullable, P0-P3 |
| created_from_interaction_id | UUID | FK → interaction_log, nullable |
| created_at | DateTime | |

**email_filters**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workspace_id | UUID | FK |
| account | String(255) | email address |
| pattern | Text | natural language pattern |
| action | String(20) | include or drop |
| created_from_interaction_id | UUID | FK → interaction_log, nullable |
| created_at | DateTime | |

**preferences**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workspace_id | UUID | FK, unique |
| content | Text | markdown preference summary |
| cursor_position | BigInteger | interaction_log row ID of last processed entry |
| updated_at | DateTime | |

**enrichment_trace**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workspace_id | UUID | FK |
| item_id | UUID | FK → items, nullable |
| depth | String(10) | shallow or deep |
| calls_made | Integer | |
| time_ms | Integer | |
| context_retrieved | JSONB | |
| timestamp | DateTime | |

**processed**
| Column | Type | Notes |
|--------|------|-------|
| workspace_id | UUID | FK, PK (composite) |
| source_type | String(50) | PK (composite) |
| source_id | String(255) | PK (composite) |
| processed_at | DateTime | |

**source_configs**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| workspace_id | UUID | FK |
| adapter_type | String(50) | email, meeting, social, task, code_review |
| config | JSONB | adapter-specific config (no raw credentials — see below) |
| credentials_encrypted | Text | encrypted credentials blob |
| schedule | String(50) | cron expression or interval |
| enabled | Boolean | default true |
| created_at | DateTime | |

**workspace_config**
| Column | Type | Notes |
|--------|------|-------|
| workspace_id | UUID | FK, PK (composite) |
| key | String(255) | PK (composite) |
| value | JSONB | |

## Indexes

- `items`: composite index on (workspace_id, status, priority)
- `interaction_log`: index on (workspace_id, timestamp)
- `filter_rules`: index on (workspace_id)
- `processed`: composite PK already serves as index
- `triage_cards`: index on (workspace_id, responded_at) for finding pending cards

## Alembic Setup

- `alembic.ini`: configure `sqlalchemy.url` to read from `DATABASE_URL` env var
- `migrations/env.py`: import all models, configure async migration support
- `migrations/versions/001_initial_schema.py`: create all tables

## Update main.py

- Import database engine and session
- Add startup event to verify DB connection
- Update `/health` to include DB connectivity check

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. `alembic upgrade head` creates all tables without errors
2. `alembic downgrade base` drops all tables cleanly
3. `/health` returns `{"status": "ok", "db": "connected"}`
4. All FK constraints and indexes are in place (verify with `\d+ table_name` in psql)
5. Cascading delete works: deleting a workspace removes all its per-workspace data
