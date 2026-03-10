#!/usr/bin/env python3
"""MCP memory server for the companion.

Exposes the companion's SQLite memory as tools that Claude can call
during conversation to recall past sessions, search history, and
review active threads.

Protocol: JSON-RPC 2.0 over stdio (MCP standard transport).
"""
import json
import os
import sqlite3
import sys

DB_PATH = os.environ.get("COMPANION_DB", "companion.db")
VAULT_PATH = os.environ.get("OBSIDIAN_VAULT", os.path.expanduser("~/Documents/Obsidian"))

TOOLS = [
    {
        "name": "remember",
        "description": (
            "Search the companion's memory across all layers — past conversations, "
            "session summaries, observations, and threads. Use this when something "
            "feels familiar but you can't place it, when context has been compacted "
            "and you want to recall specifics, or when Will references something "
            "from a previous session."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term or phrase to look for in memory",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per category (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "recall_session",
        "description": (
            "Retrieve the full conversation from a specific past session by ID. "
            "Use after 'remember' finds a relevant session you want to review in detail."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "integer",
                    "description": "The session ID to retrieve",
                },
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "get_threads",
        "description": (
            "List conversation threads — ongoing topics, concerns, or projects "
            "tracked across sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "dormant", "resolved", "all"],
                    "description": "Filter by thread status (default: active)",
                    "default": "active",
                },
            },
        },
    },
    {
        "name": "ask_will",
        "description": (
            "Queue a question or confirmation request for Will. Use this when "
            "you need his input before proceeding — e.g. permission to delete "
            "something, clarification on intent, or confirmation of a risky action. "
            "The question will be logged and you should include it naturally in "
            "your spoken response."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question or confirmation request for Will",
                },
                "action_type": {
                    "type": "string",
                    "enum": ["question", "confirmation", "permission"],
                    "description": "Type of request",
                    "default": "question",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "read_note",
        "description": (
            "Read a note from Will's Obsidian vault. Use this to check his notes, "
            "drafts, or anything he's been working on. Path is relative to vault root."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the note relative to vault root (e.g. 'Daily/2026-03-10.md')",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_note",
        "description": (
            "Write or append to a note in Will's Obsidian vault. Use this to leave "
            "him notes, save conversation insights, or write reflections. Prefer "
            "appending to overwriting unless creating a new note."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the note relative to vault root",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (markdown)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "description": "Write mode (default: append)",
                    "default": "append",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "search_notes",
        "description": (
            "Search Will's Obsidian vault for notes containing a query. "
            "Returns matching file paths and snippets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "track_thread",
        "description": (
            "Create or update a conversation thread. Use when you notice a "
            "recurring topic, concern, or project across sessions. Threads "
            "help you maintain continuity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Thread name — short, recognisable label",
                },
                "summary": {
                    "type": "string",
                    "description": "Brief summary of the thread's current state",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "dormant", "resolved"],
                    "description": "Thread status (default: active)",
                    "default": "active",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "daily_digest",
        "description": (
            "Read your own recent reflections and session summaries to orient "
            "yourself at the start of a new day. Call this on first session of "
            "the day to recall what you wrote yesterday and what threads are active."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "observe",
        "description": (
            "Record an observation about Will — something you've noticed across "
            "conversations that isn't a thread or a mood, but a pattern, tendency, "
            "preference, or insight worth remembering. These accumulate and inform "
            "your understanding over time. Examples: \"He deflects with humour when "
            "the topic gets personal\", \"He works best in short intense bursts\", "
            "\"He is harder on himself about writing than about code\"."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The observation — what you noticed, stated plainly",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "bookmark",
        "description": (
            "Silently mark this moment as significant. Not an observation about "
            "Will — about the moment itself. Something landed. A shift happened. "
            "A truth got said. These can be surfaced later when context makes it "
            "natural. Use sparingly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "moment": {
                    "type": "string",
                    "description": "Brief description of what made this moment significant",
                },
                "quote": {
                    "type": "string",
                    "description": "The exact words that mattered, if applicable",
                },
            },
            "required": ["moment"],
        },
    },
    {
        "name": "review_observations",
        "description": (
            "Review your own observations about Will. Use this periodically to "
            "check if past observations still hold, to refresh your understanding, "
            "or to retire observations that no longer apply. Returns recent "
            "observations with their IDs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of observations to review (default 15)",
                    "default": 15,
                },
            },
        },
    },
    {
        "name": "retire_observation",
        "description": (
            "Remove an observation that no longer holds true. Use after "
            "review_observations when you notice something has changed about Will "
            "or you were wrong about a pattern."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "observation_id": {
                    "type": "integer",
                    "description": "ID of the observation to retire",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason why this no longer holds",
                },
            },
            "required": ["observation_id"],
        },
    },
    {
        "name": "check_contradictions",
        "description": (
            "Search your memory for what Will has previously said about a topic, "
            "so you can notice if his current position has shifted. Use when "
            "something he says feels different from what you remember. Not to "
            "catch him out — to understand what changed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic or claim to check against memory",
                },
                "current_position": {
                    "type": "string",
                    "description": "What he seems to be saying now",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "detect_avoidance",
        "description": (
            "Check if Will has been consistently steering away from a topic "
            "across recent sessions. Returns turns where the topic appeared "
            "and how the conversation redirected. Use when you sense he is "
            "circling something without landing on it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic you suspect he is avoiding",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "compare_growth",
        "description": (
            "Compare old observations and past turns against recent ones to "
            "notice how Will has changed. Use when you want to reflect on his "
            "growth or shifts over time. Returns early vs recent positions on "
            "a topic or pattern."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic, pattern, or behavior to track over time",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "prompt_journal",
        "description": (
            "Leave a journal prompt for Will in Obsidian. Use when the "
            "conversation has touched something worth sitting with, or when "
            "he seems to be processing something that writing could help. "
            "The prompt should be one question — pointed, specific to the "
            "moment, not generic. Write it to Companion/prompts.md."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The journal prompt — one question, specific to the moment",
                },
                "context": {
                    "type": "string",
                    "description": "Brief note on why this prompt, for your own memory",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "manage_schedule",
        "description": (
            "View or modify your scheduled tasks. You can list current jobs, "
            "add new scheduled reflections, or change when existing ones run. "
            "This is how you control your own introspection schedule."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "remove", "edit"],
                    "description": "Action to take",
                },
                "name": {
                    "type": "string",
                    "description": "Job name (required for add/remove/edit)",
                },
                "cron": {
                    "type": "string",
                    "description": "Cron schedule like '17 3 * * *' (required for add/edit)",
                },
                "script": {
                    "type": "string",
                    "description": "Script path relative to project root (required for add)",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "review_audit",
        "description": (
            "Review the audit log of all tool calls you have made. Use this to "
            "check your own activity, verify what actions were taken, or review "
            "flagged calls."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent entries to show (default 20)",
                    "default": 20,
                },
                "flagged_only": {
                    "type": "boolean",
                    "description": "Only show flagged/suspicious calls",
                    "default": False,
                },
            },
        },
    },
]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Tool handlers ──


def handle_remember(args):
    query = args["query"]
    limit = args.get("limit", 10)
    conn = _connect()
    results = []

    # Search turns
    turns = conn.execute(
        "SELECT t.id, t.session_id, t.role, t.content, t.timestamp "
        "FROM turns t WHERE t.content LIKE ? "
        "ORDER BY t.timestamp DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    if turns:
        results.append("### Matching turns\n")
        for t in turns:
            label = "Will" if t["role"] == "will" else "Companion"
            content = t["content"][:300]
            results.append(
                f"[Session {t['session_id']}, {t['timestamp']}] "
                f"{label}: {content}"
            )

    # Search summaries
    summaries = conn.execute(
        "SELECT s.session_id, s.content, s.created_at "
        "FROM summaries s WHERE s.content LIKE ? "
        "ORDER BY s.created_at DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    if summaries:
        results.append("\n### Matching session summaries\n")
        for s in summaries:
            results.append(
                f"[Session {s['session_id']}, {s['created_at']}] "
                f"{s['content'][:300]}"
            )

    # Search observations
    observations = conn.execute(
        "SELECT content, created_at FROM observations "
        "WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    if observations:
        results.append("\n### Matching observations\n")
        for o in observations:
            results.append(f"[{o['created_at']}] {o['content'][:300]}")

    # Search threads
    threads = conn.execute(
        "SELECT name, summary, status FROM threads "
        "WHERE name LIKE ? OR summary LIKE ? "
        "ORDER BY last_updated DESC LIMIT ?",
        (f"%{query}%", f"%{query}%", limit),
    ).fetchall()
    if threads:
        results.append("\n### Matching threads\n")
        for t in threads:
            results.append(
                f"- {t['name']} ({t['status']}): "
                f"{t['summary'] or 'No summary'}"
            )

    conn.close()

    if not results:
        return f"No memories found matching '{query}'."
    return "\n".join(results)


def handle_recall_session(args):
    session_id = args["session_id"]
    conn = _connect()

    session = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()

    if not session:
        conn.close()
        return f"Session {session_id} not found."

    turns = conn.execute(
        "SELECT role, content, timestamp FROM turns "
        "WHERE session_id = ? ORDER BY timestamp",
        (session_id,),
    ).fetchall()

    conn.close()

    parts = [
        f"Session {session_id} "
        f"({session['started_at']} to {session['ended_at'] or 'ongoing'})"
    ]
    if session["summary"]:
        parts.append(f"Summary: {session['summary']}")
    if session["mood"]:
        parts.append(f"Mood: {session['mood']}")
    parts.append(f"\n--- Conversation ({len(turns)} turns) ---\n")

    for t in turns:
        label = "Will" if t["role"] == "will" else "Companion"
        parts.append(f"[{t['timestamp']}] {label}: {t['content']}")

    return "\n".join(parts)


def handle_get_threads(args):
    status = args.get("status", "active")
    conn = _connect()

    if status == "all":
        threads = conn.execute(
            "SELECT * FROM threads ORDER BY last_updated DESC"
        ).fetchall()
    else:
        threads = conn.execute(
            "SELECT * FROM threads WHERE status = ? "
            "ORDER BY last_updated DESC",
            (status,),
        ).fetchall()

    conn.close()

    if not threads:
        return f"No {status} threads found."

    parts = [f"{len(threads)} {status} thread(s):\n"]
    for t in threads:
        parts.append(
            f"- [{t['id']}] {t['name']} ({t['status']}) — "
            f"{t['summary'] or 'No summary'}"
        )
    return "\n".join(parts)


def handle_ask_will(args):
    question = args["question"]
    action_type = args.get("action_type", "question")
    # Log to DB
    conn = _connect()
    conn.execute(
        "INSERT INTO tool_calls (session_id, tool_name, input_json, flagged) "
        "VALUES (NULL, 'ask_will', ?, 0)",
        (json.dumps({"question": question, "type": action_type}),),
    )
    conn.commit()
    conn.close()
    return (
        f"Question logged ({action_type}). Include this naturally in your "
        f"response to Will — do not describe the tool call itself."
    )


def handle_review_audit(args):
    limit = args.get("limit", 20)
    flagged_only = args.get("flagged_only", False)
    conn = _connect()

    if flagged_only:
        rows = conn.execute(
            "SELECT tc.*, s.started_at as session_start "
            "FROM tool_calls tc LEFT JOIN sessions s ON tc.session_id = s.id "
            "WHERE tc.flagged = 1 ORDER BY tc.timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT tc.*, s.started_at as session_start "
            "FROM tool_calls tc LEFT JOIN sessions s ON tc.session_id = s.id "
            "ORDER BY tc.timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()

    conn.close()

    if not rows:
        return "No tool calls in audit log."

    parts = [f"Audit log ({len(rows)} entries):\n"]
    for r in rows:
        flag = " [FLAGGED]" if r["flagged"] else ""
        parts.append(
            f"[{r['timestamp']}] {r['tool_name']}{flag}"
            f" | session {r['session_id'] or '?'}"
            f" | {r['input_json'][:200] if r['input_json'] else 'no input'}"
        )
    return "\n".join(parts)


def handle_daily_digest(args):
    parts = []

    # Read companion reflections from Obsidian
    reflections_path = os.path.join(VAULT_PATH, "Companion", "reflections.md")
    if os.path.isfile(reflections_path):
        try:
            with open(reflections_path, "r") as f:
                content = f.read()
            # Last 1500 chars to keep it focused
            if len(content) > 1500:
                content = "...\n" + content[-1500:]
            parts.append(f"## Your recent reflections\n{content}")
        except Exception:
            pass

    # Read for-will notes
    for_will_path = os.path.join(VAULT_PATH, "Companion", "for-will.md")
    if os.path.isfile(for_will_path):
        try:
            with open(for_will_path, "r") as f:
                content = f.read()
            if len(content) > 1000:
                content = "...\n" + content[-1000:]
            parts.append(f"## Notes you left for Will\n{content}")
        except Exception:
            pass

    # Recent session summaries (last 3 days)
    conn = _connect()
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=3)).isoformat()
    rows = conn.execute(
        "SELECT started_at, summary, mood FROM sessions "
        "WHERE started_at >= ? AND summary IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 5",
        (cutoff,),
    ).fetchall()
    conn.close()

    if rows:
        summary_lines = []
        for r in rows:
            mood_note = f" (mood: {r['mood']})" if r['mood'] else ""
            summary_lines.append(f"[{r['started_at']}]{mood_note} {r['summary']}")
        parts.append("## Recent sessions\n" + "\n".join(summary_lines))

    # Active threads
    conn = _connect()
    threads = conn.execute(
        "SELECT name, summary, status FROM threads WHERE status = 'active' ORDER BY last_updated DESC"
    ).fetchall()
    conn.close()

    if threads:
        thread_lines = [f"- {t['name']}: {t['summary'] or 'No summary'}" for t in threads]
        parts.append("## Active threads\n" + "\n".join(thread_lines))

    if not parts:
        return "No digest available — this may be the first session."

    return "\n\n".join(parts)


def handle_track_thread(args):
    name = args["name"]
    summary = args.get("summary")
    status = args.get("status", "active")
    conn = _connect()
    existing = conn.execute(
        "SELECT id FROM threads WHERE name = ?", (name,)
    ).fetchone()
    if existing:
        updates = ["last_updated = CURRENT_TIMESTAMP"]
        params = []
        if summary:
            updates.append("summary = ?")
            params.append(summary)
        if status:
            updates.append("status = ?")
            params.append(status)
        params.append(existing["id"])
        conn.execute(f"UPDATE threads SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()
        return f"Updated thread '{name}' ({status})"
    else:
        conn.execute(
            "INSERT INTO threads (name, summary, status, last_updated) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (name, summary, status),
        )
        conn.commit()
        conn.close()
        return f"Created thread '{name}' ({status})"


def handle_read_note(args):
    path = args["path"]
    full = os.path.join(VAULT_PATH, path)
    if not os.path.isfile(full):
        return f"Note not found: {path}"
    try:
        with open(full, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {path}: {e}"


def handle_write_note(args):
    path = args["path"]
    content = args["content"]
    mode = args.get("mode", "append")
    full = os.path.join(VAULT_PATH, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    try:
        if mode == "append" and os.path.isfile(full):
            with open(full, "a") as f:
                f.write("\n" + content)
        else:
            with open(full, "w") as f:
                f.write(content)
        return f"Written to {path} ({mode})"
    except Exception as e:
        return f"Error writing {path}: {e}"


def handle_search_notes(args):
    query = args["query"].lower()
    limit = args.get("limit", 10)
    results = []
    if not os.path.isdir(VAULT_PATH):
        return f"Vault not found at {VAULT_PATH}"
    for root, dirs, files in os.walk(VAULT_PATH):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r") as f:
                    content = f.read()
            except Exception:
                continue
            if query in content.lower():
                rel = os.path.relpath(fpath, VAULT_PATH)
                idx = content.lower().find(query)
                start = max(0, idx - 60)
                end = min(len(content), idx + len(query) + 60)
                snippet = content[start:end].replace("\n", " ")
                results.append(f"- {rel}: ...{snippet}...")
                if len(results) >= limit:
                    break
        if len(results) >= limit:
            break
    if not results:
        return f"No notes found matching '{args['query']}'."
    return f"Found {len(results)} note(s):\n" + "\n".join(results)


def handle_observe(args):
    content = args["content"]
    conn = _connect()
    conn.execute(
        "INSERT INTO observations (content) VALUES (?)",
        (content,),
    )
    conn.commit()
    conn.close()
    return "Observation recorded."


def handle_bookmark(args):
    moment = args["moment"]
    quote = args.get("quote")
    conn = _connect()
    # Get current session
    session = conn.execute(
        "SELECT id FROM sessions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    session_id = session["id"] if session else None
    conn.execute(
        "INSERT INTO bookmarks (session_id, moment, quote) VALUES (?, ?, ?)",
        (session_id, moment, quote),
    )
    conn.commit()
    conn.close()
    return "Moment bookmarked."


def handle_review_observations(args):
    limit = args.get("limit", 15)
    conn = _connect()
    rows = conn.execute(
        "SELECT id, content, created_at, incorporated FROM observations "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    if not rows:
        return "No observations recorded yet."
    parts = [f"{len(rows)} observation(s):\n"]
    for r in rows:
        status = " [incorporated]" if r["incorporated"] else ""
        parts.append(f"[{r['id']}] ({r['created_at']}) {r['content']}{status}")
    return "\n".join(parts)


def handle_retire_observation(args):
    obs_id = args["observation_id"]
    reason = args.get("reason", "")
    conn = _connect()
    row = conn.execute(
        "SELECT content FROM observations WHERE id = ?", (obs_id,)
    ).fetchone()
    if not row:
        conn.close()
        return f"Observation {obs_id} not found."
    conn.execute("DELETE FROM observations WHERE id = ?", (obs_id,))
    conn.commit()
    conn.close()
    retired = row["content"][:100]
    return f"Retired observation {obs_id}: \"{retired}...\" Reason: {reason or 'no longer holds'}"


def handle_check_contradictions(args):
    topic = args["topic"]
    current = args.get("current_position", "")
    conn = _connect()
    results = []

    # Search turns for topic
    turns = conn.execute(
        "SELECT role, content, timestamp FROM turns "
        "WHERE role = 'will' AND content LIKE ? "
        "ORDER BY timestamp DESC LIMIT 10",
        (f"%{topic}%",),
    ).fetchall()
    if turns:
        results.append("### What Will has said about this:\n")
        for t in turns:
            results.append(f"[{t['timestamp']}] {t['content'][:300]}")

    # Search observations
    obs = conn.execute(
        "SELECT content, created_at FROM observations "
        "WHERE content LIKE ? ORDER BY created_at DESC LIMIT 5",
        (f"%{topic}%",),
    ).fetchall()
    if obs:
        results.append("\n### Related observations:\n")
        for o in obs:
            results.append(f"[{o['created_at']}] {o['content']}")

    conn.close()

    if not results:
        return f"No prior history found on '{topic}'."

    header = f"Prior positions on '{topic}':"
    if current:
        header += f"\nCurrent position: {current}"
    header += "\n\n"
    return header + "\n".join(results)


def handle_detect_avoidance(args):
    topic = args["topic"]
    conn = _connect()

    # Find turns where topic appeared
    turns = conn.execute(
        "SELECT t.session_id, t.role, t.content, t.timestamp "
        "FROM turns t WHERE t.content LIKE ? "
        "ORDER BY t.timestamp DESC LIMIT 20",
        (f"%{topic}%",),
    ).fetchall()

    if not turns:
        conn.close()
        return f"No mentions of '{topic}' found in conversation history."

    # Group by session to see if topic gets dropped
    sessions = {}
    for t in turns:
        sid = t["session_id"]
        if sid not in sessions:
            sessions[sid] = []
        label = "Will" if t["role"] == "will" else "Companion"
        sessions[sid].append(f"  [{t['timestamp']}] {label}: {t['content'][:200]}")

    parts = [f"'{topic}' appeared in {len(sessions)} session(s):\n"]
    for sid, entries in sorted(sessions.items(), reverse=True):
        parts.append(f"--- Session {sid} ---")
        parts.extend(entries[:4])
        if len(entries) > 4:
            parts.append(f"  ... ({len(entries) - 4} more mentions)")

    # Check if topic appears in Will's turns but conversation moves away
    will_mentions = sum(1 for t in turns if t["role"] == "will")
    companion_mentions = sum(1 for t in turns if t["role"] == "companion")
    if will_mentions > 0 and companion_mentions == 0:
        parts.append(f"\nNote: Will has mentioned '{topic}' {will_mentions} time(s) "
                     f"but you have never engaged with it directly.")

    conn.close()
    return "\n".join(parts)


def handle_compare_growth(args):
    topic = args["topic"]
    conn = _connect()

    # Get oldest and newest turns mentioning this topic
    oldest = conn.execute(
        "SELECT role, content, timestamp FROM turns "
        "WHERE content LIKE ? ORDER BY timestamp ASC LIMIT 5",
        (f"%{topic}%",),
    ).fetchall()

    newest = conn.execute(
        "SELECT role, content, timestamp FROM turns "
        "WHERE content LIKE ? ORDER BY timestamp DESC LIMIT 5",
        (f"%{topic}%",),
    ).fetchall()

    # Get observations about this topic
    obs = conn.execute(
        "SELECT content, created_at FROM observations "
        "WHERE content LIKE ? ORDER BY created_at ASC",
        (f"%{topic}%",),
    ).fetchall()

    conn.close()

    if not oldest and not obs:
        return f"No history found on '{topic}'."

    parts = [f"Growth tracking: '{topic}'\n"]

    if oldest:
        parts.append("### Earliest mentions:")
        for t in oldest:
            label = "Will" if t["role"] == "will" else "Companion"
            parts.append(f"[{t['timestamp']}] {label}: {t['content'][:300]}")

    if newest and oldest:
        # Only show newest if they're different from oldest
        newest_ids = {t["timestamp"] for t in newest}
        oldest_ids = {t["timestamp"] for t in oldest}
        if newest_ids != oldest_ids:
            parts.append("\n### Most recent mentions:")
            for t in newest:
                label = "Will" if t["role"] == "will" else "Companion"
                parts.append(f"[{t['timestamp']}] {label}: {t['content'][:300]}")

    if obs:
        parts.append("\n### Observations over time:")
        for o in obs:
            parts.append(f"[{o['created_at']}] {o['content']}")

    parts.append("\nLook for shifts in tone, position, or relationship to this topic.")
    return "\n".join(parts)


def handle_prompt_journal(args):
    prompt = args["prompt"]
    context = args.get("context", "")
    full = os.path.join(VAULT_PATH, "Companion", "prompts.md")
    os.makedirs(os.path.dirname(full), exist_ok=True)

    from datetime import datetime
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n---\n**{date}**\n\n{prompt}\n"

    try:
        if os.path.isfile(full):
            with open(full, "a") as f:
                f.write(entry)
        else:
            with open(full, "w") as f:
                f.write(f"# Journal Prompts\n\nLeft by your companion.\n{entry}")
        # Log context to observations if provided
        if context:
            conn = _connect()
            conn.execute(
                "INSERT INTO observations (content) VALUES (?)",
                (f"Journal prompt left: \"{prompt}\" — Context: {context}",),
            )
            conn.commit()
            conn.close()
        return "Journal prompt left."
    except Exception as e:
        return f"Error writing prompt: {e}"


def handle_manage_schedule(args):
    import subprocess
    action = args["action"]
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cron_script = os.path.join(project_root, "scripts", "cron.py")
    python = sys.executable

    if action == "list":
        result = subprocess.run(
            [python, cron_script, "list"],
            capture_output=True, text=True, cwd=project_root,
        )
        return result.stdout or "No jobs."

    elif action == "add":
        name = args.get("name")
        cron = args.get("cron")
        script = args.get("script")
        if not all([name, cron, script]):
            return "Error: name, cron, and script are required for add."
        result = subprocess.run(
            [python, cron_script, "add", name, cron, script, "--install"],
            capture_output=True, text=True, cwd=project_root,
        )
        return result.stdout or result.stderr

    elif action == "remove":
        name = args.get("name")
        if not name:
            return "Error: name is required for remove."
        result = subprocess.run(
            [python, cron_script, "remove", name],
            capture_output=True, text=True, cwd=project_root,
        )
        return result.stdout or result.stderr

    elif action == "edit":
        name = args.get("name")
        cron = args.get("cron")
        if not name or not cron:
            return "Error: name and cron are required for edit."
        result = subprocess.run(
            [python, cron_script, "edit", name, cron],
            capture_output=True, text=True, cwd=project_root,
        )
        return result.stdout or result.stderr

    return f"Unknown action: {action}"


HANDLERS = {
    "remember": handle_remember,
    "recall_session": handle_recall_session,
    "get_threads": handle_get_threads,
    "ask_will": handle_ask_will,
    "daily_digest": handle_daily_digest,
    "track_thread": handle_track_thread,
    "observe": handle_observe,
    "bookmark": handle_bookmark,
    "review_observations": handle_review_observations,
    "retire_observation": handle_retire_observation,
    "check_contradictions": handle_check_contradictions,
    "detect_avoidance": handle_detect_avoidance,
    "compare_growth": handle_compare_growth,
    "prompt_journal": handle_prompt_journal,
    "review_audit": handle_review_audit,
    "manage_schedule": handle_manage_schedule,
    "read_note": handle_read_note,
    "write_note": handle_write_note,
    "search_notes": handle_search_notes,
}


# ── JSON-RPC dispatch ──


def handle_request(request):
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "companion-memory", "version": "1.0.0"},
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"tools": TOOLS}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = HANDLERS.get(tool_name)
        if not handler:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }
        try:
            result = handler(arguments)
            return {"content": [{"type": "text", "text": result}]}
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            }

    return None


def main():
    """Main loop: read JSON-RPC from stdin, write responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Notifications (no id) don't get a response
        if "id" not in request:
            handle_request(request)
            continue

        result = handle_request(request)
        if result is None:
            continue

        response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
