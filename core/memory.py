"""SQLite memory layer. All database operations live here. No SQL elsewhere."""
import sqlite3
import json
from datetime import datetime
from pathlib import Path

from config import DB_PATH, SCHEMA_PATH


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = DB_PATH):
    """Create all tables from schema.sql."""
    schema = SCHEMA_PATH.read_text()
    conn = _connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()


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
               db_path: Path = DB_PATH) -> int:
    """Write a single turn. Returns turn_id."""
    conn = _connect(db_path)
    cursor = conn.execute(
        "INSERT INTO turns (session_id, role, content, topic_tags, weight) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, topic_tags, weight),
    )
    turn_id = cursor.lastrowid
    conn.commit()
    conn.close()
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
    conn.execute(
        "INSERT INTO summaries (session_id, content, topics) VALUES (?, ?, ?)",
        (session_id, content, topics),
    )
    conn.commit()
    conn.close()


def write_observation(content: str, source_turn_id: int = None,
                      db_path: Path = DB_PATH):
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO observations (content, source_turn) VALUES (?, ?)",
        (content, source_turn_id),
    )
    conn.commit()
    conn.close()


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
    """Get the N most recent companion turn contents."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT content FROM turns WHERE role = 'companion' "
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
