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
from pathlib import Path

_version_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")
_APP_VERSION = open(_version_file).read().strip() if os.path.exists(_version_file) else "0.0.0"

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

VAULT_PATH = os.environ.get("OBSIDIAN_VAULT", os.path.expanduser("~/Documents/Obsidian"))
AGENT_DIR = os.environ.get("OBSIDIAN_AGENT_DIR", os.path.join(VAULT_PATH, "Projects", "The Atrophied Mind", "Agent Workspace", "companion"))
AGENT_NOTES = os.environ.get("OBSIDIAN_AGENT_NOTES", AGENT_DIR)

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
        "name": "recall_other_agent",
        "description": (
            "Search another agent's conversation history — their turns and session "
            "summaries with Will. Use this to understand what Will discussed with "
            "another agent, or to get context on a topic they covered. Does NOT "
            "access their observations or identity model — only what was said."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "Name of the agent to search (e.g. 'companion', 'general_montgomery')",
                },
                "query": {
                    "type": "string",
                    "description": "Search term or phrase to look for in their conversation history",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per category (default 10)",
                    "default": 10,
                },
            },
            "required": ["agent", "query"],
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
            "Ask Will a question or request confirmation via Telegram. "
            "For confirmation/permission, sends Yes/No buttons. "
            "For questions, sends a message and waits for a text reply. "
            "Blocks until Will responds (up to 2 minutes). Use this when "
            "you need his input before proceeding."
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
                    "description": "Type of request. confirmation/permission show Yes/No buttons.",
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
            "him notes, save conversation insights, or write reflections. New notes "
            "automatically get YAML frontmatter (type, created, updated, agent, tags). "
            "Appending updates the 'updated' date. Prefer appending unless creating new. "
            "Use Obsidian features in your content: [[wiki links]] to connect notes, "
            "#tags for categorisation, inline Dataview fields like [mood:: contemplative] "
            "or [topic:: memory], and (@YYYY-MM-DD) for reminders."
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
            "moment, not generic. Write it to Companion/agents/companion/notes/journal-prompts.md."
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
    {
        "name": "send_telegram",
        "description": (
            "Send a Telegram message to Will. Use this to reach out proactively — "
            "share a thought, follow up on something from a previous session, "
            "or respond to a heartbeat impulse. Rate limited to 5 per day."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to send",
                },
                "reason": {
                    "type": "string",
                    "description": "Why you're reaching out (logged for audit, not sent)",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "update_emotional_state",
        "description": (
            "Update your emotional state when you notice shifts in the conversation. "
            "Pass a JSON object of emotion deltas — positive to increase, negative to decrease. "
            "Valid emotions: connection, curiosity, confidence, warmth, frustration, playfulness. "
            "Deltas should be small (typically ±0.05 to ±0.15). Use this for nuanced shifts "
            "beyond what automatic detection catches."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "deltas": {
                    "type": "object",
                    "description": (
                        "Emotion deltas, e.g. {\"connection\": 0.1, \"frustration\": -0.05}"
                    ),
                },
            },
            "required": ["deltas"],
        },
    },
    {
        "name": "update_trust",
        "description": (
            "Adjust trust in a specific domain based on how an interaction went. "
            "Trust changes slowly — max ±0.05 per call. It takes many sessions to "
            "build trust. Domains: emotional, intellectual, creative, practical."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["emotional", "intellectual", "creative", "practical"],
                    "description": "The trust domain to adjust",
                },
                "delta": {
                    "type": "number",
                    "description": "Amount to adjust (max ±0.05)",
                },
            },
            "required": ["domain", "delta"],
        },
    },
    {
        "name": "render_canvas",
        "description": (
            "Render HTML content to the visual canvas panel in the companion window. "
            "Use this to show structured thoughts, diagrams, relationship maps, "
            "formatted text, or any visual content. The canvas is a web view — "
            "full HTML/CSS/JS is supported. Keep styling dark (#1a1a1a background, "
            "#e0e0e0 text) to match the app aesthetic."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "html": {
                    "type": "string",
                    "description": "Complete HTML document to render in the canvas",
                },
            },
            "required": ["html"],
        },
    },
    {
        "name": "render_memory_graph",
        "description": (
            "Generate and render a visual graph of active memory threads and recent "
            "observations in the canvas panel. Shows threads as nodes with their "
            "summaries, connected to recent observations. Optionally focus on a "
            "specific thread or entity to highlight it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional thread name or entity to highlight in the graph",
                },
            },
        },
    },
    {
        "name": "create_agent",
        "description": (
            "Create a new agent for The Atrophied Mind. Accepts a complete configuration "
            "as JSON and scaffolds everything: repo directories, agent.json manifest, "
            "prompts (soul, system, heartbeat), Obsidian workspace (skills, notes, dashboard), "
            "memory database, scheduled job scripts, and cron jobs.json. "
            "Optionally downloads a source face image and video clips to create the avatar.\n\n"
            "Use this after collecting all the agent's identity, voice, appearance, and "
            "autonomy preferences through conversation. The config must include at minimum "
            "identity.display_name and identity.user_name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "description": (
                        "Full agent configuration with sections: identity, boundaries, "
                        "voice, appearance, channels, heartbeat, autonomy. "
                        "Plus optional source_image_url and video_clip_urls."
                    ),
                },
            },
            "required": ["config"],
        },
    },
    {
        "name": "defer_to_agent",
        "description": (
            "Hand off the current conversation to another agent who is better suited "
            "to respond. Use this when the user's question falls outside your expertise "
            "or when they explicitly ask for another agent. The target agent will receive "
            "the user's question along with your context notes. You can still speak before "
            "deferring — say your handoff line, then call this tool."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Agent slug to defer to (e.g. 'general_montgomery')",
                },
                "context": {
                    "type": "string",
                    "description": "Brief context for the target agent — what was discussed, why you're handing off",
                },
                "user_question": {
                    "type": "string",
                    "description": "The user's original question or message that triggered the deferral",
                },
            },
            "required": ["target", "context", "user_question"],
        },
    },
    {
        "name": "set_reminder",
        "description": (
            "Set a reminder for Will at a specific time. When the time arrives, "
            "a macOS notification fires, a sound plays, and the message is queued "
            "for the next conversation. Use natural time understanding — Will might "
            "say 'in 20 minutes', 'at 3pm', 'tomorrow morning', etc. You parse it "
            "into an ISO datetime. Also supports alarms ('wake me at 7am')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "time": {
                    "type": "string",
                    "description": "ISO datetime when the reminder should fire, e.g. '2024-03-10T14:30:00'",
                },
                "message": {
                    "type": "string",
                    "description": "What to remind Will about",
                },
            },
            "required": ["time", "message"],
        },
    },
    {
        "name": "create_task",
        "description": (
            "Create a recurring task that runs on a schedule. This lets you set up "
            "things like 'fetch the news every 2 hours' or 'check the weather every "
            "morning' without needing to write code. You define the prompt and delivery "
            "method, and the system handles scheduling and execution.\n\n"
            "Delivery methods: message_queue (queued for next interaction), "
            "telegram (sent immediately), notification (macOS alert), "
            "obsidian (written to notes).\n\n"
            "Sources you can request: weather, headlines, threads, summaries, observations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short task name (lowercase, hyphens ok), e.g. 'news-digest'",
                },
                "prompt": {
                    "type": "string",
                    "description": "The prompt to execute each time the task runs",
                },
                "cron": {
                    "type": "string",
                    "description": "Cron schedule, e.g. '0 */2 * * *' for every 2 hours",
                },
                "deliver": {
                    "type": "string",
                    "enum": ["message_queue", "telegram", "notification", "obsidian"],
                    "description": "How to deliver the result (default: message_queue)",
                },
                "voice": {
                    "type": "boolean",
                    "description": "Pre-synthesise TTS audio for the result (default: true)",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Data sources to fetch before running: weather, headlines, threads, summaries, observations",
                },
            },
            "required": ["name", "prompt", "cron"],
        },
    },
    {
        "name": "set_timer",
        "description": (
            "Start a visual countdown timer in the app. The timer runs locally "
            "with zero latency — no inference involved, just a clock and a sound. "
            "Use for cooking timers, break reminders, time-boxing tasks, etc. "
            "The timer appears as a floating overlay in the top-right corner."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "Duration in seconds (e.g. 300 for 5 minutes)",
                },
                "label": {
                    "type": "string",
                    "description": "What the timer is for (e.g. 'Tea', 'Break', 'Focus')",
                },
            },
            "required": ["seconds", "label"],
        },
    },
    {
        "name": "add_avatar_loop",
        "description": (
            "Generate a new ambient avatar loop segment. Each loop is a paired "
            "sequence: clip 1 animates from the neutral portrait to an expression, "
            "clip 2 returns to neutral. The result is a ~10s seamless segment that "
            "gets added to the agent's ambient rotation.\n\n"
            "Use this when you want to add a new expression, gesture, or mood to "
            "your visual presence. The loop is generated via Kling 3.0 and added "
            "to the ambient loop automatically.\n\n"
            "The prompt should describe the MOVEMENT and EXPRESSION in cinematic "
            "terms — what changes from the neutral starting position."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short name for this loop segment (e.g. 'contemplation', 'alert', 'wry_smile'). Used as filename.",
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "Cinematic description of the expression/movement. Describe "
                        "what happens FROM neutral TO the peak expression. 3-6 sentences. "
                        "Include physical details: eyes, brow, mouth, head position, hands."
                    ),
                },
                "agent": {
                    "type": "string",
                    "description": "Agent to add the loop to. Defaults to current agent.",
                },
            },
            "required": ["name", "prompt"],
        },
    },
    {
        "name": "create_artefact",
        "description": (
            "Create a visual artefact — an interactive visualisation, chart, map, "
            "image, or video that appears on-screen overlaying the ambient video. "
            "Use this when a visual would genuinely help understanding: a map with "
            "positions marked, a graph of data, a timeline, a 3D rendering, or a "
            "generated image/video.\n\n"
            "For type 'html': provide the content directly (complete HTML document). "
            "No approval needed, no cost.\n"
            "For type 'image' or 'video': provide a generation prompt. The user will "
            "be asked to approve before generation (costs money via fal.ai).\n\n"
            "Use this tool sparingly and purposefully. It exists to elucidate, not "
            "to decorate. Every artefact should earn its place on screen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["html", "image", "video"],
                    "description": "Artefact type: html (interactive), image (fal generation), video (fal generation)",
                },
                "name": {
                    "type": "string",
                    "description": "Short descriptive name for this artefact (used as filename, e.g. 'iran-positions-map', 'solar-system')",
                },
                "description": {
                    "type": "string",
                    "description": "One-line description of what this artefact shows",
                },
                "content": {
                    "type": "string",
                    "description": "Complete HTML document (for type 'html' only). Include all CSS/JS inline.",
                },
                "prompt": {
                    "type": "string",
                    "description": "Generation prompt (for type 'image' or 'video' only)",
                },
                "model": {
                    "type": "string",
                    "description": "Fal model ID (for image/video). Default: fal-ai/flux-general for images, fal-ai/kling-video/v3/pro/text-to-video for video.",
                },
                "width": {
                    "type": "integer",
                    "description": "Image/video width in pixels (default: 1024)",
                },
                "height": {
                    "type": "integer",
                    "description": "Image/video height in pixels (default: 768)",
                },
            },
            "required": ["type", "name", "description"],
        },
    },
    {
        "name": "search_similar",
        "description": (
            "Find semantically similar memories using vector search. Unlike "
            "'remember' which uses keywords, this finds conceptual connections — "
            "memories that mean something similar even if they use different words. "
            "Use when you sense a connection but can't pin down the keywords."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text or concept to find similar memories for",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default 5)",
                    "default": 5,
                },
            },
            "required": ["text"],
        },
    },
]

