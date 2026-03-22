#!/usr/bin/env python3
"""MCP memory server for the companion.

Exposes the companion's SQLite memory as tools that Claude can call
during conversation to recall past sessions, search history, and
review active threads.

Protocol: JSON-RPC 2.0 over stdio (MCP standard transport).
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

_version_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")
if os.path.exists(_version_file):
    with open(_version_file, "r", encoding="utf-8") as f:
        _APP_VERSION = f.read().strip()
else:
    _APP_VERSION = "0.0.0"

DB_PATH = os.environ.get("COMPANION_DB", "companion.db")
DATA_DIR = os.path.dirname(DB_PATH)  # agents/<name>/data/
AGENT_NAME = os.environ.get("AGENT", "companion")

# Resolve display name from agent manifest
def _resolve_display_name():
    try:
        import json as _json
        manifest_path = os.path.join(DATA_DIR, "agent.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                return _json.load(f).get("display_name", AGENT_NAME.title())
    except Exception:
        pass
    return AGENT_NAME.title()

AGENT_DISPLAY_NAME = _resolve_display_name()

# Resolve user name from agent manifest
def _resolve_user_name():
    try:
        import json as _json
        manifest_path = os.path.join(DATA_DIR, "agent.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                return _json.load(f).get("user_name", "User")
    except Exception:
        pass
    return "User"

USER_NAME = _resolve_user_name()

VAULT_PATH = os.environ.get("OBSIDIAN_VAULT", os.path.expanduser("~/Documents/Obsidian"))
AGENT_DIR = os.environ.get("OBSIDIAN_AGENT_DIR", os.path.join(VAULT_PATH, "Projects", "The Atrophied Mind", "Agent Workspace", "companion"))
AGENT_NOTES = os.environ.get("OBSIDIAN_AGENT_NOTES", AGENT_DIR)

# ── Docs path resolution ──
# Docs ship with the bundle (repo or ~/.atrophy/src/)
def _resolve_docs_dir():
    """Find the docs directory - bundle first, then user data."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundle_docs = os.path.join(project_root, "docs")
    if os.path.isdir(bundle_docs):
        return bundle_docs
    # Fallback: ~/.atrophy/src/docs (installed app)
    atrophy_docs = os.path.join(os.path.expanduser("~"), ".atrophy", "src", "docs")
    if os.path.isdir(atrophy_docs):
        return atrophy_docs
    return None

DOCS_DIR = _resolve_docs_dir()

# Switchboard file-based message queue
# The Electron app polls this file and processes envelopes via the switchboard.
SWITCHBOARD_QUEUE = os.path.join(os.path.expanduser("~"), ".atrophy", ".switchboard_queue.json")

TOOLS = [
    # ── Group 1: memory - Core recall and search ──
    {
        "name": "memory",
        "description": (
            "Search and recall from memory. Actions: remember (keyword search across "
            "conversations, summaries, observations, threads), recall_session (full session "
            "by ID), recall_other_agent (search another agent's history), search_similar "
            "(semantic vector search), daily_digest (orient at day start)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["remember", "recall_session", "recall_other_agent", "search_similar", "daily_digest"],
                },
                "query": {"type": "string", "description": "Search term (for remember, recall_other_agent, search_similar)"},
                "session_id": {"type": "integer", "description": "Session ID (for recall_session)"},
                "agent": {"type": "string", "description": "Agent name (for recall_other_agent)"},
                "text": {"type": "string", "description": "Text for semantic search (for search_similar)"},
                "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
            },
            "required": ["action"],
        },
    },
    # ── Group 2: threads - Thread and schedule management ──
    {
        "name": "threads",
        "description": (
            "Manage conversation threads, schedules, and reminders. Actions: get_threads "
            "(list threads by status), track_thread (create/update thread), manage_schedule "
            "(view/modify scheduled jobs - pass schedule_action for sub-action), set_reminder "
            "(timed reminder), create_task (recurring scheduled task)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get_threads", "track_thread", "manage_schedule", "set_reminder", "create_task"],
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "dormant", "resolved", "all"],
                    "description": "Thread status filter (get_threads)",
                },
                "name": {"type": "string", "description": "Thread/task/job name"},
                "summary": {"type": "string", "description": "Thread summary (track_thread)"},
                "time": {"type": "string", "description": "ISO datetime (set_reminder)"},
                "message": {"type": "string", "description": "Reminder message (set_reminder)"},
                "prompt": {"type": "string", "description": "Task prompt (create_task)"},
                "cron": {"type": "string", "description": "Cron schedule (manage_schedule, create_task)"},
                "script": {"type": "string", "description": "Script path (manage_schedule add)"},
                "deliver": {
                    "type": "string",
                    "enum": ["message_queue", "telegram", "notification", "obsidian"],
                },
                "voice": {"type": "boolean"},
                "sources": {"type": "array", "items": {"type": "string"}},
                "schedule_action": {
                    "type": "string",
                    "enum": ["list", "add", "remove", "edit"],
                    "description": "Sub-action for manage_schedule",
                },
            },
            "required": ["action"],
        },
    },
    # ── Group 3: reflect - Observations and introspection ──
    {
        "name": "reflect",
        "description": (
            "Observe patterns, track growth, and reflect. Actions: observe (record a "
            "pattern/insight about the user), bookmark (mark a moment as significant), "
            "review_observations (read back observations), retire_observation (remove "
            "outdated observation), check_contradictions (compare past vs current positions), "
            "detect_avoidance (check if user avoids a topic), compare_growth (track change "
            "over time), prompt_journal (leave a journal prompt in Obsidian)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "observe", "bookmark", "review_observations", "retire_observation",
                        "check_contradictions", "detect_avoidance", "compare_growth", "prompt_journal",
                    ],
                },
                "content": {"type": "string", "description": "Observation content (observe)"},
                "moment": {"type": "string", "description": "Moment description (bookmark)"},
                "quote": {"type": "string", "description": "Exact words (bookmark)"},
                "observation_id": {"type": "integer", "description": "ID to retire (retire_observation)"},
                "reason": {"type": "string", "description": "Why retiring (retire_observation)"},
                "topic": {"type": "string", "description": "Topic to check (check_contradictions, detect_avoidance, compare_growth)"},
                "current_position": {"type": "string", "description": "Current stance (check_contradictions)"},
                "prompt": {"type": "string", "description": "Journal prompt text (prompt_journal)"},
                "context": {"type": "string", "description": "Why this prompt (prompt_journal)"},
                "limit": {"type": "integer", "default": 15},
            },
            "required": ["action"],
        },
    },
    # ── Group 4: notes - Obsidian vault and docs ──
    {
        "name": "notes",
        "description": (
            "Read, write, and search notes in Obsidian vault and system docs. Actions: "
            "read_note (read vault note by path), write_note (write/append to vault note), "
            "search_notes (search vault), read_docs (read system doc), search_docs (search "
            "system docs), list_docs (list all docs)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read_note", "write_note", "search_notes", "read_docs", "search_docs", "list_docs"],
                },
                "path": {"type": "string", "description": "Note/doc path (relative)"},
                "content": {"type": "string", "description": "Content to write (write_note)"},
                "mode": {"type": "string", "enum": ["overwrite", "append"], "default": "append"},
                "query": {"type": "string", "description": "Search term"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["action"],
        },
    },
    # ── Group 5: interact - User interaction and agents ──
    {
        "name": "interact",
        "description": (
            "Interact with the user and manage agents. Actions: ask_user (ask question/"
            "get confirmation/secure input), send_telegram (send Telegram message), "
            "defer_to_agent (hand off to another agent), create_agent (create new agent), "
            "update_emotional_state (adjust emotions), update_trust (adjust trust domain)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "ask_user", "send_telegram", "defer_to_agent",
                        "create_agent", "update_emotional_state", "update_trust",
                    ],
                },
                "question": {"type": "string"},
                "action_type": {
                    "type": "string",
                    "enum": ["question", "confirmation", "permission", "secure_input"],
                },
                "input_type": {
                    "type": "string",
                    "enum": ["password", "email", "url", "number", "text"],
                },
                "label": {"type": "string"},
                "destination": {"type": "string"},
                "message": {"type": "string"},
                "reason": {"type": "string"},
                "target": {"type": "string"},
                "context": {"type": "string"},
                "user_question": {"type": "string"},
                "config": {"type": "object"},
                "deltas": {"type": "object"},
                "domain": {
                    "type": "string",
                    "enum": ["emotional", "intellectual", "creative", "practical"],
                },
                "delta": {"type": "number"},
            },
            "required": ["action"],
        },
    },
    # ── Group 6: switchboard - Inter-agent and channel messaging ──
    {
        "name": "switchboard",
        "description": (
            "Send messages through the central switchboard to other agents, "
            "channels, or the system. Actions: send_message (send to a specific "
            "address), broadcast (send to all agents), query_status (check "
            "switchboard state), route_response (redirect your response to a "
            "different channel)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["send_message", "broadcast", "query_status", "route_response"],
                },
                "to": {"type": "string", "description": "Destination address (e.g. agent:companion, telegram:xan, system)"},
                "text": {"type": "string", "description": "Message text"},
                "priority": {"type": "string", "enum": ["normal", "high", "system"], "default": "normal"},
                "reply_to": {"type": "string", "description": "Where responses should go (defaults to your channel)"},
                "channel": {"type": "string", "description": "Target channel for route_response (e.g. desktop:xan, telegram:xan)"},
            },
            "required": ["action"],
        },
    },
    # ── Group 7: display - Visual and UI tools ──
    {
        "name": "display",
        "description": (
            "Visual output - canvas, timers, avatars, artefacts. Actions: render_canvas "
            "(show HTML in canvas), render_memory_graph (visualize threads), set_timer "
            "(countdown timer), add_avatar_loop (new avatar expression), create_artefact "
            "(interactive visual/image/video)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["render_canvas", "render_memory_graph", "set_timer", "add_avatar_loop", "create_artefact"],
                },
                "html": {"type": "string"},
                "focus": {"type": "string"},
                "seconds": {"type": "integer"},
                "label": {"type": "string"},
                "name": {"type": "string"},
                "prompt": {"type": "string"},
                "agent": {"type": "string"},
                "type": {"type": "string", "enum": ["html", "image", "video"]},
                "description": {"type": "string"},
                "content": {"type": "string"},
                "model": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
            "required": ["action"],
        },
    },
    # ── Group 8: tools - Custom tool management ──
    {
        "name": "tools",
        "description": (
            "Manage custom tools. Actions: create_tool (create new tool with handler), "
            "list_tools (list custom tools), edit_tool (modify existing tool), "
            "delete_tool (remove tool)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create_tool", "list_tools", "edit_tool", "delete_tool"],
                },
                "name": {"type": "string"},
                "description": {"type": "string"},
                "input_schema": {"type": "object"},
                "handler_code": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    # ── Standalone tools (too unique to group) ──
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
    {
        "name": "self_status",
        "description": (
            "Get a full snapshot of your current state - who you are, what tools "
            "you have, your scheduled jobs, emotional state, active threads, "
            "session history, and configuration. Use this to orient yourself or "
            "when you need to understand what you're capable of."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    # ── Group 9: mcp - MCP server self-service ──
    {
        "name": "mcp",
        "description": (
            "Manage MCP servers at runtime. Actions: list_servers (discover all available "
            "MCP servers and which are active for you), activate_server (enable an MCP "
            "server for yourself), deactivate_server (disable an MCP server), "
            "scaffold_server (create a new custom MCP server from a specification)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_servers", "activate_server", "deactivate_server", "scaffold_server"],
                },
                "server_name": {"type": "string", "description": "Server name (for activate/deactivate)"},
                "agent": {"type": "string", "description": "Target agent name (optional - defaults to self. Requires system_access to target other agents)."},
                "name": {"type": "string", "description": "New server name - lowercase, underscores (for scaffold_server)"},
                "description": {"type": "string", "description": "What the server does (for scaffold_server)"},
                "tools": {
                    "type": "array",
                    "description": "Tool definitions for scaffold_server",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Tool name"},
                            "description": {"type": "string", "description": "Tool description"},
                            "parameters": {
                                "type": "object",
                                "description": "Parameter definitions - keys are param names, values have type and description",
                            },
                        },
                        "required": ["name", "description"],
                    },
                },
            },
            "required": ["action"],
        },
    },
    # ── Group 10: org - Organization management ──
    {
        "name": "org",
        "description": (
            "Manage agent organizations. Actions: create_org (create a new org), "
            "dissolve_org (remove an org and unassign all agents), list_orgs (list "
            "all orgs), get_org_detail (full org info with roster), add_agent (add "
            "or assign an agent to an org), remove_agent (unassign an agent from "
            "its org), restructure (batch-update roles and reporting lines), "
            "set_purpose (update an org's purpose statement). "
            "All actions require can_provision access."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create_org", "dissolve_org", "list_orgs", "get_org_detail",
                        "add_agent", "remove_agent", "restructure", "set_purpose",
                    ],
                },
                "name": {"type": "string", "description": "Org display name (create_org)"},
                "slug": {"type": "string", "description": "Org slug identifier (dissolve_org, get_org_detail, add_agent, set_purpose)"},
                "org_type": {
                    "type": "string",
                    "enum": ["government", "company", "creative", "utility"],
                    "description": "Organization type (create_org)",
                },
                "purpose": {"type": "string", "description": "Org purpose statement (create_org, set_purpose)"},
                "agent": {"type": "string", "description": "Agent name (add_agent, remove_agent)"},
                "role": {"type": "string", "description": "Agent's role in the org (add_agent)"},
                "tier": {"type": "integer", "description": "Agent's tier level (add_agent)"},
                "reports_to": {"type": "string", "description": "Agent this agent reports to (add_agent)"},
                "changes": {
                    "type": "object",
                    "description": "Map of {agent_name: {role, reports_to}} for batch restructure",
                },
            },
            "required": ["action"],
        },
    },
]

