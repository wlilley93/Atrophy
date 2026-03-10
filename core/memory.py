"""SQLite memory layer. All database operations live here. No SQL elsewhere."""
import math
import re
import sqlite3
import json
import threading
from datetime import datetime
from pathlib import Path

from config import DB_PATH, SCHEMA_PATH, AGENT_NAME


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = DB_PATH):
    """Create all tables from schema.sql, then run migrations."""
    schema = SCHEMA_PATH.read_text()
    conn = _connect(db_path)
    # Run migrations first — adds missing columns that the schema's
    # CREATE INDEX statements may reference (e.g. activation).
    try:
        conn.executescript(schema)
    except sqlite3.OperationalError:
        # Schema has new columns/indexes the old DB lacks — migrate first
        _migrate(conn)
        conn.executescript(schema)
    conn.commit()
    _migrate(conn)
    conn.close()


def _migrate(conn: sqlite3.Connection):
    """Run safe migrations for schema changes on existing databases."""
    # Add channel column to turns if missing
    turns_cols = {row[1] for row in conn.execute("PRAGMA table_info(turns)").fetchall()}
    if "channel" not in turns_cols:
        conn.execute("ALTER TABLE turns ADD COLUMN channel TEXT DEFAULT 'direct'")
        conn.commit()

    # Add embedding to turns
    if "embedding" not in turns_cols:
        conn.execute("ALTER TABLE turns ADD COLUMN embedding BLOB")
        conn.commit()

    # Add bi-temporal + embedding columns to observations
    obs_cols = {row[1] for row in conn.execute("PRAGMA table_info(observations)").fetchall()}
    for col, defn in [
        ("valid_from", "DATETIME"),
        ("valid_to", "DATETIME"),
        ("learned_at", "DATETIME"),
        ("expired_at", "DATETIME"),
        ("confidence", "REAL DEFAULT 0.5"),
        ("activation", "REAL DEFAULT 1.0"),
        ("last_accessed", "DATETIME"),
        ("embedding", "BLOB"),
    ]:
        if col not in obs_cols:
            conn.execute(f"ALTER TABLE observations ADD COLUMN {col} {defn}")
    conn.commit()

    # Add embedding to summaries
    sum_cols = {row[1] for row in conn.execute("PRAGMA table_info(summaries)").fetchall()}
    if "embedding" not in sum_cols:
        conn.execute("ALTER TABLE summaries ADD COLUMN embedding BLOB")
        conn.commit()

    # Add embedding to bookmarks
    bm_cols = {row[1] for row in conn.execute("PRAGMA table_info(bookmarks)").fetchall()}
    if "embedding" not in bm_cols:
        conn.execute("ALTER TABLE bookmarks ADD COLUMN embedding BLOB")
        conn.commit()

    # Migrate role 'companion' → 'agent' and drop CHECK constraint
    # SQLite can't alter CHECK constraints, so we recreate the table
    check_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='turns'"
    ).fetchone()
    if check_sql and "'companion'" in (check_sql[0] or ""):
        conn.executescript("""
            CREATE TABLE turns_new (
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
            INSERT INTO turns_new SELECT * FROM turns;
            UPDATE turns_new SET role = 'agent' WHERE role = 'companion';
            DROP TABLE turns;
            ALTER TABLE turns_new RENAME TO turns;
            CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
            CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp);
        """)
        conn.commit()


def start_session(db_path: Path = DB_PATH) -> int:
    """Begin a new session. Returns session_id."""
    conn = _connect(db_path)
    cursor = conn.execute("INSERT INTO sessions DEFAULT VALUES")
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id


def write_turn(session_id: int, role: str, content: str,
               topic_tags: str = None, weight: int = 1,
               channel: str = "direct",
               db_path: Path = DB_PATH) -> int:
    """Write a single turn. Returns turn_id. Embeds asynchronously."""
    conn = _connect(db_path)
    cursor = conn.execute(
        "INSERT INTO turns (session_id, role, content, topic_tags, weight, channel) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, role, content, topic_tags, weight, channel),
    )
    turn_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _embed_async("turns", turn_id, content, db_path)
    return turn_id