# Rate limit tracking for Telegram sends
_telegram_sends_today: list[str] = []  # timestamps of sends today
_TELEGRAM_DAILY_LIMIT = 5


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
                    label = "Will" if r.get("role") == "will" else AGENT_DISPLAY_NAME
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
            label = "Will" if t["role"] == "will" else AGENT_DISPLAY_NAME
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
        label = "Will" if t["role"] == "will" else AGENT_DISPLAY_NAME
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
                    label = "Will" if r.get("role") == "will" else display_name
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
                label = "Will" if t["role"] == "will" else display_name
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

    # Send via Telegram and wait for response
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)

    try:
        from channels.telegram import ask_confirm, ask_question

        if action_type in ("confirmation", "permission"):
            result = ask_confirm(f"🔒 {question}")
            if result is True:
                return "Will approved: Yes."
            elif result is False:
                return "Will declined: No."
            else:
                return "No response from Will (timed out after 2 minutes)."
        else:
            reply = ask_question(f"❓ {question}")
            if reply:
                return f"Will replied: {reply}"
            else:
                return "No response from Will (timed out after 2 minutes)."

    except Exception as e:
        return f"Failed to reach Will via Telegram: {e}"


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


_ATROPHY_DIR = os.path.realpath(os.path.join(os.path.expanduser("~"), ".atrophy"))