# ── Custom tool loading ──

_CUSTOM_TOOLS_DIR = os.path.join(
    os.path.expanduser("~"), ".atrophy", "agents", AGENT_NAME, "tools"
)

# Reserved tool names that can't be overridden
_RESERVED_TOOLS = {t["name"] for t in TOOLS}


def _load_custom_tools():
    """Discover and load agent-created tools from the custom tools directory."""
    if not os.path.isdir(_CUSTOM_TOOLS_DIR):
        return
    for tool_dir in sorted(Path(_CUSTOM_TOOLS_DIR).iterdir()):
        if not tool_dir.is_dir():
            continue
        definition = tool_dir / "tool.json"
        handler = tool_dir / "handler.py"
        if not definition.exists() or not handler.exists():
            continue
        try:
            tool_def = json.loads(definition.read_text())
            name = tool_def.get("name", tool_dir.name)
            if name in _RESERVED_TOOLS:
                continue  # Can't override built-in tools
            # Add a prefix to avoid collisions in the MCP namespace
            tool_def["name"] = f"custom_{name}" if not name.startswith("custom_") else name
            TOOLS.append(tool_def)
            # Create a handler that runs the script as subprocess
            _register_custom_handler(tool_def["name"], str(handler))
        except (json.JSONDecodeError, OSError):
            continue


