# db/schema.sql - Database Schema

**Line count:** ~278 lines  
**Purpose:** SQLite schema for three-layer memory architecture

## Overview

This file defines the complete database schema for Atrophy's memory system. The architecture has three layers:

1. **Episodic** - Raw turn-by-turn record (permanent, immutable)
2. **Semantic** - Summarized understanding (injected at session start)
3. **Identity** - Persistent model of the user (updated deliberately)

## Layer 1: Episodic Memory

### sessions

```sql
CREATE TABLE IF NOT EXISTS sessions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  ended_at        DATETIME,
  summary         TEXT,
  mood            TEXT,
  notable         BOOLEAN DEFAULT 0,
  cli_session_id  TEXT
);
```

**Purpose:** Track conversation sessions from start to close.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `started_at` | DATETIME | Session start time |
| `ended_at` | DATETIME | Session end time (null if active) |
| `summary` | TEXT | 2-3 sentence summary generated at session end |
| `mood` | TEXT | Detected mood (e.g., "heavy") |
| `notable` | BOOLEAN | Flag for significant sessions |
| `cli_session_id` | TEXT | Claude CLI session ID for `--resume` |

### turns

```sql
CREATE TABLE IF NOT EXISTS turns (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  role        TEXT NOT NULL CHECK(role IN ('will', 'agent')),
  content     TEXT NOT NULL,
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
  topic_tags  TEXT,
  weight      INTEGER DEFAULT 1 CHECK(weight BETWEEN 1 AND 5),
  channel     TEXT DEFAULT 'direct',
  embedding   BLOB
);
```

**Purpose:** Individual messages within a session.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `session_id` | INTEGER | Foreign key to sessions |
| `role` | TEXT | `'will'` (user) or `'agent'` |
| `content` | TEXT | Message text |
| `timestamp` | DATETIME | Message timestamp |
| `topic_tags` | TEXT | Optional topic labels |
| `weight` | INTEGER | 1-5 importance (default 1) |
| `channel` | TEXT | `'direct'`, `'telegram'`, `'task'` |
| `embedding` | BLOB | 384-dim float32 vector |

**CHECK constraints:**
- `role IN ('will', 'agent')` - Prevents legacy `'companion'` role
- `weight BETWEEN 1 AND 5` - Valid weight range

## Layer 2: Semantic Memory

### summaries

```sql
CREATE TABLE IF NOT EXISTS summaries (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  session_id    INTEGER REFERENCES sessions(id),
  content       TEXT NOT NULL,
  topics        TEXT,
  embedding     BLOB
);
```

**Purpose:** Session summaries for context injection.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `created_at` | DATETIME | Summary creation time |
| `session_id` | INTEGER | Foreign key to sessions |
| `content` | TEXT | 2-3 sentence summary |
| `topics` | TEXT | Topic tags |
| `embedding` | BLOB | 384-dim float32 vector |

### threads

```sql
CREATE TABLE IF NOT EXISTS threads (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  last_updated  DATETIME,
  summary       TEXT,
  status        TEXT DEFAULT 'active'
    CHECK(status IN ('active', 'dormant', 'resolved'))
);
```

**Purpose:** Track ongoing topics across sessions.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `name` | TEXT | Thread name (e.g., "career transition") |
| `last_updated` | DATETIME | Last update time |
| `summary` | TEXT | Current state description |
| `status` | TEXT | `'active'`, `'dormant'`, or `'resolved'` |

### thread_mentions

```sql
CREATE TABLE IF NOT EXISTS thread_mentions (
  turn_id       INTEGER REFERENCES turns(id),
  thread_id     INTEGER REFERENCES threads(id),
  PRIMARY KEY (turn_id, thread_id)
);
```

**Purpose:** Junction table linking turns to threads.

**Composite primary key:** Prevents duplicate links.

## Layer 3: Identity Memory

### identity_snapshots

```sql
CREATE TABLE IF NOT EXISTS identity_snapshots (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  trigger       TEXT,
  content       TEXT NOT NULL
);
```

**Purpose:** Agent's self-understanding snapshots.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `created_at` | DATETIME | Snapshot creation time |
| `trigger` | TEXT | What prompted the snapshot |
| `content` | TEXT | First-person narrative |

### observations

```sql
CREATE TABLE IF NOT EXISTS observations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  content       TEXT NOT NULL,
  source_turn   INTEGER REFERENCES turns(id),
  incorporated  BOOLEAN DEFAULT 0,
  -- Bi-temporal columns
  valid_from    DATETIME,
  valid_to      DATETIME,
  learned_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  expired_at    DATETIME,
  confidence    REAL DEFAULT 0.5,
  activation    REAL DEFAULT 1.0,
  last_accessed DATETIME,
  embedding     BLOB
);
```

**Purpose:** Facts about the user with bi-temporal tracking.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `created_at` | DATETIME | Observation creation time |
| `content` | TEXT | Observation text |
| `source_turn` | INTEGER | Source turn (optional) |
| `incorporated` | BOOLEAN | Reviewed and confirmed |
| `valid_from` | DATETIME | When fact became true (event time) |
| `valid_to` | DATETIME | When fact stopped being true |
| `learned_at` | DATETIME | When agent learned it (transaction time) |
| `expired_at` | DATETIME | When observation was retired |
| `confidence` | REAL | 0.0-1.0 confidence level |
| `activation` | REAL | 0.0-1.0 activation (decays over time) |
| `last_accessed` | DATETIME | Last retrieval time |
| `embedding` | BLOB | 384-dim float32 vector |