def _safe_vault_path(path: str) -> str | None:
    """Resolve a path within the vault, blocking traversal attacks.

    Returns the resolved absolute path if it falls inside VAULT_PATH,
    or None if the path escapes the vault boundary or lands in ~/.atrophy/.
    """
    full = os.path.realpath(os.path.join(VAULT_PATH, path))
    vault_real = os.path.realpath(VAULT_PATH)
    if not full.startswith(vault_real + os.sep) and full != vault_real:
        return None
    # Block access to ~/.atrophy/ even if it's inside the vault (e.g. via symlink)
    if full.startswith(_ATROPHY_DIR + os.sep) or full == _ATROPHY_DIR:
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
            existing = open(full, "r").read()
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
        label = "Will" if t["role"] == "will" else AGENT_DISPLAY_NAME
        sessions[sid].append(f"  [{t['timestamp']}] {label}: {t['content'][:200]}")

    parts = [f"'{topic}' appeared in {len(sessions)} session(s):\n"]
    for sid, entries in sorted(sessions.items(), reverse=True):
        parts.append(f"--- Session {sid} ---")
        parts.extend(entries[:4])
        if len(entries) > 4:
            parts.append(f"  ... ({len(entries) - 4} more mentions)")

    # Check if topic appears in Will's turns but conversation moves away
    will_mentions = sum(1 for t in turns if t["role"] == "will")
    companion_mentions = sum(1 for t in turns if t["role"] == "agent")
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
            label = "Will" if t["role"] == "will" else AGENT_DISPLAY_NAME
            parts.append(f"[{t['timestamp']}] {label}: {t['content'][:300]}")

    if newest and oldest:
        # Only show newest if they're different from oldest
        newest_ids = {t["timestamp"] for t in newest}
        oldest_ids = {t["timestamp"] for t in oldest}
        if newest_ids != oldest_ids:
            parts.append("\n### Most recent mentions:")
            for t in newest:
                label = "Will" if t["role"] == "will" else AGENT_DISPLAY_NAME
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
            reminders = json.loads(open(reminders_file).read())
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

    return f"Timer set: {label} — {display}"