def get_session_turns(session_id: int, db_path: Path = DB_PATH) -> list[dict]:
    """Get all turns for a session, ordered by timestamp."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT id, role, content, timestamp, topic_tags, weight "
        "FROM turns WHERE session_id = ? ORDER BY timestamp",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def end_session(session_id: int, summary: str = None,
                mood: str = None, notable: bool = False,
                db_path: Path = DB_PATH):
    """Close a session with optional summary."""
    conn = _connect(db_path)
    conn.execute(
        "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP, "
        "summary = ?, mood = ?, notable = ? WHERE id = ?",
        (summary, mood, notable, session_id),
    )
    conn.commit()
    conn.close()


def update_session_mood(session_id: int, mood: str, db_path: Path = DB_PATH):
    conn = _connect(db_path)
    conn.execute("UPDATE sessions SET mood = ? WHERE id = ?", (mood, session_id))
    conn.commit()
    conn.close()


def get_current_session_mood(db_path: Path = DB_PATH) -> str | None:
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT mood FROM sessions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["mood"] if row and row["mood"] else None


def get_context_injection(n_summaries: int = 3, db_path: Path = DB_PATH) -> str:
    """Assemble context from memory layers for injection at session start.

    Returns a formatted string containing:
    - Latest identity snapshot
    - Active threads
    - Recent session summaries
    """
    conn = _connect(db_path)
    parts = []

    # Layer 3: Identity
    row = conn.execute(
        "SELECT content FROM identity_snapshots ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row:
        parts.append(f"## Who Will Is (Current Understanding)\n{row['content']}")

    # Layer 2: Active threads
    threads = conn.execute(
        "SELECT name, summary FROM threads WHERE status = 'active' ORDER BY last_updated DESC"
    ).fetchall()
    if threads:
        thread_lines = [f"- **{t['name']}**: {t['summary'] or 'No summary yet'}" for t in threads]
        parts.append(f"## Active Threads\n" + "\n".join(thread_lines))

    # Layer 2: Recent summaries
    summaries = conn.execute(
        "SELECT content, created_at FROM summaries ORDER BY created_at DESC LIMIT ?",
        (n_summaries,),
    ).fetchall()
    if summaries:
        summary_lines = [f"[{s['created_at']}] {s['content']}" for s in reversed(summaries)]
        parts.append(f"## Recent Sessions\n" + "\n".join(summary_lines))

    conn.close()
    return "\n\n".join(parts) if parts else ""


def get_active_threads(db_path: Path = DB_PATH) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT id, name, summary, status, last_updated FROM threads "
        "WHERE status = 'active' ORDER BY last_updated DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_identity(db_path: Path = DB_PATH) -> str | None:
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT content FROM identity_snapshots ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["content"] if row else None


def write_summary(session_id: int, content: str, topics: str = None,
                  db_path: Path = DB_PATH):
    conn = _connect(db_path)
    cursor = conn.execute(
        "INSERT INTO summaries (session_id, content, topics) VALUES (?, ?, ?)",
        (session_id, content, topics),
    )
    summary_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _embed_async("summaries", summary_id, content, db_path)


def write_observation(content: str, source_turn_id: int = None,
                      confidence: float = 0.5,
                      valid_from: str = None,
                      db_path: Path = DB_PATH):
    conn = _connect(db_path)
    cursor = conn.execute(
        "INSERT INTO observations (content, source_turn, confidence, valid_from) "
        "VALUES (?, ?, ?, ?)",
        (content, source_turn_id, confidence, valid_from),
    )
    obs_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _embed_async("observations", obs_id, content, db_path)
    return obs_id


def write_identity_snapshot(content: str, trigger: str = None,
                            db_path: Path = DB_PATH):
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO identity_snapshots (content, trigger) VALUES (?, ?)",
        (content, trigger),
    )
    conn.commit()
    conn.close()


def get_last_cli_session_id(db_path: Path = DB_PATH) -> str | None:
    """Get the CLI session ID from the most recent session that has one."""
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT cli_session_id FROM sessions "
        "WHERE cli_session_id IS NOT NULL "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["cli_session_id"] if row else None


def save_cli_session_id(session_id: int, cli_session_id: str,
                        db_path: Path = DB_PATH):
    """Store the CLI session ID for a companion session."""
    conn = _connect(db_path)
    conn.execute(
        "UPDATE sessions SET cli_session_id = ? WHERE id = ?",
        (cli_session_id, session_id),
    )
    conn.commit()
    conn.close()


def log_tool_call(session_id: int, tool_name: str, input_json: str = None,
                  flagged: bool = False, db_path: Path = DB_PATH):
    """Audit log: record a tool call the companion made."""
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO tool_calls (session_id, tool_name, input_json, flagged) "
        "VALUES (?, ?, ?, ?)",
        (session_id, tool_name, input_json, flagged),
    )
    conn.commit()
    conn.close()


def get_tool_audit(session_id: int = None, flagged_only: bool = False,
                   limit: int = 50, db_path: Path = DB_PATH) -> list[dict]:
    """Retrieve tool call audit log."""
    conn = _connect(db_path)
    conditions = []
    params = []
    if session_id is not None:
        conditions.append("session_id = ?")
        params.append(session_id)
    if flagged_only:
        conditions.append("flagged = 1")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM tool_calls {where} ORDER BY timestamp DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_session_mood(session_id: int, mood: str, db_path: Path = DB_PATH):
    """Update the mood field on the current session."""
    conn = _connect(db_path)
    conn.execute(
        "UPDATE sessions SET mood = ? WHERE id = ?",
        (mood, session_id),
    )
    conn.commit()
    conn.close()


def create_thread(name: str, summary: str = None, db_path: Path = DB_PATH) -> int:
    """Create a new thread. Returns thread_id."""
    conn = _connect(db_path)
    cursor = conn.execute(
        "INSERT INTO threads (name, summary, last_updated) "
        "VALUES (?, ?, CURRENT_TIMESTAMP)",
        (name, summary),
    )
    thread_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return thread_id


def get_recent_summaries(n: int = 3, db_path: Path = DB_PATH) -> list[dict]:
    """Get the N most recent session summaries."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT session_id, content, created_at FROM summaries "
        "ORDER BY created_at DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_last_session_time(db_path: Path = DB_PATH) -> str | None:
    """Get the started_at timestamp of the most recent previous session."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT started_at FROM sessions ORDER BY id DESC LIMIT 2"
    ).fetchall()
    conn.close()
    if len(rows) >= 2:
        return rows[1]["started_at"]
    return None


def get_recent_observations(n: int = 10, db_path: Path = DB_PATH) -> list[dict]:
    """Get the N most recent observations."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT id, content, created_at, incorporated FROM observations "
        "ORDER BY created_at DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_companion_turns(n: int = 5, db_path: Path = DB_PATH) -> list[str]:
    """Get the N most recent agent turn contents."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT content FROM turns WHERE role = 'agent' "
        "ORDER BY timestamp DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [r["content"] for r in rows]


def mark_observation_incorporated(obs_id: int, db_path: Path = DB_PATH):
    """Mark an observation as incorporated (reviewed and still holds)."""
    conn = _connect(db_path)
    conn.execute(
        "UPDATE observations SET incorporated = 1 WHERE id = ?",
        (obs_id,),
    )
    conn.commit()
    conn.close()


def retire_observation(obs_id: int, db_path: Path = DB_PATH):
    """Delete an observation that no longer holds."""
    conn = _connect(db_path)
    conn.execute("DELETE FROM observations WHERE id = ?", (obs_id,))
    conn.commit()
    conn.close()


def log_heartbeat(decision: str, reason: str, message: str = "",
                  db_path: Path = DB_PATH):
    """Log a heartbeat evaluation to the database."""
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO heartbeats (decision, reason, message) VALUES (?, ?, ?)",
        (decision, reason, message),
    )
    conn.commit()
    conn.close()


def get_last_interaction_time(db_path: Path = DB_PATH) -> str | None:
    """Get the timestamp of the most recent turn (any role)."""
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT timestamp FROM turns ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["timestamp"] if row else None


def log_coherence_check(score: float, degraded: bool, signals: list[str],
                        action: str = "none", db_path: Path = DB_PATH):
    """Log a SENTINEL coherence check result."""
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO coherence_checks (score, degraded, signals, action) "
        "VALUES (?, ?, ?, ?)",
        (score, degraded, json.dumps(signals), action),
    )
    conn.commit()
    conn.close()


def update_thread(thread_id: int, summary: str = None, status: str = None,
                  db_path: Path = DB_PATH):
    conn = _connect(db_path)
    updates = []
    params = []
    if summary is not None:
        updates.append("summary = ?")
        params.append(summary)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    updates.append("last_updated = CURRENT_TIMESTAMP")
    params.append(thread_id)
    conn.execute(
        f"UPDATE threads SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()
    conn.close()


# ── Sleep cycle helpers ──

def get_todays_turns(db_path: Path = DB_PATH) -> list[dict]:
    """All turns from sessions started today."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT t.id, t.session_id, t.role, t.content, t.timestamp, t.topic_tags, t.weight "
        "FROM turns t "
        "JOIN sessions s ON t.session_id = s.id "
        "WHERE date(s.started_at) = date('now') "
        "ORDER BY t.timestamp",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_todays_observations(db_path: Path = DB_PATH) -> list[dict]:
    """Observations created today."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT id, content, created_at, incorporated FROM observations "
        "WHERE date(created_at) = date('now') "
        "ORDER BY created_at",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_todays_bookmarks(db_path: Path = DB_PATH) -> list[dict]:
    """Bookmarks from today."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT id, session_id, moment, quote, created_at FROM bookmarks "
        "WHERE date(created_at) = date('now') "
        "ORDER BY created_at",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_observations_stale(older_than_days: int = 30,
                            db_path: Path = DB_PATH) -> int:
    """Flag old unreferenced observations as stale.

    Marks observations older than `older_than_days` that were never
    incorporated by prepending [stale] to their content.
    Returns the number of observations marked.
    """
    conn = _connect(db_path)
    cursor = conn.execute(
        "UPDATE observations SET content = '[stale] ' || content "
        "WHERE incorporated = 0 "
        "AND content NOT LIKE '[stale]%' "
        "AND created_at < datetime('now', ?)",
        (f"-{older_than_days} days",),
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def update_thread_summary(thread_name: str, summary: str,
                          db_path: Path = DB_PATH):
    """Update a thread's summary by name. Matches case-insensitively."""
    conn = _connect(db_path)
    cursor = conn.execute(
        "UPDATE threads SET summary = ?, last_updated = CURRENT_TIMESTAMP "
        "WHERE LOWER(name) = LOWER(?)",
        (summary, thread_name),
    )
    if cursor.rowcount == 0:
        print(f"  [memory] No thread found matching '{thread_name}' — skipped")
    conn.commit()
    conn.close()


# ── Async embedding helper ──

def _embed_async(table: str, row_id: int, text: str, db_path: Path = DB_PATH):
    """Fire-and-forget embedding in a background thread.

    Does not block the conversation pipeline.
    """
    def _do_embed():
        try:
            from core.embeddings import embed, vector_to_blob
            vec = embed(text)
            blob = vector_to_blob(vec)
            conn = _connect(db_path)
            conn.execute(
                f"UPDATE {table} SET embedding = ? WHERE id = ?",
                (blob, row_id),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"  [embed-async] Failed to embed {table}:{row_id}: {e}")

    t = threading.Thread(target=_do_embed, daemon=True)
    t.start()


# ── Vector search wrapper ──

def search_memory(query: str, n: int = 5, db_path: Path = DB_PATH) -> list[dict]:
    """Search memory using hybrid vector + keyword search.

    Wrapper around vector_search.search(). Updates activation for accessed memories.
    """
    from core.vector_search import search
    results = search(query, n=n, db_path=db_path)

    # Bump activation for accessed memories
    for r in results:
        table = r.get("_source_table")
        row_id = r.get("id")
        if table and row_id:
            update_activation(table, row_id, db_path)

    return results


def embed_and_store(table: str, row_id: int, text: str, db_path: Path = DB_PATH):
    """Embed text and update the embedding blob for a row (synchronous)."""
    from core.embeddings import embed, vector_to_blob
    vec = embed(text)
    blob = vector_to_blob(vec)
    conn = _connect(db_path)
    conn.execute(
        f"UPDATE {table} SET embedding = ? WHERE id = ?",
        (blob, row_id),
    )
    conn.commit()
    conn.close()


def update_activation(table: str, row_id: int, db_path: Path = DB_PATH):
    """Bump activation score and last_accessed when a memory is retrieved.

    Only applies to tables that have activation/last_accessed columns (observations).
    For other tables, just returns silently.
    """
    conn = _connect(db_path)
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if "activation" in cols and "last_accessed" in cols:
        # Boost activation by 0.2, capped at 1.0
        conn.execute(
            f"UPDATE {table} SET "
            f"activation = MIN(1.0, COALESCE(activation, 0.5) + 0.2), "
            f"last_accessed = CURRENT_TIMESTAMP "
            f"WHERE id = ?",
            (row_id,),
        )
        conn.commit()
    conn.close()


def decay_activations(half_life_days: int = 30, db_path: Path = DB_PATH):
    """Apply activation decay to all observations. Called from sleep cycle.

    Uses exponential decay with configurable half-life.
    Memories accessed recently stay active; old unreferenced ones fade.
    Formula: activation *= 2^(-days_since_access / half_life)
    """
    conn = _connect(db_path)
    # Get all observations with activation > 0
    rows = conn.execute(
        "SELECT id, activation, last_accessed, created_at FROM observations "
        "WHERE activation > 0.01"
    ).fetchall()

    now = datetime.now()
    decay_constant = math.log(2) / half_life_days
    updated = 0

    for row in rows:
        # Use last_accessed if available, otherwise created_at
        ref_time_str = row["last_accessed"] or row["created_at"]
        try:
            ref_time = datetime.fromisoformat(ref_time_str)
        except (ValueError, TypeError):
            continue

        days_elapsed = (now - ref_time).total_seconds() / 86400
        if days_elapsed <= 0:
            continue

        decay_factor = math.exp(-decay_constant * days_elapsed)
        new_activation = (row["activation"] or 1.0) * decay_factor

        # Clamp to minimum
        if new_activation < 0.01:
            new_activation = 0.0

        conn.execute(
            "UPDATE observations SET activation = ? WHERE id = ?",
            (new_activation, row["id"]),
        )
        updated += 1

    conn.commit()
    conn.close()
    if updated:
        print(f"  [memory] Decayed activation for {updated} observation(s)")
    return updated


# ── Entity extraction ──

# Known entity types by pattern
_PERSON_TITLES = {"mr", "mrs", "ms", "dr", "prof", "professor"}


def extract_entities(text: str, db_path: Path = DB_PATH) -> list[dict]:
    """Simple entity extraction using regex patterns.

    Catches proper nouns, quoted terms, and known entity names.
    Not ML-based — just pattern matching.
    """
    entities = []
    seen = set()

    # Pattern 1: Capitalized multi-word names (e.g., "John Smith", "The Atrophied Mind")
    for match in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text):
        name = match.group(1).strip()
        if name.lower() not in seen and len(name) > 2:
            seen.add(name.lower())
            entities.append({"name": name, "entity_type": _guess_entity_type(name)})

    # Pattern 2: Single capitalized words that aren't sentence starters
    # Look for mid-sentence proper nouns
    for match in re.finditer(r'(?<=[a-z]\s)([A-Z][a-z]{2,})\b', text):
        name = match.group(1).strip()
        if name.lower() not in seen and name.lower() not in {"the", "this", "that", "what", "when", "where", "how"}:
            seen.add(name.lower())
            entities.append({"name": name, "entity_type": "concept"})

    # Pattern 3: Quoted terms (significant enough to quote)
    for match in re.finditer(r'"([^"]{2,50})"', text):
        term = match.group(1).strip()
        if term.lower() not in seen:
            seen.add(term.lower())
            entities.append({"name": term, "entity_type": "concept"})

    # Store/update entities in DB
    conn = _connect(db_path)
    for ent in entities:
        existing = conn.execute(
            "SELECT id, mention_count FROM entities WHERE LOWER(name) = LOWER(?)",
            (ent["name"],),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE entities SET mention_count = mention_count + 1, "
                "last_seen = CURRENT_TIMESTAMP WHERE id = ?",
                (existing["id"],),
            )
            ent["id"] = existing["id"]
            ent["mention_count"] = existing["mention_count"] + 1
        else:
            cursor = conn.execute(
                "INSERT INTO entities (name, entity_type, last_seen) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (ent["name"], ent["entity_type"]),
            )
            ent["id"] = cursor.lastrowid
            ent["mention_count"] = 1
    conn.commit()
    conn.close()

    return entities