**Bi-temporal design:**
- `valid_from`/`valid_to`: When the fact was true in reality
- `learned_at`/`expired_at`: When the agent knew it

## Bookmarks

```sql
CREATE TABLE IF NOT EXISTS bookmarks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  moment      TEXT NOT NULL,
  quote       TEXT,
  embedding   BLOB
);
```

**Purpose:** Significant moments marked silently.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `session_id` | INTEGER | Foreign key to sessions |
| `created_at` | DATETIME | Bookmark creation time |
| `moment` | TEXT | What made it significant |
| `quote` | TEXT | Exact words (optional) |
| `embedding` | BLOB | 384-dim float32 vector |

## Audit Tables

### tool_calls

```sql
CREATE TABLE IF NOT EXISTS tool_calls (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
  tool_name   TEXT NOT NULL,
  input_json  TEXT,
  flagged     BOOLEAN DEFAULT 0
);
```

**Purpose:** Audit log of MCP tool calls.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `session_id` | INTEGER | Foreign key to sessions |
| `timestamp` | DATETIME | Call timestamp |
| `tool_name` | TEXT | MCP tool name |
| `input_json` | TEXT | Input arguments |
| `flagged` | BOOLEAN | Matched safety patterns |

### heartbeats

```sql
CREATE TABLE IF NOT EXISTS heartbeats (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
  decision  TEXT NOT NULL,
  reason    TEXT,
  message   TEXT
);
```

**Purpose:** Log of every heartbeat evaluation.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `timestamp` | DATETIME | Evaluation timestamp |
| `decision` | TEXT | `"send"` or `"skip"` |
| `reason` | TEXT | Why decision was made |
| `message` | TEXT | What was sent (if sent) |

### coherence_checks

```sql
CREATE TABLE IF NOT EXISTS coherence_checks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    score     REAL,
    degraded  BOOLEAN,
    signals   TEXT,
    action    TEXT DEFAULT 'none'
);
```

**Purpose:** SENTINEL coherence monitoring logs.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `timestamp` | DATETIME | Check timestamp |
| `score` | REAL | 0.0-1.0 coherence score |
| `degraded` | BOOLEAN | Whether degradation detected |
| `signals` | TEXT | JSON array of signal strings |
| `action` | TEXT | `"none"` or `"reanchor"` |

## Knowledge Graph

### entities

```sql
CREATE TABLE IF NOT EXISTS entities (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    entity_type   TEXT DEFAULT 'concept',
    first_seen    DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen     DATETIME,
    mention_count INTEGER DEFAULT 1,
    embedding     BLOB
);
```

**Purpose:** Knowledge graph nodes (people, concepts, places, events, projects).

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `name` | TEXT | Entity name (unique) |
| `entity_type` | TEXT | `'person'`, `'concept'`, `'place'`, `'event'`, `'project'` |
| `first_seen` | DATETIME | First mention time |
| `last_seen` | DATETIME | Last mention time |
| `mention_count` | INTEGER | Total mentions |
| `embedding` | BLOB | 384-dim float32 vector |

### entity_relations

```sql
CREATE TABLE IF NOT EXISTS entity_relations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_a    INTEGER REFERENCES entities(id),
    entity_b    INTEGER REFERENCES entities(id),
    relation    TEXT,
    strength    REAL DEFAULT 0.5,
    first_seen  DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen   DATETIME
);
```

**Purpose:** Knowledge graph edges.

**Fields:**

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Auto-increment primary key |
| `entity_a` | INTEGER | Foreign key to entities |
| `entity_b` | INTEGER | Foreign key to entities |
| `relation` | TEXT | Relation type (e.g., `"discussed_with"`) |
| `strength` | REAL | 0.0-1.0 (starts at 0.5, increments on re-encounter) |
| `first_seen` | DATETIME | First link time |
| `last_seen` | DATETIME | Last link time |

## Indexes

```sql
-- Turn indexes
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp);

-- Summary indexes
CREATE INDEX IF NOT EXISTS idx_summaries_session_id ON summaries(session_id);

-- Observation indexes
CREATE INDEX IF NOT EXISTS idx_observations_incorporated ON observations(incorporated);
CREATE INDEX IF NOT EXISTS idx_observations_activation ON observations(activation);

-- Thread indexes
CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status);

-- Entity indexes
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

-- Relation indexes
CREATE INDEX IF NOT EXISTS idx_entity_relations_a ON entity_relations(entity_a);
CREATE INDEX IF NOT EXISTS idx_entity_relations_b ON entity_relations(entity_b);
```

## Embedding Columns

All `embedding BLOB` columns store 384-dimensional float32 vectors from `@xenova/transformers` (all-MiniLM-L6-v2 model).

**Tables with embeddings:**
- `turns` - For semantic search of conversation turns
- `summaries` - For semantic search of session summaries
- `observations` - For semantic search of user facts
- `bookmarks` - For semantic search of significant moments
- `entities` - For semantic search of knowledge graph

## See Also

- [`src/main/memory.ts`](files/src/main/memory.md) - Database operations
- [`src/main/vector-search.ts`](files/src/main/vector-search.md) - Hybrid search implementation
- [`src/main/embeddings.ts`](files/src/main/embeddings.md) - Embedding engine
