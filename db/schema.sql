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
  role        TEXT NOT NULL CHECK(role IN ('will', 'companion')),
  content     TEXT NOT NULL,
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
  topic_tags  TEXT,
  weight      INTEGER DEFAULT 1 CHECK(weight BETWEEN 1 AND 5)
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
  incorporated  BOOLEAN DEFAULT 0
);

-- ── BOOKMARKS ──────────────────────────────────────────────────
-- Significant moments the companion marks silently.

CREATE TABLE IF NOT EXISTS bookmarks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  moment      TEXT NOT NULL,
  quote       TEXT
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

-- ── INDEXES ───────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_turns_session
  ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_timestamp
  ON turns(timestamp);
CREATE INDEX IF NOT EXISTS idx_summaries_topics
  ON summaries(topics);
CREATE INDEX IF NOT EXISTS idx_threads_status
  ON threads(status);
CREATE INDEX IF NOT EXISTS idx_observations_inc
  ON observations(incorporated);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session
  ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_flagged
  ON tool_calls(flagged);