def _guess_entity_type(name: str) -> str:
    """Heuristic guess at entity type from name."""
    lower = name.lower()
    words = lower.split()
    if words[0] in _PERSON_TITLES:
        return "person"
    if any(w in lower for w in ["project", "system", "framework", "engine"]):
        return "project"
    if any(w in lower for w in ["street", "road", "city", "park", "building"]):
        return "place"
    return "concept"


def link_entities(entity_a: str, entity_b: str, relation: str = "related_to",
                  db_path: Path = DB_PATH):
    """Create or strengthen a relationship between two entities."""
    conn = _connect(db_path)

    # Get or create entity IDs
    def _get_or_create(name):
        row = conn.execute(
            "SELECT id FROM entities WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        if row:
            return row["id"]
        cursor = conn.execute(
            "INSERT INTO entities (name, entity_type, last_seen) "
            "VALUES (?, 'concept', CURRENT_TIMESTAMP)", (name,)
        )
        return cursor.lastrowid

    id_a = _get_or_create(entity_a)
    id_b = _get_or_create(entity_b)

    # Check for existing relation (in either direction)
    existing = conn.execute(
        "SELECT id, strength FROM entity_relations "
        "WHERE (entity_a = ? AND entity_b = ? AND relation = ?) "
        "OR (entity_a = ? AND entity_b = ? AND relation = ?)",
        (id_a, id_b, relation, id_b, id_a, relation),
    ).fetchone()

    if existing:
        # Strengthen existing relation (cap at 1.0)
        new_strength = min(1.0, (existing["strength"] or 0.5) + 0.1)
        conn.execute(
            "UPDATE entity_relations SET strength = ?, last_seen = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (new_strength, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO entity_relations (entity_a, entity_b, relation, last_seen) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (id_a, id_b, relation),
        )

    conn.commit()
    conn.close()


def write_bookmark(session_id: int, moment: str, quote: str = None,
                   db_path: Path = DB_PATH) -> int:
    """Create a bookmark and embed it asynchronously. Returns bookmark_id."""
    conn = _connect(db_path)
    cursor = conn.execute(
        "INSERT INTO bookmarks (session_id, moment, quote) VALUES (?, ?, ?)",
        (session_id, moment, quote),
    )
    bm_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _embed_async("bookmarks", bm_id, moment, db_path)
    return bm_id


# ── Cross-agent memory ──


def get_other_agents_recent_summaries(n_per_agent: int = 2, max_agents: int = 5,
                                       current_agent: str = None) -> list[dict]:
    """Get recent session summaries from other agents' databases.

    Returns list of {"agent": name, "display_name": str, "summaries": [...]}.
    """
    from core.agent_manager import discover_agents
    from config import _agent_data_dir

    current = current_agent or AGENT_NAME
    agents = discover_agents()
    results = []

    for agent in agents[:max_agents + 1]:
        if agent["name"] == current:
            continue
        if len(results) >= max_agents:
            break

        db_path = _agent_data_dir(agent["name"]) / "memory.db"
        if not db_path.exists():
            continue

        try:
            conn = _connect(db_path)
            rows = conn.execute(
                "SELECT s.content, s.created_at, se.mood "
                "FROM summaries s "
                "LEFT JOIN sessions se ON s.session_id = se.id "
                "ORDER BY s.created_at DESC LIMIT ?",
                (n_per_agent,),
            ).fetchall()
            conn.close()

            if rows:
                results.append({
                    "agent": agent["name"],
                    "display_name": agent["display_name"],
                    "summaries": [
                        {"content": r["content"], "created_at": r["created_at"],
                         "mood": r["mood"]}
                        for r in rows
                    ],
                })
        except Exception:
            continue

    return results


def search_other_agent_memory(agent_name: str, query: str,
                               limit: int = 10) -> dict:
    """Search another agent's turns and summaries (not observations/identity)."""
    from config import _agent_data_dir

    db_path = _agent_data_dir(agent_name) / "memory.db"
    if not db_path.exists():
        return {"error": f"Agent '{agent_name}' has no memory database."}

    try:
        conn = _connect(db_path)

        turns = conn.execute(
            "SELECT id, session_id, role, content, timestamp "
            "FROM turns WHERE content LIKE ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()

        summaries = conn.execute(
            "SELECT session_id, content, created_at "
            "FROM summaries WHERE content LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()

        conn.close()

        return {
            "agent": agent_name,
            "turns": [dict(t) for t in turns],
            "summaries": [dict(s) for s in summaries],
        }
    except Exception as e:
        return {"error": f"Failed to search {agent_name}'s memory: {e}"}