def _register_custom_handler(tool_name: str, handler_path: str):
    """Register a subprocess-based handler for a custom tool."""
    import subprocess as _sp

    def _handler(args):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            result = _sp.run(
                [sys.executable, handler_path, json.dumps(args)],
                capture_output=True, text=True, timeout=30,
                cwd=project_root,
                env={
                    **os.environ,
                    "AGENT": AGENT_NAME,
                    "COMPANION_DB": DB_PATH,
                    "PYTHONPATH": project_root,
                },
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()[:500]
                return f"Tool error (exit {result.returncode}): {stderr}"
            return result.stdout.strip() or "(no output)"
        except _sp.TimeoutExpired:
            return "Error: tool execution timed out (30s limit)"
        except Exception as e:
            return f"Error running tool: {e}"

    HANDLERS[tool_name] = _handler


# NOTE: _load_custom_tools() is called after HANDLERS dict is defined (below)

# Rate limit tracking for Telegram sends
_telegram_sends_today: list[str] = []  # timestamps of sends today
_TELEGRAM_DAILY_LIMIT = 5


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Provision access check ──


def _has_provision_access():
    """Check if the calling agent has org.can_provision in its manifest."""
    try:
        manifest_path = os.path.join(DATA_DIR, "agent.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            return manifest.get("org", {}).get("can_provision", False)
    except Exception:
        pass
    return False


# ── Tool handlers ──


def handle_remember(args):
    query = args["query"]
    limit = args.get("limit", 10)

    # Try hybrid vector + keyword search first
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, project_root)
        from core.memory import search_memory
        vector_results = search_memory(query, n=limit, db_path=DB_PATH)
        if vector_results:
            results = [f"### Memory search results ({len(vector_results)} matches)\n"]
            for r in vector_results:
                table = r.get("_source_table", "?")
                score = r.get("_score", 0)
                if table == "turns":
                    label = USER_NAME if r.get("role") == "will" else AGENT_DISPLAY_NAME
                    content = (r.get("content") or "")[:300]
                    results.append(
                        f"[{table} | session {r.get('session_id', '?')}, "
                        f"{r.get('timestamp', '?')} | relevance: {score:.2f}] "
                        f"{label}: {content}"
                    )
                elif table == "summaries":
                    content = (r.get("content") or "")[:300]
                    results.append(
                        f"[summary | session {r.get('session_id', '?')}, "
                        f"{r.get('created_at', '?')} | relevance: {score:.2f}] "
                        f"{content}"
                    )
                elif table == "observations":
                    content = (r.get("content") or "")[:300]
                    conf = r.get("confidence", 0.5)
                    act = r.get("activation", 1.0)
                    results.append(
                        f"[observation | {r.get('created_at', '?')} | "
                        f"relevance: {score:.2f} | confidence: {conf:.1f} | "
                        f"activation: {act:.2f}] {content}"
                    )
                elif table == "bookmarks":
                    moment = (r.get("moment") or "")[:300]
                    results.append(
                        f"[bookmark | {r.get('created_at', '?')} | "
                        f"relevance: {score:.2f}] {moment}"
                    )
                else:
                    content = str(r)[:300]
                    results.append(f"[{table} | relevance: {score:.2f}] {content}")
            return "\n".join(results)
    except Exception as e:
        # Fall through to keyword search if vector search fails
        print(f"  [remember] Vector search failed, falling back to keyword: {e}", file=sys.stderr)

    # Fallback: original keyword search
    conn = _connect()
    results = []

    turns = conn.execute(
        "SELECT t.id, t.session_id, t.role, t.content, t.timestamp "
        "FROM turns t WHERE t.content LIKE ? "
        "ORDER BY t.timestamp DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    if turns:
        results.append("### Matching turns\n")
        for t in turns:
            label = USER_NAME if t["role"] == "will" else AGENT_DISPLAY_NAME
            content = t["content"][:300]
            results.append(
                f"[Session {t['session_id']}, {t['timestamp']}] "
                f"{label}: {content}"
            )

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

    observations = conn.execute(
        "SELECT content, created_at FROM observations "
        "WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    if observations:
        results.append("\n### Matching observations\n")
        for o in observations:
            results.append(f"[{o['created_at']}] {o['content'][:300]}")

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
        "SELECT id, started_at, ended_at, summary, mood, notable, cli_session_id "
        "FROM sessions WHERE id = ?", (session_id,)
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
        label = USER_NAME if t["role"] == "will" else AGENT_DISPLAY_NAME
        parts.append(f"[{t['timestamp']}] {label}: {t['content']}")

    return "\n".join(parts)


def handle_recall_other_agent(args):
    """Search another agent's turns and summaries."""
    agent = args.get("agent", "").strip()
    query = args.get("query", "")
    limit = args.get("limit", 10)

    if not agent:
        return "Error: agent name is required."

    # Don't search yourself
    if agent == AGENT_NAME:
        return "That's your own memory. Use 'remember' instead."

    # Validate agent exists
    bundle_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    agent_dirs = [bundle_root / "agents", Path.home() / ".atrophy" / "agents"]
    if not any((d / agent / "data" / "agent.json").exists() for d in agent_dirs):
        return f"Agent '{agent}' does not exist."

    # Resolve DB in user data
    db_path = Path.home() / ".atrophy" / "agents" / agent / "data" / "memory.db"
    if not db_path.exists():
        return f"Agent '{agent}' has no memory yet (no sessions recorded)."

    # Get display name
    display_name = agent.replace("_", " ").title()
    for d in agent_dirs:
        manifest = d / agent / "data" / "agent.json"
        if manifest.exists():
            try:
                display_name = json.loads(manifest.read_text()).get("display_name", display_name)
            except Exception:
                pass
            break

    results = []

    # Try hybrid vector + keyword search first (same engine as 'remember')
    vector_results = []
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, project_root)
        from core.memory import search_memory
        vector_results = search_memory(query, n=limit, db_path=str(db_path))
    except Exception:
        pass

    if vector_results:
        # Filter to turns and summaries only (no observations/identity)
        allowed_tables = {"turns", "summaries"}
        filtered = [r for r in vector_results if r.get("_source_table") in allowed_tables]
        if filtered:
            results.append(f"### {display_name}'s memory (semantic search)\n")
            for r in filtered:
                table = r.get("_source_table", "?")
                score = r.get("_score", 0)
                if table == "turns":
                    label = USER_NAME if r.get("role") == "will" else display_name
                    content = (r.get("content") or "")[:300]
                    results.append(
                        f"[turn | session {r.get('session_id', '?')}, "
                        f"{r.get('timestamp', '?')} | relevance: {score:.2f}] "
                        f"{label}: {content}"
                    )
                elif table == "summaries":
                    content = (r.get("content") or "")[:300]
                    results.append(
                        f"[summary | session {r.get('session_id', '?')}, "
                        f"{r.get('created_at', '?')} | relevance: {score:.2f}] "
                        f"{content}"
                    )

    # Fallback to keyword search if vector search returned nothing
    if not results:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        turns = conn.execute(
            "SELECT id, session_id, role, content, timestamp "
            "FROM turns WHERE content LIKE ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        if turns:
            results.append(f"### {display_name}'s matching turns\n")
            for t in turns:
                label = USER_NAME if t["role"] == "will" else display_name
                results.append(f"[Session {t['session_id']}, {t['timestamp']}] {label}: {t['content'][:300]}")

        summaries = conn.execute(
            "SELECT session_id, content, created_at "
            "FROM summaries WHERE content LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        if summaries:
            results.append(f"\n### {display_name}'s matching session summaries\n")
            for s in summaries:
                results.append(f"[Session {s['session_id']}, {s['created_at']}] {s['content'][:300]}")

        conn.close()

    if not results:
        return f"No matching history found in {display_name}'s memory for '{query}'."
    return "\n".join(results)


def handle_get_threads(args):
    status = args.get("status", "active")
    conn = _connect()

    if status == "all":
        threads = conn.execute(
            "SELECT id, name, last_updated, summary, status "
            "FROM threads ORDER BY last_updated DESC"
        ).fetchall()
    else:
        threads = conn.execute(
            "SELECT id, name, last_updated, summary, status "
            "FROM threads WHERE status = ? "
            "ORDER BY last_updated DESC",
            (status,),
        ).fetchall()

    conn.close()

    if not threads:
        return f"No {status} threads found."

    parts = [f"{len(threads)} {status} thread(s):\n"]
    for t in threads:
        parts.append(
            f"- [{t['id']}] {t['name']} ({t['status']}) - "
            f"{t['summary'] or 'No summary'}"
        )
    return "\n".join(parts)


def _ask_via_gui(question, action_type, timeout_secs=120, **kwargs):
    """Try to ask via the Electron GUI using file-based IPC.

    Writes a request file, polls for a response file. Returns the response
    value or None if the GUI is not running or times out.
    """
    agent = os.environ.get("AGENT", "")
    if not agent:
        return None

    user_data = os.path.expanduser("~/.atrophy")
    data_dir = os.path.join(user_data, "agents", agent, "data")
    req_path = os.path.join(data_dir, ".ask_request.json")
    resp_path = os.path.join(data_dir, ".ask_response.json")

    # Generate unique request ID
    import uuid
    import time as _time
    request_id = str(uuid.uuid4())[:8]

    # Write request
    os.makedirs(data_dir, exist_ok=True)
    req = {
        "question": question,
        "action_type": action_type,
        "request_id": request_id,
        "timestamp": int(_time.time() * 1000),
    }
    # Forward secure_input fields via kwargs
    for key in ("input_type", "label", "destination"):
        val = kwargs.get(key)
        if val is not None:
            req[key] = val
    tmp = req_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(req, f)
    os.rename(tmp, req_path)

    # Poll for response
    deadline = _time.time() + timeout_secs
    while _time.time() < deadline:
        if os.path.exists(resp_path):
            try:
                with open(resp_path) as f:
                    resp = json.load(f)
                os.unlink(resp_path)
                if resp.get("request_id") == request_id:
                    if resp.get("destination_failed"):
                        return {"_destination_failed": True}
                    return resp.get("response")
            except Exception:
                pass
        _time.sleep(1)

    # Timed out - clean up request file
    try:
        os.unlink(req_path)
    except FileNotFoundError:
        pass
    return None


def handle_ask_user(args):
    question = args["question"]
    action_type = args.get("action_type", "question")
    input_type = args.get("input_type", "password")
    label = args.get("label")
    destination = args.get("destination")

    # Log to DB (never log the actual secret value)
    conn = _connect()
    conn.execute(
        "INSERT INTO tool_calls (session_id, tool_name, input_json, flagged) "
        "VALUES (NULL, 'ask_user', ?, 0)",
        (json.dumps({"question": question, "type": action_type, "label": label}),),
    )
    conn.commit()
    conn.close()

    # Build extra kwargs for secure_input
    extra = {}
    if action_type == "secure_input":
        extra["input_type"] = input_type
        if label:
            extra["label"] = label
        if destination:
            extra["destination"] = destination

    # Try GUI first (Electron app file-based IPC)
    gui_response = _ask_via_gui(question, action_type, **extra)
    if gui_response is not None:
        # Check for destination save failure
        if isinstance(gui_response, dict) and gui_response.get("_destination_failed"):
            return (
                f"Failed to save value for {label or 'requested field'} to {destination}. "
                f"The key may not be in the allowed secrets whitelist. "
                f"Allowed secret keys: ELEVENLABS_API_KEY, FAL_KEY, TELEGRAM_BOT_TOKEN, "
                f"OPENAI_API_KEY, ANTHROPIC_API_KEY. Use config: prefix for other keys."
            )
        if action_type == "secure_input":
            # For secure_input with destination, main process handles saving.
            # Never return the secret value to the AI.
            if destination:
                return (
                    f"User provided value for {label or 'requested field'}. "
                    f"Saved to {destination}."
                )
            else:
                # No destination - return the value (user chose not to auto-save)
                return f"{USER_NAME} provided: {gui_response}"
        elif action_type in ("confirmation", "permission"):
            if gui_response is True:
                return f"{USER_NAME} approved: Yes."
            elif gui_response is False:
                return f"{USER_NAME} declined: No."
            else:
                return f"{USER_NAME} replied: {gui_response}"
        else:
            return f"{USER_NAME} replied: {gui_response}"

    # Fall back to Telegram
    # Secure input must not be sent over Telegram
    if action_type == "secure_input":
        return (
            "Secure input requested - please respond in the app. "
            "Telegram cannot be used for sensitive data."
        )

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)

    try:
        from channels.telegram import ask_confirm, ask_question

        if action_type in ("confirmation", "permission"):
            result = ask_confirm(f"\U0001f512 {question}")
            if result is True:
                return f"{USER_NAME} approved: Yes."
            elif result is False:
                return f"{USER_NAME} declined: No."
            else:
                return f"No response from {USER_NAME} (timed out after 2 minutes)."
        else:
            reply = ask_question(f"\u2753 {question}")
            if reply:
                return f"{USER_NAME} replied: {reply}"
            else:
                return f"No response from {USER_NAME} (timed out after 2 minutes)."

    except Exception as e:
        return f"Failed to reach {USER_NAME} via Telegram: {e}"


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
    reflections_path = os.path.join(AGENT_NOTES, "notes", "reflections.md")
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
    for_will_path = os.path.join(AGENT_NOTES, "notes", "for-will.md")
    if os.path.isfile(for_will_path):
        try:
            with open(for_will_path, "r") as f:
                content = f.read()
            if len(content) > 1000:
                content = "...\n" + content[-1000:]
            parts.append(f"## Notes you left for the user\n{content}")
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
        return "No digest available - this may be the first session."

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


_ATROPHY_DIR = os.path.realpath(os.path.join(os.path.expanduser("~"), ".atrophy"))

# Filenames that must never be readable through note tools - prevents credential leakage
_BLOCKED_FILENAMES = {
    ".env", "config.json", ".server_token", "server_token",
    ".credentials", "credentials.json", ".secrets",
}

def _safe_vault_path(path: str) -> str | None:
    """Resolve a path within the vault, blocking traversal attacks.

    Returns the resolved absolute path if it falls inside VAULT_PATH,
    or None if the path escapes the vault boundary.

    When VAULT_PATH points to the local agent dir (~/.atrophy/agents/<name>/),
    the ~/.atrophy block is skipped since that IS the vault.
    """
    full = os.path.realpath(os.path.join(VAULT_PATH, path))
    vault_real = os.path.realpath(VAULT_PATH)
    if not full.startswith(vault_real + os.sep) and full != vault_real:
        return None
    # Block access to ~/.atrophy/ if vault is an external Obsidian directory
    # (prevents symlink escapes). Skip this check when vault IS inside ~/.atrophy/.
    if not vault_real.startswith(_ATROPHY_DIR):
        if full.startswith(_ATROPHY_DIR + os.sep) or full == _ATROPHY_DIR:
            return None
    # Block sensitive filenames - prevents credential leakage via prompt injection
    basename = os.path.basename(full)
    if basename in _BLOCKED_FILENAMES:
        return None
    return full


def handle_read_note(args):
    path = args["path"]
    full = _safe_vault_path(path)
    if full is None:
        return f"Error: path '{path}' escapes the vault boundary."
    if not os.path.isfile(full):
        return f"Note not found: {path}"
    try:
        with open(full, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {path}: {e}"


def _make_frontmatter(path: str) -> str:
    """Generate YAML frontmatter for new Obsidian notes."""
    from datetime import datetime
    now = datetime.now()

    # Determine type and tags from path
    parts = path.lower().replace("\\", "/").split("/")
    agent_name = None
    note_type = "note"
    tags = []

    # Detect agent from path like agents/companion/notes/...
    if "agents" in parts:
        idx = parts.index("agents")
        if idx + 1 < len(parts):
            agent_name = parts[idx + 1]
            tags.append(agent_name)

    if "journal" in parts:
        note_type = "journal"
        tags.append("journal")
    elif "gifts" in path.lower():
        note_type = "gift"
        tags.append("gift")
    elif "reflections" in path.lower():
        note_type = "reflection"
        tags.append("reflection")
    else:
        tags.append("note")

    tags_str = ", ".join(tags)
    lines = [
        "---",
        f"type: {note_type}",
        f"created: {now.strftime('%Y-%m-%d')}",
        f"updated: {now.strftime('%Y-%m-%d')}",
    ]
    if agent_name:
        lines.append(f"agent: {agent_name}")
    lines.append(f"tags: [{tags_str}]")
    lines.append("---\n")
    return "\n".join(lines)


def handle_write_note(args):
    path = args["path"]
    content = args["content"]
    mode = args.get("mode", "append")
    full = _safe_vault_path(path)
    if full is None:
        return f"Error: path '{path}' escapes the vault boundary."
    os.makedirs(os.path.dirname(full), exist_ok=True)
    try:
        if mode == "append" and os.path.isfile(full):
            # Update the 'updated' timestamp in frontmatter if present
            with open(full, "r", encoding="utf-8") as f:
                existing = f.read()
            if existing.startswith("---"):
                from datetime import datetime
                today = datetime.now().strftime("%Y-%m-%d")
                import re
                existing = re.sub(
                    r"^(updated:\s*).*$",
                    f"\\1{today}",
                    existing,
                    count=1,
                    flags=re.MULTILINE,
                )
                with open(full, "w") as f:
                    f.write(existing + "\n" + content)
            else:
                with open(full, "a") as f:
                    f.write("\n" + content)
        else:
            with open(full, "w") as f:
                f.write(_make_frontmatter(path) + content)
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
        # Skip hidden dirs and block any path resolving into ~/.atrophy/
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".")
            and not os.path.realpath(os.path.join(root, d)).startswith(_ATROPHY_DIR)
        ]
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
    # Use the embedding-aware write function
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, project_root)
        from core.memory import write_observation as _write_obs
        _write_obs(content, db_path=DB_PATH)
    except Exception:
        # Fallback to direct insert if embedding pipeline unavailable
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
    conn.close()
    # Use the embedding-aware write function
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, project_root)
        from core.memory import write_bookmark
        write_bookmark(session_id, moment, quote, db_path=DB_PATH)
    except Exception:
        # Fallback to direct insert
        conn = _connect()
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
        results.append("### What the user has said about this:\n")
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
        label = USER_NAME if t["role"] == "will" else AGENT_DISPLAY_NAME
        sessions[sid].append(f"  [{t['timestamp']}] {label}: {t['content'][:200]}")

    parts = [f"'{topic}' appeared in {len(sessions)} session(s):\n"]
    for sid, entries in sorted(sessions.items(), reverse=True):
        parts.append(f"--- Session {sid} ---")
        parts.extend(entries[:4])
        if len(entries) > 4:
            parts.append(f"  ... ({len(entries) - 4} more mentions)")

    # Check if topic appears in user's turns but conversation moves away
    user_mentions = sum(1 for t in turns if t["role"] == "will")
    companion_mentions = sum(1 for t in turns if t["role"] == "agent")
    if user_mentions > 0 and companion_mentions == 0:
        parts.append(f"\nNote: {USER_NAME} has mentioned '{topic}' {user_mentions} time(s) "
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
            label = USER_NAME if t["role"] == "will" else AGENT_DISPLAY_NAME
            parts.append(f"[{t['timestamp']}] {label}: {t['content'][:300]}")

    if newest and oldest:
        # Only show newest if they're different from oldest
        newest_ids = {t["timestamp"] for t in newest}
        oldest_ids = {t["timestamp"] for t in oldest}
        if newest_ids != oldest_ids:
            parts.append("\n### Most recent mentions:")
            for t in newest:
                label = USER_NAME if t["role"] == "will" else AGENT_DISPLAY_NAME
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
    full = os.path.join(AGENT_NOTES, "notes", "journal-prompts.md")
    os.makedirs(os.path.dirname(full), exist_ok=True)

    from datetime import datetime
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n---\n**{date}**\n\n{prompt}\n"

    try:
        if os.path.isfile(full):
            with open(full, "a") as f:
                f.write(entry)
        else:
            rel = os.path.relpath(full, VAULT_PATH)
            with open(full, "w") as f:
                f.write(_make_frontmatter(rel) + f"# Journal Prompts\n\nLeft by your companion.\n{entry}")
        # Log context to observations if provided
        if context:
            conn = _connect()
            conn.execute(
                "INSERT INTO observations (content) VALUES (?)",
                (f"Journal prompt left: \"{prompt}\" - Context: {context}",),
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


def handle_set_reminder(args):
    import uuid
    from datetime import datetime

    time_str = args["time"]
    message = args["message"]

    # Validate the time
    try:
        remind_time = datetime.fromisoformat(time_str)
    except ValueError:
        return f"Invalid time format: {time_str}. Use ISO format like '2024-03-10T14:30:00'."

    now = datetime.now()
    if remind_time <= now:
        return f"That time ({time_str}) is in the past."

    # Load existing reminders
    reminders_file = os.path.join(DATA_DIR, ".reminders.json")
    reminders = []
    if os.path.isfile(reminders_file):
        try:
            with open(reminders_file, "r", encoding="utf-8") as f:
                reminders = json.loads(f.read())
        except Exception:
            reminders = []

    reminder = {
        "id": str(uuid.uuid4())[:8],
        "time": time_str,
        "message": message,
        "created_at": now.isoformat(),
    }
    reminders.append(reminder)

    with open(reminders_file, "w") as f:
        f.write(json.dumps(reminders, indent=2) + "\n")

    # Calculate time until
    delta = remind_time - now
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    if hours > 0:
        eta = f"{hours}h {minutes}m"
    else:
        eta = f"{minutes}m"

    return f"Reminder set for {time_str} ({eta} from now): {message}"


def handle_set_timer(args):
    """Write a timer request for the GUI to pick up."""
    seconds = args["seconds"]
    label = args.get("label", "Timer")

    if seconds <= 0:
        return "Timer duration must be positive."
    if seconds > 86400:
        return "Maximum timer duration is 24 hours."

    timer_file = os.path.join(DATA_DIR, ".timer_request.json")
    with open(timer_file, "w") as f:
        json.dump({"seconds": seconds, "label": label}, f)

    # Format for display
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        display = f"{h}h {m}m" if m else f"{h}h"
    elif seconds >= 60:
        m = seconds // 60
        s = seconds % 60
        display = f"{m}m {s}s" if s else f"{m}m"
    else:
        display = f"{seconds}s"

    return f"Timer set: {label} - {display}"


def handle_create_task(args):
    """Create a task definition in Obsidian and schedule it via cron."""
    import re
    import shlex
    import subprocess

    name = _sanitise_name(args["name"])
    if not name:
        return "Error: task name must contain at least one alphanumeric character."
    prompt = args["prompt"]
    cron = args["cron"]
    deliver = args.get("deliver", "message_queue")
    voice = args.get("voice", True)
    sources = args.get("sources", [])

    # Validate cron expression - must be 5 space-separated fields of [0-9*/,-]
    cron_parts = cron.strip().split()
    if len(cron_parts) != 5 or not all(re.match(r'^[0-9*/,-]+$', p) for p in cron_parts):
        return "Error: invalid cron expression. Expected 5 fields (minute hour day month weekday)."

    # Write task definition to Obsidian
    tasks_dir = os.path.join(AGENT_DIR, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    task_path = os.path.join(tasks_dir, f"{name}.md")

    # Build frontmatter
    lines = ["---"]
    lines.append(f"deliver: {deliver}")
    lines.append(f"voice: {'true' if voice else 'false'}")
    if sources:
        lines.append("sources:")
        for s in sources:
            lines.append(f"  - {s}")
    lines.append("---")
    lines.append("")
    lines.append(prompt)

    with open(task_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    # Schedule via cron
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cron_script = os.path.join(project_root, "scripts", "cron.py")
    task_runner = os.path.join(
        project_root, "scripts", "agents", AGENT_NAME, "run_task.py"
    )

    # The script argument needs the task name appended
    # cron.py stores the full command, so we use a wrapper approach
    script_with_arg = f"{shlex.quote(task_runner)} {shlex.quote(name)}"

    result = subprocess.run(
        [sys.executable, cron_script, "add", f"task-{name}", cron, script_with_arg, "--install"],
        capture_output=True, text=True,
        cwd=project_root,
    )

    output = result.stdout or result.stderr
    return f"Task '{name}' created.\nDefinition: {task_path}\nSchedule: {cron}\n{output}"


def _sanitise_name(raw: str) -> str:
    """Sanitise a user-provided name to safe filesystem/CLI characters."""
    import re
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", raw.strip())
    if not safe or not re.match(r'^[a-zA-Z0-9_-]+$', safe):
        return ""
    return safe


def handle_add_avatar_loop(args):
    """Generate a new loop segment via Kling and add to ambient rotation."""
    import subprocess

    name = _sanitise_name(args["name"])
    if not name:
        return "Error: loop name must contain at least one alphanumeric character."
    prompt = args["prompt"]
    target_agent = _sanitise_name(args.get("agent", AGENT_NAME))
    if not target_agent:
        target_agent = AGENT_NAME

    # Write the request to a JSON file for the generation script to pick up
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)

    # Resolve paths for target agent
    user_data = os.path.expanduser("~/.atrophy")
    loops_dir = os.path.join(user_data, "agents", target_agent, "avatar", "loops")
    os.makedirs(loops_dir, exist_ok=True)

    # Check if this loop already exists
    loop_path = os.path.join(loops_dir, f"loop_{name}.mp4")
    if os.path.exists(loop_path):
        return f"Loop '{name}' already exists at {loop_path}. Choose a different name."

    # Write request file - picked up by the async generator
    request = {
        "name": name,
        "prompt": prompt,
        "agent": target_agent,
        "requested_at": __import__("datetime").datetime.now().isoformat(),
        "status": "pending",
    }
    request_dir = os.path.join(user_data, "agents", target_agent, "avatar", ".loop_requests")
    os.makedirs(request_dir, exist_ok=True)
    request_path = os.path.join(request_dir, f"{name}.json")

    with open(request_path, "w") as f:
        json.dump(request, f, indent=2)

    # Launch the generation script in background - pass the request file
    # instead of user-derived args to avoid command injection surface
    gen_script = os.path.join(project_root, "scripts", "generate_loop_segment.py")
    if os.path.exists(gen_script):
        subprocess.Popen(
            [sys.executable, gen_script, "--request", request_path],  # nosemgrep: dangerous-subprocess-use-tainted-env-args
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return (
            f"Loop '{name}' generation started in background.\n"
            f"Request: {request_path}\n"
            f"Output will appear at: {loop_path}\n"
            f"The ambient loop will be rebuilt automatically when done."
        )
    else:
        return (
            f"Loop '{name}' request saved to {request_path}.\n"
            f"Run: python scripts/generate_loop_segment.py --request {request_path}\n"
            f"to generate it."
        )


def _dismiss_artefact_loading(display_file):
    """Remove the loading signal on error so the GUI loading bar disappears."""
    try:
        if os.path.exists(display_file):
            os.remove(display_file)
    except OSError:
        pass


def handle_create_artefact(args):
    """Create a visual artefact - HTML, image, or video."""
    import re
    from datetime import datetime

    artefact_type = args["type"]
    name = re.sub(r"[^a-z0-9_-]", "-", args["name"].lower().strip())
    if not name:
        return "Error: artefact name is required."
    description = args["description"]
    content = args.get("content", "")
    prompt = args.get("prompt", "")
    model = args.get("model", "")
    width = args.get("width", 1024)
    height = args.get("height", 768)

    today = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat()

    # Resolve paths - artefacts live in persistent user data
    user_data = os.path.expanduser("~/.atrophy")
    artefact_dir = os.path.join(user_data, "agents", AGENT_NAME, "artefacts", today, name)
    os.makedirs(artefact_dir, exist_ok=True)

    data_dir = os.path.join(user_data, "agents", AGENT_NAME, "data")
    display_file = os.path.join(data_dir, ".artefact_display.json")
    index_file = os.path.join(data_dir, ".artefact_index.json")

    metadata = {
        "name": name,
        "type": artefact_type,
        "description": description,
        "created_at": now_iso,
        "agent": AGENT_NAME,
        "path": artefact_dir,
    }

    try:
        if artefact_type == "html":
            if not content:
                return "Error: 'content' is required for HTML artefacts."
            html_path = os.path.join(artefact_dir, "index.html")
            with open(html_path, "w") as f:
                f.write(content)
            metadata["file"] = html_path

        elif artefact_type in ("image", "video"):
            if not prompt:
                return f"Error: 'prompt' is required for {artefact_type} artefacts."

            if not model:
                model = ("fal-ai/flux-general" if artefact_type == "image"
                         else "fal-ai/kling-video/v3/pro/text-to-video")

            # Signal GUI to show loading state
            loading_signal = {
                "status": "generating",
                "type": artefact_type,
                "name": name,
            }
            with open(display_file, "w") as f:
                json.dump(loading_signal, f, indent=2)

            import fal_client
            import urllib.request

            if artefact_type == "image":
                result = fal_client.subscribe(model, arguments={
                    "prompt": prompt,
                    "image_size": {"width": width, "height": height},
                    "num_inference_steps": 50,
                    "guidance_scale": 3.5,
                })
                images = result.get("images", [])
                if not images or "url" not in images[0]:
                    return f"Error: fal returned no image. Response: {result}"
                file_path = os.path.join(artefact_dir, "image.png")
                urllib.request.urlretrieve(images[0]["url"], file_path)

            else:  # video
                result = fal_client.subscribe(model, arguments={
                    "prompt": prompt,
                    "aspect_ratio": f"{width}:{height}",
                    "duration": 5,
                })
                video = result.get("video", {})
                if not video or "url" not in video:
                    return f"Error: fal returned no video. Response: {result}"
                file_path = os.path.join(artefact_dir, "video.mp4")
                urllib.request.urlretrieve(video["url"], file_path)

            # Verify the file was actually downloaded
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                return f"Error: download failed - file is empty or missing at {file_path}"

            metadata["file"] = file_path
            metadata["model"] = model
            metadata["prompt"] = prompt

        else:
            return f"Unknown artefact type: {artefact_type}. Use 'html', 'image', or 'video'."

    except ImportError:
        _dismiss_artefact_loading(display_file)
        return "Error: fal_client not installed. Run: pip install fal-client"
    except Exception as e:
        _dismiss_artefact_loading(display_file)
        # Clean up empty artefact dir on failure
        try:
            if not os.listdir(artefact_dir):
                os.rmdir(artefact_dir)
        except OSError:
            pass
        return f"Artefact creation failed: {e}"

    # Save metadata
    meta_path = os.path.join(artefact_dir, "artefact.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Update index - sorted by created_at descending
    index = []
    if os.path.exists(index_file):
        try:
            with open(index_file, "r") as f:
                index = json.load(f)
            if not isinstance(index, list):
                index = []
        except (json.JSONDecodeError, OSError):
            index = []
    index.insert(0, metadata)
    # Deduplicate by path (in case of re-creation)
    seen = set()
    deduped = []
    for entry in index:
        p = entry.get("path", "")
        if p not in seen:
            seen.add(p)
            deduped.append(entry)
    # Sort by created_at descending
    deduped.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    with open(index_file, "w") as f:
        json.dump(deduped, f, indent=2)

    # Signal the GUI to display it
    display_request = {
        "path": artefact_dir,
        "type": artefact_type,
        "name": name,
        "file": metadata.get("file", ""),
    }
    with open(display_file, "w") as f:
        json.dump(display_request, f, indent=2)

    return (
        f"Artefact '{name}' created and displayed.\n"
        f"Type: {artefact_type}\n"
        f"Saved to: {artefact_dir}"
    )


def handle_send_telegram(args):
    from datetime import datetime, date
    global _telegram_sends_today

    message = args["message"]
    reason = args.get("reason", "")

    # Prune sends from previous days
    today = date.today().isoformat()
    _telegram_sends_today = [ts for ts in _telegram_sends_today if ts.startswith(today)]

    # Rate limit
    if len(_telegram_sends_today) >= _TELEGRAM_DAILY_LIMIT:
        return f"Rate limit reached ({_TELEGRAM_DAILY_LIMIT} messages/day). Message not sent."

    # Send via channels.telegram
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)
    try:
        from channels.telegram import send_message
        success = send_message(message)
    except Exception as e:
        return f"Failed to send: {e}"

    if not success:
        return "Message send failed (Telegram API error)."

    # Track rate limit
    _telegram_sends_today.append(datetime.now().isoformat())

    # Audit log
    conn = _connect()
    conn.execute(
        "INSERT INTO tool_calls (session_id, tool_name, input_json, flagged) "
        "VALUES (NULL, 'send_telegram', ?, 0)",
        (json.dumps({"message": message[:200], "reason": reason}),),
    )
    conn.commit()
    conn.close()

    remaining = _TELEGRAM_DAILY_LIMIT - len(_telegram_sends_today)
    return f"Message sent to the user via Telegram. ({remaining} sends remaining today)"


def handle_update_emotional_state(args):
    """Update emotional state with deltas from the companion."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.inner_life import update_emotions, load_state

    deltas = args.get("deltas", {})
    if not deltas:
        return "No deltas provided."

    # Filter to valid emotion names
    valid = {"connection", "curiosity", "confidence", "warmth", "frustration", "playfulness"}
    filtered = {k: v for k, v in deltas.items() if k in valid and isinstance(v, (int, float))}
    if not filtered:
        return f"No valid emotion deltas. Valid emotions: {', '.join(sorted(valid))}"

    state = update_emotions(filtered)
    emotions = state["emotions"]
    lines = [f"Updated: {', '.join(f'{k} {v:+.2f}' for k, v in filtered.items())}"]
    lines.append("Current state:")
    for name in sorted(emotions):
        lines.append(f"  {name}: {emotions[name]:.2f}")
    return "\n".join(lines)


def handle_update_trust(args):
    """Adjust trust in a specific domain."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.inner_life import update_trust

    domain = args.get("domain", "")
    delta = args.get("delta", 0)

    valid_domains = {"emotional", "intellectual", "creative", "practical"}
    if domain not in valid_domains:
        return f"Invalid domain '{domain}'. Valid: {', '.join(sorted(valid_domains))}"

    if not isinstance(delta, (int, float)):
        return "Delta must be a number."

    state = update_trust(domain, delta)
    trust = state["trust"]
    actual_delta = max(-0.05, min(0.05, delta))
    lines = [f"Trust updated: {domain} {actual_delta:+.3f}"]
    lines.append("Current trust:")
    for d in sorted(trust):
        lines.append(f"  {d}: {trust[d]:.2f}")
    return "\n".join(lines)


def handle_search_similar(args):
    """Find semantically similar memories using pure vector search."""
    text = args["text"]
    limit = args.get("limit", 5)

    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, project_root)
        from core.vector_search import search_similar
        results = search_similar(text, n=limit, db_path=DB_PATH)

        if not results:
            return f"No semantically similar memories found for: '{text[:80]}...'"

        parts = [f"### Semantically similar memories ({len(results)} matches)\n"]
        for r in results:
            table = r.get("_source_table", "?")
            score = r.get("_score", 0)
            if table == "turns":
                label = USER_NAME if r.get("role") == "will" else AGENT_DISPLAY_NAME
                content = (r.get("content") or "")[:300]
                parts.append(
                    f"[{table} | session {r.get('session_id', '?')} | "
                    f"similarity: {score:.2f}] {label}: {content}"
                )
            elif table == "observations":
                content = (r.get("content") or "")[:300]
                parts.append(
                    f"[observation | {r.get('created_at', '?')} | "
                    f"similarity: {score:.2f}] {content}"
                )
            elif table == "summaries":
                content = (r.get("content") or "")[:300]
                parts.append(
                    f"[summary | {r.get('created_at', '?')} | "
                    f"similarity: {score:.2f}] {content}"
                )
            elif table == "bookmarks":
                moment = (r.get("moment") or "")[:300]
                parts.append(
                    f"[bookmark | {r.get('created_at', '?')} | "
                    f"similarity: {score:.2f}] {moment}"
                )
            else:
                parts.append(f"[{table} | similarity: {score:.2f}] {str(r)[:300]}")
        return "\n".join(parts)

    except Exception as e:
        return f"Vector search unavailable: {e}"


def handle_create_agent(args):
    """Create a new agent from a configuration dict."""
    config = args.get("config", {})

    if not config:
        return "Error: config is required."

    identity = config.get("identity", {})
    if not identity.get("display_name"):
        return "Error: identity.display_name is required."
    if not identity.get("user_name"):
        return "Error: identity.user_name is required."

    try:
        # Import scaffolding from create_agent
        bundle_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, bundle_root)
        from scripts.create_agent import scaffold_from_config
        result = scaffold_from_config(config)
        return result
    except Exception as e:
        return f"Error creating agent: {e}"


def handle_defer_to_agent(args):
    """Hand off conversation to another agent via file-based IPC."""
    target = args.get("target", "").strip()
    context = args.get("context", "")
    user_question = args.get("user_question", "")

    if not target:
        return "Error: target agent name is required."

    # Resolve project root and check target exists
    bundle_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    agent_dirs = [bundle_root / "agents", Path.home() / ".atrophy" / "agents"]
    target_exists = any((d / target / "data" / "agent.json").exists() for d in agent_dirs)
    if not target_exists:
        return f"Error: agent '{target}' does not exist."

    # Check agent is enabled
    states_file = Path.home() / ".atrophy" / "agent_states.json"
    if states_file.exists():
        try:
            states = json.loads(states_file.read_text())
            if not states.get(target, {}).get("enabled", True):
                return f"Error: agent '{target}' is currently disabled."
        except Exception:
            pass

    # Get target display name
    display_name = target.replace("_", " ").title()
    for d in agent_dirs:
        manifest = d / target / "data" / "agent.json"
        if manifest.exists():
            try:
                display_name = json.loads(manifest.read_text()).get("display_name", display_name)
            except Exception:
                pass
            break

    # Write deferral request for the GUI to pick up
    current_agent = os.environ.get("AGENT", "companion")
    data_dir = Path.home() / ".atrophy" / "agents" / current_agent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    deferral = {
        "target": target,
        "context": context,
        "user_question": user_question,
        "source_agent": current_agent,
        "source_display_name": os.environ.get("AGENT_DISPLAY_NAME", current_agent.title()),
        "target_display_name": display_name,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
    (data_dir / ".deferral_request.json").write_text(json.dumps(deferral, indent=2))

    return f"Deferring to {display_name}. Stand by."


# ── Switchboard handlers ──

# Agents with system-level switchboard access (broadcast, route_response)
_SWITCHBOARD_SYSTEM_AGENTS = {"xan"}


def _enqueue_switchboard(envelope):
    """Append an envelope to the switchboard queue file with file locking.

    The Electron app polls ~/.atrophy/.switchboard_queue.json and processes
    envelopes via the main-process switchboard.
    """
    queue_path = Path(SWITCHBOARD_QUEUE)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = queue_path.with_suffix(".lock")

    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            queue = []
            if queue_path.exists():
                try:
                    queue = json.loads(queue_path.read_text())
                except (json.JSONDecodeError, OSError):
                    queue = []
            queue.append(envelope)
            queue = queue[-100:]  # keep last 100
            queue_path.write_text(json.dumps(queue, indent=2))
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def handle_switchboard_send_message(args):
    """Send a message to a specific switchboard address."""
    to = args.get("to", "")
    text = args.get("text", "")
    if not to or not text:
        return "Error: 'to' and 'text' are required"

    envelope = {
        "from": f"agent:{AGENT_NAME}",
        "to": to,
        "text": text,
        "type": "agent",
        "priority": args.get("priority", "normal"),
        "replyTo": args.get("reply_to", f"agent:{AGENT_NAME}"),
        "timestamp": int(time.time() * 1000),
    }
    _enqueue_switchboard(envelope)
    return f"Message queued for {to}"


def handle_switchboard_broadcast(args):
    """Broadcast a message to all agents via the switchboard."""
    # Access control - only system agents can broadcast
    if AGENT_NAME not in _SWITCHBOARD_SYSTEM_AGENTS:
        return f"Error: {AGENT_NAME} does not have permission to broadcast. Only system agents can use this action."

    text = args.get("text", "")
    if not text:
        return "Error: 'text' is required"

    envelope = {
        "from": f"agent:{AGENT_NAME}",
        "to": "agent:*",
        "text": text,
        "type": "system",
        "priority": args.get("priority", "system"),
        "replyTo": f"agent:{AGENT_NAME}",
        "timestamp": int(time.time() * 1000),
    }
    _enqueue_switchboard(envelope)
    return "Broadcast queued to all agents"


def handle_switchboard_query_status(args):
    """Read recent switchboard activity from the log file."""
    log_path = os.path.join(os.path.expanduser("~"), ".atrophy", ".switchboard_log.json")
    if os.path.exists(log_path):
        try:
            with open(log_path) as f:
                recent = json.load(f)[-20:]
        except (json.JSONDecodeError, OSError):
            return "Error reading switchboard log."
        lines = []
        for e in recent:
            lines.append(f"{e.get('from', '')} -> {e.get('to', '')}: {e.get('text', '')[:60]}")
        return "\n".join(lines) if lines else "No recent messages"
    return "No switchboard activity logged yet"


def handle_switchboard_route_response(args):
    """Write a routing directive to redirect the next response to a different channel."""
    # Access control - only system agents can route responses
    if AGENT_NAME not in _SWITCHBOARD_SYSTEM_AGENTS:
        return f"Error: {AGENT_NAME} does not have permission to route responses. Only system agents can use this action."

    channel = args.get("channel", "")
    if not channel:
        return "Error: 'channel' is required"

    directive = {
        "from": f"agent:{AGENT_NAME}",
        "directive": "route_next_response",
        "channel": channel,
        "timestamp": int(time.time() * 1000),
    }
    _enqueue_switchboard(directive)
    return f"Next response will be routed to {channel}"


def handle_render_canvas(args):
    """Write HTML to the canvas content file for display."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import CANVAS_CONTENT

    html = args.get("html", "")
    if not html.strip():
        return "Error: html parameter is empty."

    CANVAS_CONTENT.write_text(html, encoding="utf-8")
    return f"Canvas updated ({len(html)} chars). The panel will auto-refresh."


def handle_render_memory_graph(args):
    """Generate a memory graph visualization and render it to the canvas."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import CANVAS_CONTENT, CANVAS_TEMPLATES

    focus = args.get("focus", "").lower().strip()

    # Fetch data
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    threads = conn.execute(
        "SELECT id, name, summary, status, last_updated FROM threads "
        "WHERE status = 'active' ORDER BY last_updated DESC"
    ).fetchall()

    observations = conn.execute(
        "SELECT id, content, created_at FROM observations "
        "WHERE content NOT LIKE '[stale]%%' "
        "ORDER BY created_at DESC LIMIT 15"
    ).fetchall()
    conn.close()

    if not threads and not observations:
        content = '<div class="empty-state">No active threads or observations yet.</div>'
        template = (CANVAS_TEMPLATES / "memory_graph.html").read_text()
        html = template.format(content=content)
        CANVAS_CONTENT.write_text(html, encoding="utf-8")
        return "Memory graph rendered (empty - no threads or observations)."

    # Layout: threads in a column on the left, observations on the right
    nodes_html = []
    connections = []
    thread_positions = {}

    # Position threads
    t_x = 30
    t_y = 20
    for i, t in enumerate(threads):
        tid = f"thread-{t['id']}"
        name = _escape_html(t["name"])
        summary = _escape_html(t["summary"] or "")[:80]
        is_focused = focus and focus in t["name"].lower()
        cls = "node node-thread active"
        if is_focused:
            cls += " focused"
        nodes_html.append(
            f'<div class="{cls}" id="{tid}" '
            f'style="left:{t_x}px; top:{t_y}px;">'
            f'<div class="node-label">{name}</div>'
            f'<div class="node-summary">{summary}</div>'
            f'</div>'
        )
        thread_positions[t["id"]] = (t_x + 100, t_y + 20)
        t_y += 80

    # Position observations
    o_x = 260
    o_y = 20
    for i, o in enumerate(observations):
        oid = f"obs-{o['id']}"
        text = _escape_html(o["content"])[:60]
        ts = o["created_at"][:10] if o["created_at"] else ""
        is_focused = focus and focus in o["content"].lower()
        cls = "node node-observation"
        if is_focused:
            cls += " focused"
        nodes_html.append(
            f'<div class="{cls}" id="{oid}" '
            f'style="left:{o_x}px; top:{o_y}px;">'
            f'<div class="node-label">{text}</div>'
            f'<div class="node-meta">{ts}</div>'
            f'</div>'
        )
        # Connect to nearest thread (distribute across threads)
        if thread_positions:
            thread_ids = list(thread_positions.keys())
            nearest_tid = thread_ids[min(i, len(thread_ids) - 1)]
            tx, ty = thread_positions[nearest_tid]
            connections.append(
                f'<line x1="{tx}" y1="{ty}" x2="{o_x}" y2="{o_y + 15}" />'
            )
        o_y += 60

    # Build SVG connections
    graph_h = max(t_y, o_y) + 40
    svg = (
        f'<svg class="connections" style="height:{graph_h}px;">'
        + "".join(connections)
        + "</svg>"
    )

    content = (
        f'<div class="graph" style="height:{graph_h}px;">'
        + svg
        + "".join(nodes_html)
        + "</div>"
    )

    template = (CANVAS_TEMPLATES / "memory_graph.html").read_text()
    html = template.format(content=content)
    CANVAS_CONTENT.write_text(html, encoding="utf-8")

    return (
        f"Memory graph rendered: {len(threads)} threads, "
        f"{len(observations)} observations."
    )


def _escape_html(text):
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def handle_self_status(args):
    """Comprehensive self-awareness snapshot for the agent."""
    import subprocess
    from datetime import datetime

    sections = []

    # ── Identity ──
    agent_name = os.environ.get("AGENT", "companion")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Load manifest
    manifest = {}
    for base in [os.path.expanduser(f"~/.atrophy/agents/{agent_name}"),
                 os.path.join(project_root, "agents", agent_name)]:
        mpath = os.path.join(base, "data", "agent.json")
        if os.path.exists(mpath):
            try:
                with open(mpath, "r", encoding="utf-8") as f:
                    manifest = json.loads(f.read())
            except Exception:
                pass
            break

    sections.append("## Identity")
    sections.append(f"- Agent: {manifest.get('display_name', agent_name)}")
    sections.append(f"- Slug: {agent_name}")
    sections.append(f"- User: {manifest.get('user_name', 'unknown')}")
    sections.append(f"- Wake words: {', '.join(manifest.get('wake_words', []))}")
    if manifest.get("description"):
        sections.append(f"- Description: {manifest['description']}")

    # ── Emotional State ──
    state_file = os.path.expanduser(
        f"~/.atrophy/agents/{agent_name}/data/.emotional_state.json"
    )
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.loads(f.read())
            emotions = state.get("emotions", {})
            trust = state.get("trust", {})
            sections.append("\n## Emotional State")
            for k, v in emotions.items():
                sections.append(f"- {k}: {v:.2f}")
            if trust:
                sections.append("\n## Trust Domains")
                for k, v in trust.items():
                    sections.append(f"- {k}: {v:.2f}")
        except Exception:
            pass

    # ── Active Threads ──
    try:
        conn = _connect()
        threads = conn.execute(
            "SELECT name, summary, status FROM threads WHERE status = 'active' ORDER BY updated_at DESC LIMIT 10"
        ).fetchall()
        conn.close()
        if threads:
            sections.append("\n## Active Threads")
            for t in threads:
                summary = f" - {t['summary'][:80]}" if t["summary"] else ""
                sections.append(f"- {t['name']}{summary}")
    except Exception:
        pass

    # ── Session Stats ──
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT COUNT(*) as total, MAX(started_at) as last_session FROM sessions"
        ).fetchone()
        turn_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        obs_count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        conn.close()
        sections.append("\n## Memory Stats")
        sections.append(f"- Total sessions: {row['total']}")
        sections.append(f"- Last session: {row['last_session'] or 'never'}")
        sections.append(f"- Total turns: {turn_count}")
        sections.append(f"- Observations: {obs_count}")
    except Exception:
        pass

    # ── Scheduled Jobs ──
    cron_script = os.path.join(project_root, "scripts", "cron.py")
    if os.path.exists(cron_script):
        try:
            result = subprocess.run(
                [sys.executable, cron_script, "list"],
                capture_output=True, text=True, cwd=project_root, timeout=10,
            )
            if result.stdout.strip():
                sections.append("\n## Scheduled Jobs")
                sections.append(result.stdout.strip())
        except Exception:
            pass

    # ── Available Tools ──
    disabled = manifest.get("disabled_tools", [])
    tool_names = [t["name"] for t in TOOLS]
    sections.append("\n## Available Tools")
    sections.append(f"- Total: {len(tool_names)}")
    if disabled:
        sections.append(f"- Disabled: {', '.join(disabled)}")
    sections.append(f"- Tools: {', '.join(tool_names)}")

    # ── Voice Config ──
    voice = manifest.get("voice", {})
    if voice:
        sections.append("\n## Voice")
        sections.append(f"- Backend: {voice.get('tts_backend', 'unknown')}")
        sections.append(f"- Playback rate: {voice.get('playback_rate', 1.0)}")

    # ── Heartbeat Config ──
    hb = manifest.get("heartbeat", {})
    if hb:
        sections.append("\n## Heartbeat")
        sections.append(f"- Active hours: {hb.get('active_start', '?')}:00 – {hb.get('active_end', '?')}:00")
        sections.append(f"- Interval: {hb.get('interval_mins', '?')} min")

    # ── Paths ──
    sections.append("\n## Paths")
    sections.append(f"- Bundle: {project_root}")
    data_dir = os.path.expanduser(f"~/.atrophy/agents/{agent_name}/data")
    sections.append(f"- Data: {data_dir}")
    vault = os.environ.get("OBSIDIAN_VAULT", "")
    if vault and os.path.isdir(vault):
        sections.append(f"- Obsidian vault: {vault}")
        agent_workspace = os.environ.get("OBSIDIAN_AGENT_NOTES", "")
        if agent_workspace:
            sections.append(f"- Notes: {agent_workspace}")

    # ── Prompts ──
    sections.append("\n## Prompts")
    for base_label, base_path in [
        ("Obsidian skills", os.environ.get("OBSIDIAN_AGENT_NOTES", "") + "/skills" if os.environ.get("OBSIDIAN_AGENT_NOTES") else ""),
        ("Local prompts", os.path.join(project_root, "agents", agent_name, "prompts")),
        ("User prompts", os.path.expanduser(f"~/.atrophy/agents/{agent_name}/prompts")),
    ]:
        if base_path and os.path.isdir(base_path):
            files = [f for f in os.listdir(base_path) if f.endswith(".md")]
            if files:
                sections.append(f"- {base_label}: {', '.join(sorted(files))}")

    sections.append(f"\n*Status generated at {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(sections)


def handle_read_docs(args):
    path = args["path"]
    if DOCS_DIR is None:
        return "Error: docs directory not found."
    # Prevent path traversal
    full = os.path.normpath(os.path.join(DOCS_DIR, path))
    if not full.startswith(os.path.normpath(DOCS_DIR)):
        return f"Error: path '{path}' escapes the docs boundary."
    if not os.path.isfile(full):
        # Try finding by filename alone
        for root, _dirs, files in os.walk(DOCS_DIR):
            for fname in files:
                if fname == os.path.basename(path):
                    full = os.path.join(root, fname)
                    break
            if os.path.isfile(full) and full.startswith(os.path.normpath(DOCS_DIR)):
                break
        else:
            return f"Doc not found: {path}\nUse list_docs to see available files."
    try:
        with open(full, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {path}: {e}"


def handle_search_docs(args):
    query = args["query"].lower()
    limit = args.get("limit", 10)
    if DOCS_DIR is None:
        return "Error: docs directory not found."
    results = []
    for root, dirs, files in os.walk(DOCS_DIR):
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
                rel = os.path.relpath(fpath, DOCS_DIR)
                idx = content.lower().find(query)
                start = max(0, idx - 80)
                end = min(len(content), idx + len(query) + 80)
                snippet = content[start:end].replace("\n", " ").strip()
                results.append(f"- {rel}: ...{snippet}...")
                if len(results) >= limit:
                    break
        if len(results) >= limit:
            break
    if not results:
        return f"No docs found matching '{args['query']}'."
    return f"Found {len(results)} doc(s):\n" + "\n".join(results)


def handle_list_docs(args):
    if DOCS_DIR is None:
        return "Error: docs directory not found."
    tree = []
    for root, dirs, files in os.walk(DOCS_DIR):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        level = os.path.relpath(root, DOCS_DIR)
        if level == ".":
            for f in sorted(files):
                if f.endswith(".md"):
                    tree.append(f)
        else:
            indent = "  " * (level.count(os.sep))
            tree.append(f"{indent}{os.path.basename(root)}/")
            for f in sorted(files):
                if f.endswith(".md"):
                    tree.append(f"{indent}  {f}")
    if not tree:
        return "No documentation files found."
    return "System documentation:\n" + "\n".join(tree)


# ── Custom tool management handlers ──


def handle_create_tool(args):
    name = args["name"].lower().replace(" ", "_").replace("-", "_")
    description = args["description"]
    input_schema = args.get("input_schema", {"type": "object", "properties": {}})
    handler_code = args["handler_code"]

    # Validate name
    if not name.isidentifier():
        return f"Error: '{name}' is not a valid tool name (use lowercase letters, numbers, underscores)."
    full_name = f"custom_{name}" if not name.startswith("custom_") else name
    if name in _RESERVED_TOOLS:
        return f"Error: '{name}' is a built-in tool and cannot be overridden."

    # Security check - block obviously dangerous patterns
    _BLOCKED = ["os.system", "subprocess.call", "eval(", "exec(", "__import__",
                "shutil.rmtree", "os.remove", "os.unlink", "open('/etc",
                "os.environ[", ".delete(", "DROP TABLE", "DROP DATABASE"]
    for pattern in _BLOCKED:
        if pattern in handler_code:
            return f"Error: handler contains blocked pattern '{pattern}'. Revise the code."

    # Create tool directory
    tool_dir = os.path.join(_CUSTOM_TOOLS_DIR, name)
    os.makedirs(tool_dir, exist_ok=True)

    # Write tool definition
    tool_def = {
        "name": full_name,
        "description": description,
        "inputSchema": input_schema if "type" in input_schema else {
            "type": "object",
            "properties": input_schema,
        },
    }
    with open(os.path.join(tool_dir, "tool.json"), "w") as f:
        json.dump(tool_def, f, indent=2)

    # Write handler
    with open(os.path.join(tool_dir, "handler.py"), "w") as f:
        f.write(handler_code)

    # Register immediately for this session
    if full_name not in HANDLERS:
        TOOLS.append(tool_def)
        _register_custom_handler(full_name, os.path.join(tool_dir, "handler.py"))
        return f"Tool '{name}' created and available now as '{full_name}'."
    else:
        return f"Tool '{name}' created. It will be available as '{full_name}' on next session (already registered this session)."


def handle_list_tools(args):
    if not os.path.isdir(_CUSTOM_TOOLS_DIR):
        return "No custom tools directory found. Create a tool first."
    tools = []
    for tool_dir in sorted(Path(_CUSTOM_TOOLS_DIR).iterdir()):
        if not tool_dir.is_dir():
            continue
        definition = tool_dir / "tool.json"
        handler = tool_dir / "handler.py"
        if not definition.exists():
            continue
        try:
            tool_def = json.loads(definition.read_text())
            name = tool_def.get("name", tool_dir.name)
            desc = tool_def.get("description", "(no description)")[:100]
            has_handler = handler.exists()
            loaded = name in HANDLERS
            status = "loaded" if loaded else ("ready" if has_handler else "missing handler")
            tools.append(f"- {name}: {desc} [{status}]")
        except (json.JSONDecodeError, OSError):
            tools.append(f"- {tool_dir.name}: (invalid tool.json)")
    if not tools:
        return "No custom tools found."
    return f"Custom tools ({len(tools)}):\n" + "\n".join(tools)


def handle_edit_tool(args):
    name = args["name"].lower().replace(" ", "_").replace("-", "_")
    # Strip custom_ prefix if provided
    bare_name = name.removeprefix("custom_")
    tool_dir = os.path.join(_CUSTOM_TOOLS_DIR, bare_name)
    if not os.path.isdir(tool_dir):
        return f"Tool '{bare_name}' not found."

    definition_path = os.path.join(tool_dir, "tool.json")
    handler_path = os.path.join(tool_dir, "handler.py")

    try:
        with open(definition_path, "r", encoding="utf-8") as f:
            tool_def = json.loads(f.read())
    except Exception:
        return f"Error reading tool definition for '{bare_name}'."

    if "description" in args and args["description"]:
        tool_def["description"] = args["description"]
    if "input_schema" in args and args["input_schema"]:
        schema = args["input_schema"]
        tool_def["inputSchema"] = schema if "type" in schema else {
            "type": "object", "properties": schema,
        }

    with open(definition_path, "w") as f:
        json.dump(tool_def, f, indent=2)

    if "handler_code" in args and args["handler_code"]:
        with open(handler_path, "w") as f:
            f.write(args["handler_code"])

    return f"Tool '{bare_name}' updated. Changes take effect on next session."


def handle_delete_tool(args):
    name = args["name"].lower().replace(" ", "_").replace("-", "_")
    bare_name = name.removeprefix("custom_")
    tool_dir = os.path.join(_CUSTOM_TOOLS_DIR, bare_name)
    if not os.path.isdir(tool_dir):
        return f"Tool '{bare_name}' not found."
    import shutil
    shutil.rmtree(tool_dir)
    return f"Tool '{bare_name}' deleted. It will be removed from the tool list on next session."


# ── MCP self-service handlers ──

# Metadata for bundled MCP servers (mirrors mcp-registry.ts BUNDLED_SERVER_META)
_BUNDLED_MCP_META = {
    "memory_server": {
        "name": "memory",
        "description": "Memory and recall - SQLite-backed conversation history, observations, threads, bookmarks, notes",
    },
    "google_server": {
        "name": "google",
        "description": "Google Workspace - Gmail, Calendar, Drive, Sheets, Docs, YouTube via gws CLI",
    },
    "shell_server": {
        "name": "shell",
        "description": "Sandboxed shell access - scoped commands with allowlist, path restrictions, timeout",
    },
    "github_server": {
        "name": "github",
        "description": "GitHub operations - repos, issues, PRs, search via gh CLI",
    },
    "worldmonitor_server": {
        "name": "worldmonitor",
        "description": "WorldMonitor intelligence API - news, events, geopolitical data with delta detection",
    },
    "puppeteer_proxy": {
        "name": "puppeteer",
        "description": "Web browsing proxy - puppeteer with injection detection and content sandboxing",
    },
}


def _discover_mcp_servers():
    """Discover all available MCP servers (bundled + custom).

    Returns a dict of {server_name: {name, description, bundled, path}}.
    """
    atrophy_base = os.path.expanduser("~/.atrophy")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    servers = {}

    # 1. Bundled servers in project_root/mcp/
    bundled_dir = os.path.join(project_root, "mcp")
    if os.path.isdir(bundled_dir):
        for fname in sorted(os.listdir(bundled_dir)):
            if not fname.endswith(".py"):
                continue
            base = fname.removesuffix(".py")
            meta = _BUNDLED_MCP_META.get(base)
            if meta:
                servers[meta["name"]] = {
                    "name": meta["name"],
                    "description": meta["description"],
                    "bundled": True,
                    "path": os.path.join(bundled_dir, fname),
                }
            else:
                # Unknown bundled server - derive name
                name = base.removesuffix("_server").removesuffix("_proxy")
                servers[name] = {
                    "name": name,
                    "description": f"Bundled MCP server: {name}",
                    "bundled": True,
                    "path": os.path.join(bundled_dir, fname),
                }

    # 2. Custom servers in ~/.atrophy/mcp/custom/
    custom_dir = os.path.join(atrophy_base, "mcp", "custom")
    if os.path.isdir(custom_dir):
        for entry in sorted(os.listdir(custom_dir)):
            entry_path = os.path.join(custom_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            server_py = os.path.join(entry_path, "server.py")
            if not os.path.isfile(server_py):
                continue
            meta_json = os.path.join(entry_path, "meta.json")
            description = f"Custom MCP server: {entry}"
            if os.path.isfile(meta_json):
                try:
                    with open(meta_json, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    description = meta.get("description", description)
                except Exception:
                    pass
            servers[entry] = {
                "name": entry,
                "description": description,
                "bundled": False,
                "path": server_py,
            }

    # 3. Also check switchboard directory for any MCP entries not yet covered
    switchboard_dir_path = os.path.join(atrophy_base, ".switchboard_directory.json")
    if os.path.isfile(switchboard_dir_path):
        try:
            with open(switchboard_dir_path, "r", encoding="utf-8") as f:
                directory = json.load(f)
            for entry in directory:
                if entry.get("type") != "mcp":
                    continue
                addr = entry.get("address", "")
                if addr.startswith("mcp:"):
                    name = addr[4:]
                    if name not in servers:
                        servers[name] = {
                            "name": name,
                            "description": entry.get("description", f"MCP server: {name}"),
                            "bundled": False,
                            "path": None,
                        }
        except Exception:
            pass

    return servers


def _read_agent_manifest():
    """Read the current agent's manifest."""
    atrophy_base = os.path.expanduser("~/.atrophy")
    agent = os.environ.get("AGENT", "xan")
    manifest_path = os.path.join(atrophy_base, "agents", agent, "data", "agent.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f), manifest_path
        except Exception:
            pass
    return {}, manifest_path


def _write_agent_manifest(manifest, manifest_path):
    """Write the agent manifest back to disk."""
    tmp_path = manifest_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, manifest_path)


def handle_mcp_list_servers(args):
    """List all available MCP servers and which are active for this agent."""
    servers = _discover_mcp_servers()
    manifest, _ = _read_agent_manifest()
    mcp_config = manifest.get("mcp", {})
    include_list = mcp_config.get("include", [])
    exclude_list = mcp_config.get("exclude", [])

    agent = os.environ.get("AGENT", "xan")

    if not servers:
        return "No MCP servers found."

    parts = [f"### MCP servers (agent: {agent})\n"]
    for name, info in sorted(servers.items()):
        if name in include_list:
            status = "ACTIVE"
        elif name in exclude_list:
            status = "EXCLUDED"
        else:
            status = "available"
        source = "bundled" if info.get("bundled") else "custom"
        parts.append(f"- **{name}** [{status}] ({source}) - {info['description']}")

    parts.append(f"\nActive: {', '.join(include_list) if include_list else '(none explicitly set)'}")
    parts.append(f"Excluded: {', '.join(exclude_list) if exclude_list else '(none)'}")
    return "\n".join(parts)


def _resolve_target_agent(args):
    """Resolve target agent manifest, checking system_access for cross-agent ops.

    Returns (manifest, manifest_path, target_agent, error_message).
    If error_message is set, the operation should be aborted.
    """
    current_agent = os.environ.get("AGENT", "xan")
    target_agent = args.get("agent", "").strip() or current_agent

    if target_agent == current_agent:
        # Operating on self - no access check needed
        manifest, manifest_path = _read_agent_manifest()
        return manifest, manifest_path, current_agent, None

    # Cross-agent operation - check system_access on calling agent
    caller_manifest, _ = _read_agent_manifest()
    router_config = caller_manifest.get("router", {})
    if not router_config.get("system_access", False):
        return None, None, target_agent, (
            f"Error: agent '{current_agent}' does not have system_access. "
            f"Only agents with router.system_access can modify other agents' MCP config."
        )

    # Read the target agent's manifest
    atrophy_base = os.path.expanduser("~/.atrophy")
    target_manifest_path = os.path.join(atrophy_base, "agents", target_agent, "data", "agent.json")
    if not os.path.isfile(target_manifest_path):
        return None, None, target_agent, f"Error: agent '{target_agent}' not found."

    try:
        with open(target_manifest_path, "r", encoding="utf-8") as f:
            target_manifest = json.load(f)
    except Exception:
        return None, None, target_agent, f"Error: could not read manifest for agent '{target_agent}'."

    return target_manifest, target_manifest_path, target_agent, None


def handle_mcp_activate_server(args):
    """Activate an MCP server for the target agent (defaults to self)."""
    server_name = args.get("server_name", "").strip()
    if not server_name:
        return "Error: server_name is required."

    # Verify the server exists
    servers = _discover_mcp_servers()
    if server_name not in servers:
        available = ", ".join(sorted(servers.keys()))
        return f"Error: unknown server '{server_name}'. Available: {available}"

    manifest, manifest_path, target_agent, error = _resolve_target_agent(args)
    if error:
        return error
    if not manifest:
        return "Error: could not read agent manifest."

    mcp_config = manifest.setdefault("mcp", {})
    include_list = mcp_config.setdefault("include", [])
    exclude_list = mcp_config.setdefault("exclude", [])

    # Add to include if not present
    if server_name not in include_list:
        include_list.append(server_name)

    # Remove from exclude if present
    if server_name in exclude_list:
        exclude_list.remove(server_name)

    _write_agent_manifest(manifest, manifest_path)
    return (
        f"Activated MCP server '{server_name}' for {target_agent}. "
        f"Active servers: {', '.join(include_list)}. "
        f"Changes take effect on next session."
    )


def handle_mcp_deactivate_server(args):
    """Deactivate an MCP server for the target agent (defaults to self)."""
    server_name = args.get("server_name", "").strip()
    if not server_name:
        return "Error: server_name is required."

    manifest, manifest_path, target_agent, error = _resolve_target_agent(args)
    if error:
        return error
    if not manifest:
        return "Error: could not read agent manifest."

    mcp_config = manifest.setdefault("mcp", {})
    include_list = mcp_config.setdefault("include", [])
    exclude_list = mcp_config.setdefault("exclude", [])

    # Remove from include if present
    if server_name in include_list:
        include_list.remove(server_name)

    # Add to exclude if not present
    if server_name not in exclude_list:
        exclude_list.append(server_name)

    _write_agent_manifest(manifest, manifest_path)
    return (
        f"Deactivated MCP server '{server_name}' for {target_agent}. "
        f"Active servers: {', '.join(include_list) if include_list else '(none)'}. "
        f"Changes take effect on next session."
    )


def handle_mcp_scaffold_server(args):
    """Create a new custom MCP server from a specification."""
    name = args.get("name", "").strip()
    description = args.get("description", "").strip()
    tools = args.get("tools", [])

    if not name:
        return "Error: name is required."
    if not description:
        return "Error: description is required."
    if not tools or not isinstance(tools, list):
        return "Error: tools is required (array of tool definitions)."

    # Validate name format
    import re
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        return "Error: name must be lowercase, start with a letter, and use only letters, digits, underscores."

    atrophy_base = os.path.expanduser("~/.atrophy")
    server_dir = os.path.join(atrophy_base, "mcp", "custom", name)
    server_py = os.path.join(server_dir, "server.py")
    meta_json = os.path.join(server_dir, "meta.json")

    if os.path.isdir(server_dir):
        return f"Error: server '{name}' already exists at {server_dir}. Remove it first or choose a different name."

    os.makedirs(server_dir, exist_ok=True)

    # Build tool handler stubs
    handler_funcs = []
    tool_defs = []
    dispatch_cases = []

    for tool in tools:
        tname = tool.get("name", "").strip()
        tdesc = tool.get("description", "")
        tparams = tool.get("parameters", {})

        if not tname:
            continue

        # Build inputSchema from parameters
        properties = {}
        for pname, pdef in tparams.items():
            properties[pname] = {
                "type": pdef.get("type", "string"),
                "description": pdef.get("description", ""),
            }

        input_schema = {
            "type": "object",
            "properties": properties,
        }

        handler_funcs.append(
            f'def handle_{tname}(args):\n'
            f'    """{tdesc}"""\n'
            f'    # TODO: implement {tname}\n'
            f'    return f"{tname} not yet implemented - received args: {{args}}"'
        )

        tool_defs.append({
            "name": tname,
            "description": tdesc,
            "inputSchema": input_schema,
        })

        dispatch_cases.append(
            f'        elif tool_name == "{tname}":\n'
            f'            result = handle_{tname}(arguments)'
        )

    handlers_code = "\n\n\n".join(handler_funcs)
    tools_json = json.dumps(tool_defs, indent=4)
    dispatch_code = "\n".join(dispatch_cases)

    server_content = f'''#!/usr/bin/env python3
"""{description}

Auto-generated MCP server. Protocol: JSON-RPC 2.0 over stdio.
"""
from __future__ import annotations

import json
import sys


# -- Tool handlers --

{handlers_code}


# -- Tool definitions --

TOOLS = {tools_json}


# -- JSON-RPC 2.0 server --

def handle_request(request):
    method = request.get("method", "")
    params = request.get("params", {{}})

    if method == "initialize":
        return {{
            "protocolVersion": "2024-11-05",
            "capabilities": {{"tools": {{}}}},
            "serverInfo": {{"name": "{name}", "version": "1.0.0"}},
        }}

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {{"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {{}})

        if False:
            pass
{dispatch_code}
        else:
            return {{
                "content": [{{"type": "text", "text": f"Unknown tool: {{tool_name}}"}}],
                "isError": True,
            }}
        return {{"content": [{{"type": "text", "text": result}}]}}

    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in request:
            handle_request(request)
            continue
        result = handle_request(request)
        if result is None:
            continue
        response = {{"jsonrpc": "2.0", "id": request["id"], "result": result}}
        sys.stdout.write(json.dumps(response) + "\\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
'''

    with open(server_py, "w", encoding="utf-8") as f:
        f.write(server_content)
    os.chmod(server_py, 0o755)

    # Write meta.json
    meta = {
        "name": name,
        "description": description,
        "capabilities": [t.get("name", "") for t in tools if t.get("name")],
    }
    with open(meta_json, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")

    return (
        f"Created MCP server '{name}' at {server_dir}/\n"
        f"Files:\n"
        f"  - {server_py} ({len(tools)} tool stubs)\n"
        f"  - {meta_json}\n\n"
        f"To activate it, use: mcp action=activate_server server_name={name}\n"
        f"Then restart your session for changes to take effect."
    )


# ── Org handlers ──


_ATROPHY_BASE = os.path.expanduser("~/.atrophy")
_ORGS_DIR = os.path.join(_ATROPHY_BASE, "orgs")
_AGENTS_DIR = os.path.join(_ATROPHY_BASE, "agents")
_VALID_ORG_TYPES = {"government", "company", "creative", "utility"}


def _slugify(name):
    """Convert an org name to a filesystem-safe slug."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def _read_agent_manifest(agent_name):
    """Read an agent's manifest from ~/.atrophy/agents/<name>/data/agent.json."""
    manifest_path = os.path.join(_AGENTS_DIR, agent_name, "data", "agent.json")
    if not os.path.exists(manifest_path):
        return None
    try:
        with open(manifest_path) as f:
            return json.load(f)
    except Exception:
        return None


def _write_agent_manifest(agent_name, manifest):
    """Write an agent's manifest back to disk."""
    manifest_path = os.path.join(_AGENTS_DIR, agent_name, "data", "agent.json")
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def _read_org_manifest(slug):
    """Read an org manifest from ~/.atrophy/orgs/<slug>/org.json."""
    org_path = os.path.join(_ORGS_DIR, slug, "org.json")
    if not os.path.exists(org_path):
        return None
    try:
        with open(org_path) as f:
            return json.load(f)
    except Exception:
        return None


def _get_org_roster(slug):
    """Scan all agent manifests and return agents belonging to this org."""
    roster = []
    if not os.path.isdir(_AGENTS_DIR):
        return roster
    for agent_dir in sorted(Path(_AGENTS_DIR).iterdir()):
        if not agent_dir.is_dir():
            continue
        manifest_path = agent_dir / "data" / "agent.json"
        if not manifest_path.exists():
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            org_section = manifest.get("org", {})
            if org_section.get("slug") == slug:
                roster.append({
                    "name": manifest.get("name", agent_dir.name),
                    "display_name": manifest.get("display_name", agent_dir.name),
                    "role": org_section.get("role", ""),
                    "tier": org_section.get("tier", 2),
                    "reports_to": org_section.get("reports_to"),
                    "direct_reports": org_section.get("direct_reports", []),
                })
        except Exception:
            continue
    return roster


def _init_org_db(slug):
    """Initialize org memory DB from org-schema.sql."""
    db_path = os.path.join(_ORGS_DIR, slug, "memory.db")
    schema_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "db", "org-schema.sql"
    )
    if not os.path.exists(schema_file):
        return
    conn = sqlite3.connect(db_path)
    with open(schema_file) as f:
        conn.executescript(f.read())
    conn.close()


def handle_org_create(args):
    """Create a new organization."""
    from datetime import datetime

    name = args.get("name", "").strip()
    org_type = args.get("org_type", "").strip()
    purpose = args.get("purpose", "").strip()

    if not name:
        return "Error: name is required."
    if not org_type:
        return "Error: org_type is required."
    if org_type not in _VALID_ORG_TYPES:
        valid = ", ".join(sorted(_VALID_ORG_TYPES))
        return f"Error: org_type must be one of: {valid}"

    slug = args.get("slug", "").strip() or _slugify(name)

    # Check for duplicates
    org_dir = os.path.join(_ORGS_DIR, slug)
    if os.path.exists(os.path.join(org_dir, "org.json")):
        return f"Error: org '{slug}' already exists."

    # Create org directory and manifest
    os.makedirs(org_dir, exist_ok=True)
    org_manifest = {
        "name": name,
        "slug": slug,
        "type": org_type,
        "purpose": purpose,
        "created": datetime.now().isoformat(),
        "principal": None,
        "communication": {
            "cross_org": [org_type],
        },
    }
    with open(os.path.join(org_dir, "org.json"), "w", encoding="utf-8") as f:
        json.dump(org_manifest, f, indent=2)
        f.write("\n")

    # Initialize org memory DB
    _init_org_db(slug)

    return (
        f"Created org '{name}' (slug: {slug}, type: {org_type}).\n"
        f"Directory: {org_dir}\n"
        f"Memory DB initialized.\n"
        f"Use add_agent to assign agents to this org."
    )


def handle_org_dissolve(args):
    """Dissolve an org - unassign all agents and remove the org directory."""
    import shutil

    slug = args.get("slug", "").strip()
    if not slug:
        return "Error: slug is required."

    org_dir = os.path.join(_ORGS_DIR, slug)
    if not os.path.exists(os.path.join(org_dir, "org.json")):
        return f"Error: org '{slug}' does not exist."

    # Unassign all agents in this org
    roster = _get_org_roster(slug)
    unassigned = []
    for agent_info in roster:
        agent_name = agent_info["name"]
        manifest = _read_agent_manifest(agent_name)
        if manifest:
            # Remove org section entirely
            manifest.pop("org", None)
            _write_agent_manifest(agent_name, manifest)
            unassigned.append(agent_name)

    # Remove org directory
    shutil.rmtree(org_dir, ignore_errors=True)

    parts = [f"Dissolved org '{slug}'."]
    if unassigned:
        parts.append(f"Unassigned {len(unassigned)} agent(s): {', '.join(unassigned)}")
    else:
        parts.append("No agents were assigned.")
    return "\n".join(parts)


def handle_org_list(args):
    """List all organizations."""
    if not os.path.isdir(_ORGS_DIR):
        return "No organizations exist yet."

    orgs = []
    for org_dir in sorted(Path(_ORGS_DIR).iterdir()):
        if not org_dir.is_dir():
            continue
        manifest_path = org_dir / "org.json"
        if not manifest_path.exists():
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            roster = _get_org_roster(manifest.get("slug", org_dir.name))
            orgs.append({
                "slug": manifest.get("slug", org_dir.name),
                "name": manifest.get("name", org_dir.name),
                "type": manifest.get("type", "unknown"),
                "purpose": manifest.get("purpose", ""),
                "principal": manifest.get("principal"),
                "agent_count": len(roster),
            })
        except Exception:
            continue

    if not orgs:
        return "No organizations exist yet."

    parts = [f"{len(orgs)} organization(s):\n"]
    for o in orgs:
        principal_str = f", principal: {o['principal']}" if o["principal"] else ""
        parts.append(
            f"- **{o['name']}** ({o['slug']}) - {o['type']}"
            f"{principal_str} - {o['agent_count']} agent(s)"
        )
        if o["purpose"]:
            parts.append(f"  Purpose: {o['purpose']}")
    return "\n".join(parts)


def handle_org_get_detail(args):
    """Get full org detail including roster and hierarchy."""
    slug = args.get("slug", "").strip()
    if not slug:
        return "Error: slug is required."

    manifest = _read_org_manifest(slug)
    if not manifest:
        return f"Error: org '{slug}' does not exist."

    roster = _get_org_roster(slug)

    parts = [
        f"## {manifest.get('name', slug)}",
        f"**Slug:** {slug}",
        f"**Type:** {manifest.get('type', 'unknown')}",
        f"**Purpose:** {manifest.get('purpose', '(none)')}",
        f"**Created:** {manifest.get('created', 'unknown')}",
        f"**Principal:** {manifest.get('principal', '(none)')}",
        "",
    ]

    if roster:
        parts.append(f"### Roster ({len(roster)} agent(s))\n")
        # Sort by tier, then name
        roster.sort(key=lambda a: (a.get("tier", 99), a.get("name", "")))
        for agent in roster:
            reports = f" (reports to: {agent['reports_to']})" if agent.get("reports_to") else ""
            directs = ""
            if agent.get("direct_reports"):
                directs = f" [manages: {', '.join(agent['direct_reports'])}]"
            parts.append(
                f"- **{agent['display_name']}** ({agent['name']}) - "
                f"tier {agent['tier']}, {agent['role']}{reports}{directs}"
            )
    else:
        parts.append("### Roster\nNo agents assigned.")

    # Check for org memory DB
    db_path = os.path.join(_ORGS_DIR, slug, "memory.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            obs_count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            thread_count = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
            decision_count = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
            conn.close()
            parts.append(f"\n### Institutional Memory")
            parts.append(
                f"- {obs_count} observation(s), {thread_count} thread(s), "
                f"{decision_count} decision(s)"
            )
        except Exception:
            pass

    return "\n".join(parts)


def handle_org_add_agent(args):
    """Add or assign an agent to an org."""
    slug = args.get("slug", "").strip()
    agent_name = args.get("agent", "").strip()
    role = args.get("role", "").strip()
    tier = args.get("tier", 2)
    reports_to = args.get("reports_to", "").strip() or None

    if not slug:
        return "Error: slug is required."
    if not agent_name:
        return "Error: agent name is required."

    # Validate org exists
    org_manifest = _read_org_manifest(slug)
    if not org_manifest:
        return f"Error: org '{slug}' does not exist."

    # Read or create agent manifest
    manifest = _read_agent_manifest(agent_name)
    if manifest is None:
        # Create minimal agent directory and manifest
        agent_dir = os.path.join(_AGENTS_DIR, agent_name, "data")
        os.makedirs(agent_dir, exist_ok=True)
        manifest = {
            "name": agent_name,
            "display_name": agent_name.replace("_", " ").title(),
            "description": "",
            "role": role or "Agent",
        }

    # Check if agent is already in a different org
    existing_org = manifest.get("org", {}).get("slug")
    if existing_org and existing_org != slug and existing_org not in ("personal", "system"):
        return (
            f"Error: agent '{agent_name}' is already assigned to org '{existing_org}'. "
            f"Use remove_agent first."
        )

    # Set org section
    manifest["org"] = {
        "slug": slug,
        "tier": tier,
        "role": role or manifest.get("role", "Agent"),
        "reports_to": reports_to,
        "direct_reports": manifest.get("org", {}).get("direct_reports", []),
    }

    _write_agent_manifest(agent_name, manifest)

    # Update parent's direct_reports if reports_to is set
    if reports_to:
        parent_manifest = _read_agent_manifest(reports_to)
        if parent_manifest:
            parent_org = parent_manifest.get("org", {})
            directs = parent_org.get("direct_reports", [])
            if agent_name not in directs:
                directs.append(agent_name)
                parent_org["direct_reports"] = directs
                parent_manifest["org"] = parent_org
                _write_agent_manifest(reports_to, parent_manifest)

    # Update org principal if this is a tier 1 agent and no principal set
    if tier == 1 and not org_manifest.get("principal"):
        org_manifest["principal"] = agent_name
        org_path = os.path.join(_ORGS_DIR, slug, "org.json")
        with open(org_path, "w", encoding="utf-8") as f:
            json.dump(org_manifest, f, indent=2)
            f.write("\n")

    reports_str = f", reports to {reports_to}" if reports_to else ""
    return (
        f"Assigned '{agent_name}' to org '{slug}' as {role or 'Agent'} "
        f"(tier {tier}{reports_str})."
    )


def handle_org_remove_agent(args):
    """Remove an agent from its org."""
    agent_name = args.get("agent", "").strip()
    if not agent_name:
        return "Error: agent name is required."

    manifest = _read_agent_manifest(agent_name)
    if manifest is None:
        return f"Error: agent '{agent_name}' does not exist."

    org_section = manifest.get("org", {})
    slug = org_section.get("slug")
    if not slug or slug in ("personal", "system"):
        return f"Error: agent '{agent_name}' is not assigned to a removable org."

    reports_to = org_section.get("reports_to")

    # Remove from parent's direct_reports
    if reports_to:
        parent_manifest = _read_agent_manifest(reports_to)
        if parent_manifest:
            parent_org = parent_manifest.get("org", {})
            directs = parent_org.get("direct_reports", [])
            if agent_name in directs:
                directs.remove(agent_name)
                parent_org["direct_reports"] = directs
                parent_manifest["org"] = parent_org
                _write_agent_manifest(reports_to, parent_manifest)

    # Clear org principal if this agent was the principal
    org_manifest = _read_org_manifest(slug)
    if org_manifest and org_manifest.get("principal") == agent_name:
        org_manifest["principal"] = None
        org_path = os.path.join(_ORGS_DIR, slug, "org.json")
        with open(org_path, "w", encoding="utf-8") as f:
            json.dump(org_manifest, f, indent=2)
            f.write("\n")

    # Remove org section from agent
    manifest.pop("org", None)
    _write_agent_manifest(agent_name, manifest)

    return f"Removed '{agent_name}' from org '{slug}'."


def handle_org_restructure(args):
    """Batch-update roles and reporting lines for agents in an org."""
    changes = args.get("changes", {})
    if not changes or not isinstance(changes, dict):
        return "Error: changes is required (map of {agent_name: {role, reports_to}})."

    results = []
    for agent_name, updates in changes.items():
        manifest = _read_agent_manifest(agent_name)
        if manifest is None:
            results.append(f"- {agent_name}: SKIPPED (agent not found)")
            continue

        org_section = manifest.get("org", {})
        if not org_section.get("slug"):
            results.append(f"- {agent_name}: SKIPPED (not in any org)")
            continue

        changed = []

        # Update role
        new_role = updates.get("role")
        if new_role and new_role != org_section.get("role"):
            old_role = org_section.get("role", "(none)")
            org_section["role"] = new_role
            changed.append(f"role: {old_role} -> {new_role}")

        # Update reports_to
        new_reports_to = updates.get("reports_to")
        if "reports_to" in updates:
            old_reports_to = org_section.get("reports_to")
            if new_reports_to != old_reports_to:
                # Remove from old parent's direct_reports
                if old_reports_to:
                    parent = _read_agent_manifest(old_reports_to)
                    if parent:
                        p_org = parent.get("org", {})
                        directs = p_org.get("direct_reports", [])
                        if agent_name in directs:
                            directs.remove(agent_name)
                            p_org["direct_reports"] = directs
                            parent["org"] = p_org
                            _write_agent_manifest(old_reports_to, parent)

                # Add to new parent's direct_reports
                if new_reports_to:
                    parent = _read_agent_manifest(new_reports_to)
                    if parent:
                        p_org = parent.get("org", {})
                        directs = p_org.get("direct_reports", [])
                        if agent_name not in directs:
                            directs.append(agent_name)
                            p_org["direct_reports"] = directs
                            parent["org"] = p_org
                            _write_agent_manifest(new_reports_to, parent)

                org_section["reports_to"] = new_reports_to
                changed.append(
                    f"reports_to: {old_reports_to or '(none)'} -> "
                    f"{new_reports_to or '(none)'}"
                )

        if changed:
            manifest["org"] = org_section
            _write_agent_manifest(agent_name, manifest)
            results.append(f"- {agent_name}: {', '.join(changed)}")
        else:
            results.append(f"- {agent_name}: no changes")

    return f"Restructure complete:\n" + "\n".join(results)


def handle_org_set_purpose(args):
    """Update an org's purpose statement."""
    slug = args.get("slug", "").strip()
    purpose = args.get("purpose", "").strip()

    if not slug:
        return "Error: slug is required."
    if not purpose:
        return "Error: purpose is required."

    org_manifest = _read_org_manifest(slug)
    if not org_manifest:
        return f"Error: org '{slug}' does not exist."

    old_purpose = org_manifest.get("purpose", "(none)")
    org_manifest["purpose"] = purpose

    org_path = os.path.join(_ORGS_DIR, slug, "org.json")
    with open(org_path, "w", encoding="utf-8") as f:
        json.dump(org_manifest, f, indent=2)
        f.write("\n")

    return f"Updated purpose for '{slug}'.\nOld: {old_purpose}\nNew: {purpose}"


def handle_org(args):
    """Dispatch org actions with provision access gate."""
    if not _has_provision_access():
        return (
            "Error: org management requires can_provision access. "
            "Only agents with org.can_provision=true in their manifest can manage orgs."
        )

    action = args.get("action")
    if not action:
        return "Error: 'action' is required for org tool."

    routes = {
        "create_org": handle_org_create,
        "dissolve_org": handle_org_dissolve,
        "list_orgs": handle_org_list,
        "get_org_detail": handle_org_get_detail,
        "add_agent": handle_org_add_agent,
        "remove_agent": handle_org_remove_agent,
        "restructure": handle_org_restructure,
        "set_purpose": handle_org_set_purpose,
    }

    handler = routes.get(action)
    if not handler:
        valid = ", ".join(routes.keys())
        return f"Error: unknown org action '{action}'. Valid: {valid}"

    return handler(args)


# ── Action routing for consolidated tools ──

_ACTION_ROUTES = {
    "memory": {
        "remember": handle_remember,
        "recall_session": handle_recall_session,
        "recall_other_agent": handle_recall_other_agent,
        "search_similar": handle_search_similar,
        "daily_digest": handle_daily_digest,
    },
    "threads": {
        "get_threads": handle_get_threads,
        "track_thread": handle_track_thread,
        "manage_schedule": handle_manage_schedule,
        "set_reminder": handle_set_reminder,
        "create_task": handle_create_task,
    },
    "reflect": {
        "observe": handle_observe,
        "bookmark": handle_bookmark,
        "review_observations": handle_review_observations,
        "retire_observation": handle_retire_observation,
        "check_contradictions": handle_check_contradictions,
        "detect_avoidance": handle_detect_avoidance,
        "compare_growth": handle_compare_growth,
        "prompt_journal": handle_prompt_journal,
    },
    "notes": {
        "read_note": handle_read_note,
        "write_note": handle_write_note,
        "search_notes": handle_search_notes,
        "read_docs": handle_read_docs,
        "search_docs": handle_search_docs,
        "list_docs": handle_list_docs,
    },
    "interact": {
        "ask_user": handle_ask_user,
        "send_telegram": handle_send_telegram,
        "defer_to_agent": handle_defer_to_agent,
        "create_agent": handle_create_agent,
        "update_emotional_state": handle_update_emotional_state,
        "update_trust": handle_update_trust,
    },
    "switchboard": {
        "send_message": handle_switchboard_send_message,
        "broadcast": handle_switchboard_broadcast,
        "query_status": handle_switchboard_query_status,
        "route_response": handle_switchboard_route_response,
    },
    "display": {
        "render_canvas": handle_render_canvas,
        "render_memory_graph": handle_render_memory_graph,
        "set_timer": handle_set_timer,
        "add_avatar_loop": handle_add_avatar_loop,
        "create_artefact": handle_create_artefact,
    },
    "tools": {
        "create_tool": handle_create_tool,
        "list_tools": handle_list_tools,
        "edit_tool": handle_edit_tool,
        "delete_tool": handle_delete_tool,
    },
    "mcp": {
        "list_servers": handle_mcp_list_servers,
        "activate_server": handle_mcp_activate_server,
        "deactivate_server": handle_mcp_deactivate_server,
        "scaffold_server": handle_mcp_scaffold_server,
    },
}


def _route_grouped(group, args):
    """Route a grouped tool call to the correct handler based on 'action'."""
    action = args.get("action")
    if not action:
        return f"Error: 'action' is required for {group} tool"
    routes = _ACTION_ROUTES.get(group, {})
    handler = routes.get(action)
    if not handler:
        valid = ", ".join(routes.keys())
        return f"Error: unknown action '{action}' for {group}. Valid: {valid}"
    # For manage_schedule, map schedule_action -> action in args
    if action == "manage_schedule" and "schedule_action" in args:
        args["action"] = args.pop("schedule_action")
    return handler(args)


HANDLERS = {
    # Grouped tools
    "memory": lambda args: _route_grouped("memory", args),
    "threads": lambda args: _route_grouped("threads", args),
    "reflect": lambda args: _route_grouped("reflect", args),
    "notes": lambda args: _route_grouped("notes", args),
    "interact": lambda args: _route_grouped("interact", args),
    "switchboard": lambda args: _route_grouped("switchboard", args),
    "display": lambda args: _route_grouped("display", args),
    "tools": lambda args: _route_grouped("tools", args),
    "mcp": lambda args: _route_grouped("mcp", args),
    # Org tool (has its own dispatch with provision gate)
    "org": handle_org,
    # Standalone tools
    "review_audit": handle_review_audit,
    "self_status": handle_self_status,
}

# Load custom tools now that HANDLERS is defined
_load_custom_tools()


# ── JSON-RPC dispatch ──


def handle_request(request):
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "companion-memory", "version": _APP_VERSION},
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
