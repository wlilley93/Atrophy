"""Usage and activity tracking across agents.

Logs inference calls to a per-agent usage_log table.
Queries tool_calls, heartbeats, and usage across all agent databases
for the settings modal's Usage and Activity tabs.
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def _ensure_table(db_path: Path):
    """Create usage_log table if it doesn't exist."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
            source      TEXT NOT NULL,
            tokens_in   INTEGER DEFAULT 0,
            tokens_out  INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            tool_count  INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def log_usage(db_path: Path, source: str, tokens_in: int = 0,
              tokens_out: int = 0, duration_ms: int = 0,
              tool_count: int = 0):
    """Log a usage event (inference call)."""
    _ensure_table(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO usage_log (source, tokens_in, tokens_out, duration_ms, tool_count) "
        "VALUES (?, ?, ?, ?, ?)",
        (source, tokens_in, tokens_out, duration_ms, tool_count),
    )
    conn.commit()
    conn.close()


def get_usage_summary(db_path: Path, days: int = None) -> dict:
    """Get aggregated usage stats for one agent."""
    _ensure_table(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    where = ""
    params = []
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        where = "WHERE timestamp >= ?"
        params = [cutoff]

    row = conn.execute(f"""
        SELECT
            COUNT(*) as total_calls,
            COALESCE(SUM(tokens_in), 0) as total_tokens_in,
            COALESCE(SUM(tokens_out), 0) as total_tokens_out,
            COALESCE(SUM(duration_ms), 0) as total_duration_ms,
            COALESCE(SUM(tool_count), 0) as total_tools
        FROM usage_log {where}
    """, params).fetchone()

    sources = conn.execute(f"""
        SELECT source, COUNT(*) as calls,
               COALESCE(SUM(tokens_in), 0) as tokens_in,
               COALESCE(SUM(tokens_out), 0) as tokens_out,
               COALESCE(SUM(duration_ms), 0) as duration_ms
        FROM usage_log {where}
        GROUP BY source
        ORDER BY calls DESC
    """, params).fetchall()

    conn.close()

    return {
        "total_calls": row["total_calls"],
        "total_tokens_in": row["total_tokens_in"],
        "total_tokens_out": row["total_tokens_out"],
        "total_tokens": row["total_tokens_in"] + row["total_tokens_out"],
        "total_duration_ms": row["total_duration_ms"],
        "total_tools": row["total_tools"],
        "by_source": [dict(s) for s in sources],
    }


def get_all_agents_usage(days: int = None) -> list[dict]:
    """Get usage summaries across all agents."""
    from config import USER_DATA

    agents_dir = USER_DATA / "agents"
    if not agents_dir.exists():
        return []

    results = []
    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        db_path = agent_dir / "data" / "memory.db"
        if not db_path.exists():
            continue

        # Load display name from manifest
        manifest_path = agent_dir / "data" / "agent.json"
        display_name = agent_dir.name.replace("_", " ").title()
        try:
            import json
            manifest = json.loads(manifest_path.read_text())
            display_name = manifest.get("display_name", display_name)
        except Exception:
            pass

        summary = get_usage_summary(db_path, days)
        summary["agent_name"] = agent_dir.name
        summary["display_name"] = display_name
        results.append(summary)

    return results


def get_all_activity(days: int = 7, limit: int = 500) -> list[dict]:
    """Query tool_calls + heartbeats across all agent databases."""
    from config import USER_DATA

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    all_items = []

    agents_dir = USER_DATA / "agents"
    if not agents_dir.exists():
        return []

    for agent_dir in agents_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        db_path = agent_dir / "data" / "memory.db"
        if not db_path.exists():
            continue

        agent_name = agent_dir.name
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Tool calls
        try:
            rows = conn.execute(
                "SELECT timestamp, tool_name, input_json, flagged "
                "FROM tool_calls WHERE timestamp >= ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            for r in rows:
                all_items.append({
                    "agent": agent_name,
                    "category": "tool_call",
                    "timestamp": r["timestamp"],
                    "action": r["tool_name"],
                    "detail": r["input_json"] or "",
                    "flagged": bool(r["flagged"]),
                })
        except sqlite3.OperationalError:
            pass

        # Heartbeats
        try:
            rows = conn.execute(
                "SELECT timestamp, decision, reason, message "
                "FROM heartbeats WHERE timestamp >= ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            for r in rows:
                detail = r["reason"] or ""
                if r["message"]:
                    detail += f"\n{r['message']}"
                all_items.append({
                    "agent": agent_name,
                    "category": "heartbeat",
                    "timestamp": r["timestamp"],
                    "action": r["decision"],
                    "detail": detail.strip(),
                    "flagged": False,
                })
        except sqlite3.OperationalError:
            pass

        # Usage log (inference calls)
        try:
            rows = conn.execute(
                "SELECT timestamp, source, tokens_in, tokens_out, duration_ms, tool_count "
                "FROM usage_log WHERE timestamp >= ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            for r in rows:
                tok_in = r["tokens_in"] or 0
                tok_out = r["tokens_out"] or 0
                dur = r["duration_ms"] or 0
                detail = f"~{tok_in + tok_out:,} tokens ({tok_in:,} in, {tok_out:,} out)"
                if dur:
                    detail += f" | {dur / 1000:.1f}s"
                if r["tool_count"]:
                    detail += f" | {r['tool_count']} tools"
                all_items.append({
                    "agent": agent_name,
                    "category": "inference",
                    "timestamp": r["timestamp"],
                    "action": r["source"],
                    "detail": detail,
                    "flagged": False,
                })
        except sqlite3.OperationalError:
            pass

        conn.close()

    all_items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return all_items[:limit]


def format_tokens(n: int) -> str:
    """Human-readable token count."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def format_duration(ms: int) -> str:
    """Human-readable duration."""
    if ms >= 3_600_000:
        return f"{ms / 3_600_000:.1f}h"
    if ms >= 60_000:
        return f"{ms / 60_000:.0f}m"
    if ms >= 1_000:
        return f"{ms / 1_000:.0f}s"
    return f"{ms}ms"
