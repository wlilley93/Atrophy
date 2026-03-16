-- COMPANION DATABASE SCHEMA
-- Three-layer memory architecture: Episodic → Semantic → Identity

-- ── LAYER 1: EPISODIC ─────────────────────────────────────────
-- Raw turn-by-turn record. Never deleted. The permanent log.

CREATE TABLE IF NOT EXISTS sessions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  ended_at        DATETIME,
  summary         TEXT,
  mood            TEXT,
  notable         BOOLEAN DEFAULT 0,
  cli_session_id  TEXT
);

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

-- ── LAYER 2: SEMANTIC ─────────────────────────────────────────
-- Summarised understanding. Injected at session start.

CREATE TABLE IF NOT EXISTS summaries (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  session_id    INTEGER REFERENCES sessions(id),
  content       TEXT NOT NULL,
  topics        TEXT,
  embedding     BLOB
);

CREATE TABLE IF NOT EXISTS threads (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  last_updated  DATETIME,
  summary       TEXT,
  status        TEXT DEFAULT 'active'
    CHECK(status IN ('active', 'dormant', 'resolved'))
);

CREATE TABLE IF NOT EXISTS thread_mentions (
  turn_id       INTEGER REFERENCES turns(id),
  thread_id     INTEGER REFERENCES threads(id),
  PRIMARY KEY (turn_id, thread_id)
);

-- ── LAYER 3: IDENTITY ─────────────────────────────────────────
-- Persistent model of Will. Updated deliberately, not automatically.

CREATE TABLE IF NOT EXISTS identity_snapshots (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  trigger       TEXT,
  content       TEXT NOT NULL
);

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

-- ── BOOKMARKS ──────────────────────────────────────────────────
-- Significant moments the companion marks silently.

CREATE TABLE IF NOT EXISTS bookmarks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  moment      TEXT NOT NULL,
  quote       TEXT,
  embedding   BLOB
);

-- ── AUDIT ────────────────────────────────────────────────────
-- Every tool call the companion makes, for review.

CREATE TABLE IF NOT EXISTS tool_calls (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
  tool_name   TEXT NOT NULL,
  input_json  TEXT,
  flagged     BOOLEAN DEFAULT 0
);

-- ── HEARTBEATS ──────────────────────────────────────────────────
-- Log of every heartbeat evaluation, whether it reached out or not.

CREATE TABLE IF NOT EXISTS heartbeats (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
  decision  TEXT NOT NULL,
  reason    TEXT,
  message   TEXT
);

-- ── COHERENCE CHECKS ──────────────────────────────────────────
-- SENTINEL monitor logs — tracks mid-session degradation checks.

CREATE TABLE IF NOT EXISTS coherence_checks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    score     REAL,
    degraded  BOOLEAN,
    signals   TEXT,
    action    TEXT DEFAULT 'none'
);

-- ── KNOWLEDGE GRAPH ──────────────────────────────────────────
-- Entity extraction and relationship tracking.

CREATE TABLE IF NOT EXISTS entities (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    entity_type   TEXT DEFAULT 'concept',  -- person, concept, place, event, project
    first_seen    DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen     DATETIME,
    mention_count INTEGER DEFAULT 1,
    embedding     BLOB
);

CREATE TABLE IF NOT EXISTS entity_relations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_a    INTEGER REFERENCES entities(id),
    entity_b    INTEGER REFERENCES entities(id),
    relation    TEXT,           -- "discussed_with", "related_to", "part_of", etc.
    strength    REAL DEFAULT 0.5,
    first_seen  DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen   DATETIME
);

-- ── INTELLIGENCE ──────────────────────────────────────────────
-- News items filed by agents. Structured storage with dedup.

CREATE TABLE IF NOT EXISTS intelligence (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  headline      TEXT NOT NULL,
  summary       TEXT,
  link          TEXT,
  source        TEXT,              -- "bbc_world", "defense_one", etc.
  published_at  DATETIME,
  urgency       TEXT DEFAULT 'routine'
    CHECK(urgency IN ('routine', 'notable', 'urgent', 'critical')),
  assessed      BOOLEAN DEFAULT 0, -- has inference reviewed this?
  assessment    TEXT,              -- Montgomery's analysis
  observation_id INTEGER REFERENCES observations(id),
  embedding     BLOB
);

-- ── USAGE LOG ──────────────────────────────────────────────────
-- Per-inference token/time tracking for usage dashboards.

CREATE TABLE IF NOT EXISTS usage_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
  source      TEXT NOT NULL,       -- 'conversation', 'heartbeat', 'morning_brief', 'news_watch', 'task', 'oneshot'
  tokens_in   INTEGER DEFAULT 0,   -- estimated input tokens
  tokens_out  INTEGER DEFAULT 0,   -- estimated output tokens
  duration_ms INTEGER DEFAULT 0,
  tool_count  INTEGER DEFAULT 0
);

-- ── INDEXES ───────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_turns_session
  ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_timestamp
  ON turns(timestamp);
CREATE INDEX IF NOT EXISTS idx_summaries_topics
  ON summaries(topics);
CREATE INDEX IF NOT EXISTS idx_summaries_session_id
  ON summaries(session_id);
CREATE INDEX IF NOT EXISTS idx_threads_status
  ON threads(status);
CREATE INDEX IF NOT EXISTS idx_observations_inc
  ON observations(incorporated);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session
  ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_flagged
  ON tool_calls(flagged);
CREATE INDEX IF NOT EXISTS idx_observations_activation
  ON observations(activation);
CREATE INDEX IF NOT EXISTS idx_entities_name
  ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entity_relations_pair
  ON entity_relations(entity_a, entity_b);
CREATE INDEX IF NOT EXISTS idx_intelligence_link
  ON intelligence(link);
CREATE INDEX IF NOT EXISTS idx_intelligence_urgency
  ON intelligence(urgency);
CREATE INDEX IF NOT EXISTS idx_intelligence_source
  ON intelligence(source);