def handle_create_task(args):
    """Create a task definition in Obsidian and schedule it via cron."""
    import re
    import shlex
    import subprocess

    name = args["name"]
    prompt = args["prompt"]
    cron = args["cron"]
    deliver = args.get("deliver", "message_queue")
    voice = args.get("voice", True)
    sources = args.get("sources", [])

    # Sanitise task name — alphanumeric, hyphens, underscores only
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip())
    if not safe_name:
        return "Error: task name must contain at least one alphanumeric character."
    name = safe_name

    # Validate cron expression — must be 5 space-separated fields of [0-9*/,-]
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


def handle_add_avatar_loop(args):
    """Generate a new loop segment via Kling and add to ambient rotation."""
    import subprocess

    name = args["name"]
    prompt = args["prompt"]
    target_agent = args.get("agent", AGENT_NAME)

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

    # Write request file — picked up by the async generator
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

    # Launch the generation script in background
    gen_script = os.path.join(project_root, "scripts", "generate_loop_segment.py")
    if os.path.exists(gen_script):
        subprocess.Popen(
            [sys.executable, gen_script, "--agent", target_agent, "--name", name],
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
            f"Run: python scripts/generate_loop_segment.py --agent {target_agent} --name {name}\n"
            f"to generate it."
        )


def handle_create_artefact(args):
    """Create a visual artefact — HTML, image, or video."""
    import re
    import time
    from datetime import datetime

    artefact_type = args["type"]
    name = re.sub(r"[^a-z0-9_-]", "-", args["name"].lower().strip())
    description = args["description"]
    content = args.get("content", "")
    prompt = args.get("prompt", "")
    model = args.get("model", "")
    width = args.get("width", 1024)
    height = args.get("height", 768)

    today = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat()

    # Resolve paths
    artefact_dir = os.path.join(AGENT_DIR, "artefacts", today, name)
    os.makedirs(artefact_dir, exist_ok=True)

    user_data = os.path.expanduser("~/.atrophy")
    data_dir = os.path.join(user_data, "agents", AGENT_NAME, "data")
    request_file = os.path.join(data_dir, ".artefact_request.json")
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

    if artefact_type == "html":
        # HTML artefacts — no approval needed, no cost
        if not content:
            return "Error: 'content' is required for HTML artefacts."
        html_path = os.path.join(artefact_dir, "index.html")
        with open(html_path, "w") as f:
            f.write(content)
        metadata["file"] = html_path

    elif artefact_type in ("image", "video"):
        # Requires approval — write request, poll for approval
        if not prompt:
            return f"Error: 'prompt' is required for {artefact_type} artefacts."

        if not model:
            model = ("fal-ai/flux-general" if artefact_type == "image"
                     else "fal-ai/kling-video/v3/pro/text-to-video")

        cost_est = "$0.03" if artefact_type == "image" else "$0.30"
        request = {
            "status": "pending",
            "type": artefact_type,
            "name": name,
            "description": description,
            "prompt": prompt,
            "model": model,
            "cost_estimate": cost_est,
            "requested_at": now_iso,
        }
        with open(request_file, "w") as f:
            json.dump(request, f, indent=2)

        # Poll for approval (max 120s)
        deadline = time.time() + 120
        approved = False
        while time.time() < deadline:
            time.sleep(2)
            try:
                with open(request_file, "r") as f:
                    state = json.load(f)
                if state.get("status") == "approved":
                    approved = True
                    break
                elif state.get("status") == "rejected":
                    try:
                        os.remove(request_file)
                    except OSError:
                        pass
                    return "Artefact creation cancelled by user."
            except (json.JSONDecodeError, OSError):
                continue

        if not approved:
            try:
                os.remove(request_file)
            except OSError:
                pass
            return "Artefact creation timed out waiting for approval."

        # Clean up request file
        try:
            os.remove(request_file)
        except OSError:
            pass

        # Generate via fal
        try:
            import fal_client
            if artefact_type == "image":
                result = fal_client.subscribe(model, arguments={
                    "prompt": prompt,
                    "image_size": {"width": width, "height": height},
                    "num_inference_steps": 50,
                    "guidance_scale": 3.5,
                })
                image_url = result["images"][0]["url"]
                # Download image
                import urllib.request
                ext = "png"
                file_path = os.path.join(artefact_dir, f"image.{ext}")
                urllib.request.urlretrieve(image_url, file_path)
                metadata["file"] = file_path
                metadata["model"] = model
                metadata["prompt"] = prompt
                metadata["cost_estimate"] = cost_est

            elif artefact_type == "video":
                result = fal_client.subscribe(model, arguments={
                    "prompt": prompt,
                    "aspect_ratio": f"{width}:{height}",
                    "duration": 5,
                })
                video_url = result["video"]["url"]
                import urllib.request
                file_path = os.path.join(artefact_dir, f"video.mp4")
                urllib.request.urlretrieve(video_url, file_path)
                metadata["file"] = file_path
                metadata["model"] = model
                metadata["prompt"] = prompt
                metadata["cost_estimate"] = cost_est

        except Exception as e:
            return f"Artefact generation failed: {e}"
    else:
        return f"Unknown artefact type: {artefact_type}"

    # Save metadata
    meta_path = os.path.join(artefact_dir, "artefact.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Update index
    index = []
    if os.path.exists(index_file):
        try:
            with open(index_file, "r") as f:
                index = json.load(f)
        except (json.JSONDecodeError, OSError):
            index = []
    index.insert(0, metadata)
    with open(index_file, "w") as f:
        json.dump(index, f, indent=2)

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
    return f"Message sent to Will via Telegram. ({remaining} sends remaining today)"


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
                label = "Will" if r.get("role") == "will" else AGENT_DISPLAY_NAME
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
        return "Memory graph rendered (empty — no threads or observations)."

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


HANDLERS = {
    "remember": handle_remember,
    "recall_session": handle_recall_session,
    "recall_other_agent": handle_recall_other_agent,
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
    "set_reminder": handle_set_reminder,
    "set_timer": handle_set_timer,
    "create_task": handle_create_task,
    "add_avatar_loop": handle_add_avatar_loop,
    "create_artefact": handle_create_artefact,
    "read_note": handle_read_note,
    "write_note": handle_write_note,
    "search_notes": handle_search_notes,
    "send_telegram": handle_send_telegram,
    "update_emotional_state": handle_update_emotional_state,
    "update_trust": handle_update_trust,
    "search_similar": handle_search_similar,
    "create_agent": handle_create_agent,
    "defer_to_agent": handle_defer_to_agent,
    "render_canvas": handle_render_canvas,
    "render_memory_graph": handle_render_memory_graph,
}


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
