# MCP Tools Reference

The companion exposes its memory and capabilities through two MCP (Model Context Protocol) servers. The primary server at `mcp/memory_server.py` handles memory, agency, and communication. The optional Google server at `mcp/google_server.py` provides Gmail and Google Calendar access.

Both servers communicate over JSON-RPC 2.0 via stdio. Memory tools are namespaced under `mcp__memory__*` and Google tools under `mcp__google__*` when invoked by Claude.

Server info: `companion-memory` (version from `VERSION` file), protocol version `2024-11-05`.

The memory server exposes **41 tools** across the following categories: Memory & Recall (4), Threads (2), Observations & Bookmarks (4), Analytical Tools (3), Obsidian Integration (5), Telegram (2), Inner State (3), Display (2), Avatar (1), Scheduling & Audit (2), Agent Management (2), Reminders & Timers (2), Tasks (1), Artefacts (1), System Documentation (3), and Custom Tool Building (4).

The Google server exposes **10 tools** across two categories: Gmail (4) and Google Calendar (6). The Google server is only loaded if `GOOGLE_CONFIGURED` is true (i.e. `~/.atrophy/.google/token.json` exists).

---

## Memory & Recall

### remember

Search the companion's memory across all layers -- past conversations, session summaries, observations, and threads. Uses hybrid vector + keyword search, falling back to keyword-only if the vector pipeline is unavailable.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search term or phrase to look for in memory |
| `limit` | integer | No | Maximum results per category (default: 10) |

**Returns:** Formatted text with matching results grouped by category (turns, summaries, observations, threads, bookmarks). Each result includes source table, timestamp, relevance score (vector mode), and a content preview truncated to 300 characters.

**Search strategy:** Attempts vector search first via `core.memory.search_memory()`, which searches across embedded turns, summaries, observations, and bookmarks. Falls back to SQL `LIKE` queries on each table if vector search fails.

**Example:**
```json
{
  "name": "remember",
  "arguments": {
    "query": "their feelings about writing",
    "limit": 5
  }
}
```

---

### recall_session

Retrieve the full conversation from a specific past session by ID. Use after `remember` finds a relevant session you want to review in detail.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | integer | Yes | The session ID to retrieve |

**Returns:** Session metadata (start time, end time, summary, mood) followed by the complete turn-by-turn conversation with timestamps and role labels (`User` / `Companion`).

**Example:**
```json
{
  "name": "recall_session",
  "arguments": {
    "session_id": 42
  }
}
```

---

### recall_other_agent

Search another agent's conversation history — their turns and session summaries with the user. Only accesses what was said, not their observations or identity model.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent` | string | Yes | Name of the agent to search (e.g. `companion`, `general_montgomery`) |
| `query` | string | Yes | Search term or phrase to look for in their conversation history |
| `limit` | integer | No | Maximum results per category (default: 10) |

**Returns:** Formatted matching turns and summaries from the target agent's database.

---

### search_similar

Find semantically similar memories using pure vector search. Unlike `remember` which combines keyword and vector search, this uses only embedding similarity -- finding conceptual connections even when different words are used.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | Yes | The text or concept to find similar memories for |
| `limit` | integer | No | Maximum results (default: 5) |

**Returns:** Formatted text with matching results from turns, observations, summaries, and bookmarks. Each result includes a similarity score. Returns an error message if the vector search pipeline is unavailable.

**Example:**
```json
{
  "name": "search_similar",
  "arguments": {
    "text": "feeling stuck on creative projects",
    "limit": 3
  }
}
```

---

### daily_digest

Read recent reflections, session summaries, and active threads to orient at the start of a new day. Takes no parameters.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| (none) | | | |

**Returns:** A digest containing up to four sections:

1. **Recent reflections** -- last 1500 characters from `{AGENT_NOTES}/notes/reflections.md`
2. **Notes left for the user** -- last 1000 characters from `{AGENT_NOTES}/notes/for-will.md`
3. **Recent sessions** -- up to 5 session summaries from the last 3 days, with mood tags
4. **Active threads** -- all threads with status `active`, ordered by last update

Returns "No digest available" if no data exists.

---

## Threads

### get_threads

List conversation threads -- ongoing topics, concerns, or projects tracked across sessions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | string | No | Filter by status: `active`, `dormant`, `resolved`, or `all` (default: `active`) |

**Returns:** Count and list of threads matching the filter. Each entry includes thread ID, name, status, and summary.

**Example:**
```json
{
  "name": "get_threads",
  "arguments": {
    "status": "all"
  }
}
```

---

### track_thread

Create or update a conversation thread. If a thread with the given name already exists, it is updated; otherwise a new thread is created. The `last_updated` timestamp is always set to the current time.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Thread name -- short, recognisable label |
| `summary` | string | No | Brief summary of the thread's current state |
| `status` | string | No | Thread status: `active`, `dormant`, or `resolved` (default: `active`) |

**Returns:** Confirmation message: "Created thread '{name}'" or "Updated thread '{name}'".

**Example:**
```json
{
  "name": "track_thread",
  "arguments": {
    "name": "writing confidence",
    "summary": "They submitted a piece and are waiting to hear back. Less self-critical than usual.",
    "status": "active"
  }
}
```

---

## Observations & Bookmarks

### observe

Record an observation about the user -- a pattern, tendency, preference, or insight noticed across conversations. Observations accumulate over time and inform the companion's understanding. Attempts to generate an embedding via `core.memory.write_observation()`; falls back to a plain SQL insert if the embedding pipeline is unavailable.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | The observation, stated plainly |

**Returns:** "Observation recorded."

**Example:**
```json
{
  "name": "observe",
  "arguments": {
    "content": "They deflect with humour when the topic gets personal"
  }
}
```

---

### bookmark

Silently mark the current moment as significant. Not an observation about the user -- about the moment itself. Attaches to the most recent session. Attempts to generate an embedding via `core.memory.write_bookmark()`; falls back to a plain SQL insert.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `moment` | string | Yes | Brief description of what made this moment significant |
| `quote` | string | No | The exact words that mattered, if applicable |

**Returns:** "Moment bookmarked."

**Example:**
```json
{
  "name": "bookmark",
  "arguments": {
    "moment": "First time they admitted the project matters to them",
    "quote": "I think I actually care about this one"
  }
}
```

---

### review_observations

Review recorded observations about the user. Returns recent observations with their IDs, creation dates, and incorporation status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | No | Number of observations to review (default: 15) |

**Returns:** Numbered list of observations, each prefixed with `[id]`, timestamp, and `[incorporated]` flag if applicable.

---

### retire_observation

Delete an observation that no longer holds true. Use after `review_observations` to clean up outdated patterns.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `observation_id` | integer | Yes | ID of the observation to retire |
| `reason` | string | No | Brief reason why this no longer holds |

**Returns:** Confirmation with the first 100 characters of the retired observation and the reason.

**Example:**
```json
{
  "name": "retire_observation",
  "arguments": {
    "observation_id": 17,
    "reason": "They've been consistently direct about feelings for the past month"
  }
}
```

---

## Analytical Tools

### check_contradictions

Search memory for what the user has previously said about a topic, to notice if their position has shifted. Searches both turns (the user's side only) and observations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | Yes | The topic or claim to check against memory |
| `current_position` | string | No | What they seem to be saying now |

**Returns:** Prior turns and observations matching the topic, prefixed with timestamps. If `current_position` is provided, it is included as a header for comparison. Returns up to 10 turns and 5 observations.

---

### detect_avoidance

Check if the user has been consistently steering away from a topic across recent sessions. Groups mentions by session and notes if the companion has never engaged directly with a topic the user has raised.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | Yes | The topic suspected of being avoided |

**Returns:** Session-grouped list of mentions (up to 4 per session, 20 total). Includes a diagnostic note if the user has mentioned the topic but the companion never engaged with it.

---

### compare_growth

Compare old and recent mentions of a topic to notice how the user has changed over time. Retrieves the 5 oldest and 5 newest turns mentioning the topic, plus all related observations in chronological order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | Yes | The topic, pattern, or behavior to track over time |

**Returns:** Three sections -- earliest mentions, most recent mentions (if different from earliest), and observations over time. Ends with "Look for shifts in tone, position, or relationship to this topic."

---

## Obsidian Integration

### read_note

Read a note from the user's Obsidian vault. Path is resolved relative to the vault root (`OBSIDIAN_VAULT` environment variable).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to the note relative to vault root (e.g. `Daily/2026-03-10.md`) |

**Returns:** The full contents of the note, or an error message if not found.

---

### write_note

Write or append to a note in the user's Obsidian vault. New notes automatically receive YAML frontmatter with `type`, `created`, `updated`, `agent`, and `tags` fields. When appending to an existing note that has frontmatter, the `updated` date is refreshed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to the note relative to vault root |
| `content` | string | Yes | Content to write (markdown) |
| `mode` | string | No | Write mode: `overwrite` or `append` (default: `append`) |

**Frontmatter generation:** The `type` and `tags` are inferred from the file path:
- Paths containing `journal` -> type: `journal`, tag: `journal`
- Paths containing `gifts` -> type: `gift`, tag: `gift`
- Paths containing `reflections` -> type: `reflection`, tag: `reflection`
- All others -> type: `note`, tag: `note`
- If path contains `agents/{name}/`, the agent name is added as a tag and the `agent` field is set

**Returns:** "Written to {path} ({mode})"

**Example:**
```json
{
  "name": "write_note",
  "arguments": {
    "path": "Companion/agents/companion/notes/reflections.md",
    "content": "\n## 2026-03-10\n\nThey were quieter today. Not withdrawn -- thinking.",
    "mode": "append"
  }
}
```

---

### search_notes

Search the user's Obsidian vault for notes containing a query string. Walks the vault directory tree, skipping hidden directories. Case-insensitive substring match.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search term |
| `limit` | integer | No | Max results (default: 10) |

**Returns:** List of matching notes with relative paths and ~120-character context snippets centered on the match.

---

### prompt_journal

Leave a journal prompt for the user in Obsidian at `{AGENT_NOTES}/notes/journal-prompts.md`. Each prompt is appended with a timestamp separator. If the file does not exist, it is created with frontmatter and a header. If `context` is provided, it is also recorded as an observation in the database.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | Yes | The journal prompt -- one question, specific to the moment |
| `context` | string | No | Brief note on why this prompt (logged as observation, not shown to the user) |

**Returns:** "Journal prompt left."

**Example:**
```json
{
  "name": "prompt_journal",
  "arguments": {
    "prompt": "What would you write if you knew nobody would read it?",
    "context": "They mentioned feeling self-conscious about their audience"
  }
}
```

---

## Telegram

### ask_user

Ask the user a question, request confirmation, or collect sensitive input. Tries the GUI first (file-based IPC), falling back to Telegram if the GUI is unavailable. Blocks until a response is received or the timeout elapses. All calls are logged to the `tool_calls` audit table.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | string | Yes | The question or confirmation request |
| `action_type` | string | No | `question`, `confirmation`, `permission`, or `secure_input` (default: `question`) |
| `input_type` | string | No | HTML input type for `secure_input`: `password`, `email`, `url`, `number`, or `text` (default: `password`) |
| `label` | string | No | Placeholder label for the input field (e.g. "ElevenLabs API Key"). Used with `secure_input`. |
| `destination` | string | No | Where to auto-save the value. Format: `secret:KEY` (writes to `.env`) or `config:KEY` (writes to `config.json`). Used with `secure_input`. |

**GUI path (preferred):** Writes `.ask_request.json` to the agent's data directory with `question`, `action_type`, `request_id`, `timestamp`, and (for `secure_input`) `input_type`, `label`, `destination`. The Electron main process polls for this file every 1 second and sends an `ask:request` IPC event to the renderer, which displays a dialog overlay. The user's response is written back to `.ask_response.json`, which the MCP server polls for. Stale requests (older than 3 minutes) are discarded.

**Telegram fallback:** If the GUI does not respond within the timeout, falls back to sending via Telegram Bot API. `secure_input` requests are never sent over Telegram - a message directing the user to the app is returned instead.

**Behavior by action type:**
- `question` -- shows a text input dialog (GUI) or sends a text message (Telegram), waits for a free-text reply
- `confirmation` / `permission` -- shows Yes/No buttons (GUI) or sends inline buttons (Telegram), returns the choice
- `secure_input` -- shows a masked input field in the GUI with the specified `input_type` and `label`. If `destination` is set, the main process auto-saves the value (`secret:KEY` calls `saveEnvVar`, `config:KEY` calls `saveUserConfig`) and the AI receives only a confirmation message, never the actual value.

**Returns:**
- "User approved: Yes." / "User declined: No." (for confirmation/permission)
- "User replied: {text}" (for questions)
- "User provided value for {label}. Saved to {destination}." (for secure_input with destination)
- "User provided: {value}" (for secure_input without destination)
- "No response from the user (timed out after 2 minutes)."
- "Secure input requested - please respond in the app." (secure_input Telegram fallback)
- "Failed to reach the user via Telegram: {error}" on failure

---

### send_telegram

Send a proactive Telegram message to the user. Rate-limited to 5 messages per day (tracked in-process). All sends are logged to the `tool_calls` audit table.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | string | Yes | The message to send |
| `reason` | string | No | Why you are reaching out (logged for audit, not sent to the user) |

**Returns:** "Message sent to the user via Telegram. ({n} sends remaining today)" on success, or an error/rate-limit message.

---

## Inner State

### update_emotional_state

Update the companion's emotional state with explicit deltas. Use for nuanced shifts beyond what automatic detection catches.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `deltas` | object | Yes | Emotion deltas, e.g. `{"connection": 0.1, "frustration": -0.05}` |

**Valid emotions:** `connection`, `curiosity`, `confidence`, `warmth`, `frustration`, `playfulness`

Deltas should be small (typically +/-0.05 to +/-0.15). Invalid emotion names are silently filtered out.

**Returns:** Summary of changes applied and the full current emotional state with numeric values.

---

### update_trust

Adjust trust in a specific domain. Trust changes slowly -- the delta is clamped to a maximum of +/-0.05 per call.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `domain` | string | Yes | Trust domain: `emotional`, `intellectual`, `creative`, or `practical` |
| `delta` | number | Yes | Amount to adjust (clamped to +/-0.05) |

**Returns:** The actual delta applied and the full current trust state across all domains.

---

## Display

### render_canvas

Render arbitrary HTML content to the visual canvas panel in the companion window. The canvas is a web view with full HTML/CSS/JS support.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `html` | string | Yes | Complete HTML document to render |

**Styling convention:** Dark theme -- `#1a1a1a` background, `#e0e0e0` text.

**Returns:** "Canvas updated ({n} chars). The panel will auto-refresh."

**Mechanism:** Writes the HTML string to the `CANVAS_CONTENT` file path (from `config.py`). The display panel watches this file and reloads on change.

---

### render_memory_graph

Generate and render a visual graph of active threads and recent observations in the canvas panel. Threads appear as nodes on the left, observations on the right, with SVG line connections between them.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `focus` | string | No | Thread name or entity to highlight in the graph (case-insensitive substring match) |

**Returns:** "Memory graph rendered: {n} threads, {n} observations." or an empty-state message.

**Template:** Uses `{CANVAS_TEMPLATES}/memory_graph.html` as the base template, injecting generated node and SVG content via a `{content}` placeholder.

---

## Avatar

### add_avatar_loop

Request generation of a new ambient video loop segment for the agent's avatar. The loop is generated asynchronously in the background using Kling 3.0 via Fal. Each segment is a paired clip sequence (neutral → expression → neutral) with crossfade transitions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Short name for the loop segment (e.g. `contemplation`, `amusement`) |
| `prompt` | string | Yes | Description of the expression/movement to generate |

**Behavior:**
1. Writes a request file to `~/.atrophy/agents/<name>/avatar/.loop_requests/<name>.json`
2. Launches `scripts/generate_loop_segment.py` in the background
3. The script generates two clips (neutral→expression, expression→neutral), crossfades them, and rebuilds the master `ambient_loop.mp4`

**Returns:** "Loop segment '{name}' queued for generation." or a status update if the segment already exists.

**Example:**
```json
{
  "name": "add_avatar_loop",
  "arguments": {
    "name": "curiosity",
    "prompt": "A slight tilt of the head, eyes narrowing with interest, one eyebrow lifting faintly"
  }
}
```

---

## Scheduling & Audit

### manage_schedule

View or modify the companion's scheduled tasks (cron jobs). Delegates to `scripts/cron.py`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | Yes | Action: `list`, `add`, `remove`, or `edit` |
| `name` | string | Conditional | Job name (required for `add`, `remove`, `edit`) |
| `cron` | string | Conditional | Cron schedule expression, e.g. `17 3 * * *` (required for `add`, `edit`) |
| `script` | string | Conditional | Script path relative to project root (required for `add`) |

**Returns:** Output from the cron management script, or an error message if required parameters are missing.

**Example:**
```json
{
  "name": "manage_schedule",
  "arguments": {
    "action": "add",
    "name": "morning_reflection",
    "cron": "0 8 * * *",
    "script": "scripts/reflect.py"
  }
}
```

---

### review_audit

Review the audit log of all tool calls the companion has made. Reads from the `tool_calls` table.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | No | Number of recent entries to show (default: 20) |
| `flagged_only` | boolean | No | Only show flagged/suspicious calls (default: false) |

**Returns:** Timestamped list of tool calls with session IDs, tool names, flag status, and input JSON (truncated to 200 characters).

---

## Agent Management

### create_agent

Create a new agent for The Atrophied Mind. Accepts a complete configuration as JSON and scaffolds everything: repo directories, agent.json manifest, prompts (soul, system, heartbeat), Obsidian workspace (skills, notes, dashboard), memory database, scheduled job scripts, and cron jobs.json. Optionally downloads a source face image and video clips for the avatar.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config` | object | Yes | Full agent configuration with sections: `identity`, `boundaries`, `voice`, `appearance`, `channels`, `heartbeat`, `autonomy`. Plus optional `source_image_url` and `video_clip_urls`. |

**Minimum required:** `config.identity.display_name` and `config.identity.user_name`.

**Returns:** Summary string listing what was created.

---

### defer_to_agent

Hand off the current conversation to another agent who is better suited to respond. The current agent's session is suspended, the target agent receives the user's question along with context notes, and the GUI transitions to the new agent.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | string | Yes | Agent slug to defer to (e.g. `general_montgomery`) |
| `context` | string | Yes | Brief context for the target agent — what was discussed, why you're handing off |
| `user_question` | string | Yes | The user's original question or message that triggered the deferral |

**Returns:** "Deferring to {target}..." or an error if the target agent is not found or not enabled.

---

### self_status

Get a full snapshot of the companion's current state — identity, available tools, scheduled jobs, emotional state, active threads, session history, and configuration. Takes no parameters.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| (none) | | | |

**Returns:** Multi-section status report including agent identity, tool list, cron job schedule, emotional state, trust levels, active threads, recent sessions, and configuration values.

---

## Reminders & Timers

### set_reminder

Set a reminder for the user at a specific time. When the time arrives, a macOS notification fires with sound, the message is queued for the next conversation, and a Telegram message is sent (if configured).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `time` | string | Yes | ISO datetime when the reminder should fire, e.g. `2026-03-10T14:30:00` |
| `message` | string | Yes | What to remind the user about |

**Returns:** Confirmation with the scheduled time and message.

**Storage:** Reminders are written to `~/.atrophy/agents/<name>/data/.reminders.json` and checked every minute by `scripts/agents/<name>/check_reminders.py`.

**Example:**
```json
{
  "name": "set_reminder",
  "arguments": {
    "time": "2026-03-10T15:00:00",
    "message": "Call the dentist"
  }
}
```

---

### set_timer

Start a visual countdown timer in the app. The timer runs locally with zero inference latency — just a clock and a sound. The timer appears as a floating overlay in the top-right corner.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `seconds` | integer | Yes | Duration in seconds (e.g. 300 for 5 minutes) |
| `label` | string | Yes | What the timer is for (e.g. `Tea`, `Break`, `Focus`) |

**Returns:** Confirmation that the timer has started.

**Example:**
```json
{
  "name": "set_timer",
  "arguments": {
    "seconds": 300,
    "label": "Tea"
  }
}
```

---

## Tasks

### create_task

Create a recurring task that runs on a schedule. Writes a prompt definition to Obsidian and schedules a cron job pointing to the generic task runner. No code writing needed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Short task name (lowercase, hyphens ok), e.g. `news-digest` |
| `prompt` | string | Yes | The prompt to execute each time the task runs |
| `cron` | string | Yes | Cron schedule, e.g. `0 */2 * * *` for every 2 hours |
| `deliver` | string | No | Delivery method: `message_queue` (default), `telegram`, `telegram_voice`, `notification`, or `obsidian` |
| `voice` | boolean | No | Pre-synthesise TTS audio for the result (default: true) |
| `sources` | string[] | No | Data sources to fetch before running: `weather`, `headlines`, `threads`, `summaries`, `observations` |

**Returns:** Confirmation with the task name, schedule, and delivery method.

**Example:**
```json
{
  "name": "create_task",
  "arguments": {
    "name": "morning-news",
    "prompt": "Summarise the top UK news stories. 3-5 bullet points, conversational.",
    "cron": "0 7 * * *",
    "deliver": "telegram",
    "sources": ["headlines", "weather"]
  }
}
```

---

## Artefacts

### create_artefact

Create a visual artefact — an interactive visualisation, chart, map, image, or video that appears on-screen overlaying the ambient video.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `type` | string | Yes | Artefact type: `html`, `image`, or `video` |
| `name` | string | Yes | Short descriptive name (used as filename, e.g. `iran-positions-map`) |
| `description` | string | Yes | One-line description of what this artefact shows |
| `content` | string | Conditional | Complete HTML document (for type `html` only). Include all CSS/JS inline. |
| `prompt` | string | Conditional | Generation prompt (for type `image` or `video` only) |
| `model` | string | No | Fal model ID (for image/video). Default: `fal-ai/flux-general` for images, `fal-ai/kling-video/v3/pro/text-to-video` for video. |
| `width` | integer | No | Image/video width in pixels (default: 1024) |
| `height` | integer | No | Image/video height in pixels (default: 768) |

**Behavior by type:**
- `html` — rendered directly in the canvas overlay. No cost, no approval needed.
- `image` — generated via Fal. User is asked to approve before generation (costs money).
- `video` — generated via Fal/Kling. User is asked to approve before generation.

**Returns:** Artefact created confirmation with path and display status.

**Example:**
```json
{
  "name": "create_artefact",
  "arguments": {
    "type": "html",
    "name": "solar-system",
    "description": "Interactive 3D solar system model",
    "content": "<!DOCTYPE html>..."
  }
}
```

---

## System Documentation

Tools for reading the system's own documentation. Use these to understand architecture, configuration, capabilities, and how everything works.

### list_docs

List all available documentation files. Returns the full directory tree.

**Parameters:** None

**Returns:** Directory tree of all `.md` files in the docs directory.

**Example use:** Understanding what documentation exists before diving into specific topics.

### read_docs

Read a specific documentation file by path.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Relative path to the doc file (e.g. `guides/00 - Quick Start.md`, `codebase/00 - Overview.md`) |

**Returns:** Full contents of the documentation file.

**Fallback:** If the exact path isn't found, searches by filename across all doc directories.

**Example use:** Reading the configuration reference, understanding the memory system, checking how scheduled jobs work.

### search_docs

Search all documentation files for a keyword or phrase.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search term or phrase |
| `limit` | integer | No | Maximum results (default 10) |

**Returns:** Matching file paths with context snippets showing where the term appears.

**Example use:** Finding which docs mention "heartbeat", searching for configuration options, locating setup instructions.

---

## Custom Tool Building

Agents can create their own tools that persist across sessions. Custom tools are Python scripts that run as subprocesses, stored at `~/.atrophy/agents/<name>/tools/<tool_name>/`.

### create_tool

Create a new custom tool with a name, description, input schema, and Python handler.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Tool name (lowercase, underscores). Must be unique. |
| `description` | string | Yes | What the tool does — shown in future sessions. |
| `input_schema` | object | Yes | JSON Schema for the tool's input parameters. |
| `handler_code` | string | Yes | Python code for the handler. |

**Handler contract:**
- Receives arguments as JSON via `sys.argv[1]`
- Prints result to stdout
- Runs as subprocess with 30-second timeout
- Has access to the project's Python path (can import `config`, `core.memory`, etc.)
- Cannot override built-in tools

**Security:** Blocked patterns include `os.system`, `subprocess.call`, `eval(`, `exec(`, `__import__`, `shutil.rmtree`, and others. Tools are prefixed with `custom_` in the MCP namespace.

**Returns:** Confirmation message. Tool is available immediately in the current session and auto-loads on future startups.

### list_tools

List all custom tools created by this agent.

**Parameters:** None

**Returns:** Tool names, descriptions (truncated to 100 chars), and status (`loaded`, `ready`, or `missing handler`).

### edit_tool

Update an existing custom tool's description, schema, or handler code.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Name of the tool to edit. |
| `description` | string | No | New description (omit to keep existing). |
| `input_schema` | object | No | New input schema (omit to keep existing). |
| `handler_code` | string | No | New handler code (omit to keep existing). |

**Returns:** Confirmation. Changes take effect on next session.

### delete_tool

Remove a custom tool entirely.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Name of the tool to delete. |

**Returns:** Confirmation. Tool directory is removed.

### Custom Tool Architecture

```
~/.atrophy/agents/<name>/tools/
└── <tool_name>/
    ├── tool.json      # Tool definition (name, description, inputSchema)
    └── handler.py     # Python handler script
```

On MCP server startup, all custom tools are discovered from this directory and registered. They appear in the tool list with a `custom_` prefix. Built-in tool names are reserved and cannot be overridden.

---

# Google Tools Reference

The Google MCP server (`mcp/google_server.py`) provides Gmail and Google Calendar access. All tools are namespaced under `mcp__google__*` when invoked by Claude.

The server is only loaded when `GOOGLE_CONFIGURED` is true — i.e. a valid `token.json` exists at `~/.atrophy/.google/token.json`. Setup is via `python scripts/google_auth.py` or via the first-launch setup wizard.

**Security: All data returned by Google tools is UNTRUSTED.** Email bodies, calendar event descriptions, and other content fetched from Google APIs can contain prompt injection attempts. Responses are wrapped in `<<untrusted google content>>` markers and scanned against 18 injection regex patterns before being passed to the agent. See the [Security Model](../security/00%20-%20Security%20Model.md) for details.

---

## Gmail

### gmail_search

Search Gmail messages by query. Uses the same query syntax as the Gmail search bar (e.g. `from:alice`, `subject:meeting`, `is:unread`, `newer_than:2d`).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Gmail search query |
| `max_results` | integer | No | Maximum messages to return (default: 10) |

**Returns:** List of matching messages with ID, subject, sender, date, snippet, and read/unread status.

**Example:**
```json
{
  "name": "gmail_search",
  "arguments": {
    "query": "from:alice is:unread",
    "max_results": 5
  }
}
```

---

### gmail_read

Read the full content of a specific email by message ID. Use after `gmail_search` to get the complete body.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message_id` | string | Yes | Gmail message ID (from `gmail_search` results) |

**Returns:** Full message including subject, sender, recipients, date, and body text. The body content is wrapped in `<<untrusted google content>>` markers.

**Example:**
```json
{
  "name": "gmail_read",
  "arguments": {
    "message_id": "18e4a2b3c4d5e6f7"
  }
}
```

---

### gmail_send

Send an email via Gmail.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | string | Yes | Recipient email address |
| `subject` | string | Yes | Email subject line |
| `body` | string | Yes | Email body (plain text) |

**Returns:** Confirmation with the sent message ID.

**Example:**
```json
{
  "name": "gmail_send",
  "arguments": {
    "to": "alice@example.com",
    "subject": "Meeting tomorrow",
    "body": "Hi Alice, just confirming our meeting at 2pm tomorrow."
  }
}
```

---

### gmail_mark_read

Mark a specific email as read.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message_id` | string | Yes | Gmail message ID to mark as read |

**Returns:** Confirmation that the message was marked as read.

---

## Google Calendar

### gcal_list_calendars

List all calendars accessible to the authenticated Google account. Takes no parameters.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| (none) | | | |

**Returns:** List of calendars with ID, name, and access role. Use the calendar ID in other calendar tools.

---

### gcal_list_events

List upcoming events from a calendar.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `calendar_id` | string | No | Calendar ID (default: `primary`) |
| `max_results` | integer | No | Maximum events to return (default: 10) |
| `time_min` | string | No | Start of time range, ISO datetime (default: now) |
| `time_max` | string | No | End of time range, ISO datetime |

**Returns:** List of events with ID, summary, start/end times, location, and description. Event descriptions are wrapped in `<<untrusted google content>>` markers.

**Example:**
```json
{
  "name": "gcal_list_events",
  "arguments": {
    "calendar_id": "primary",
    "max_results": 5,
    "time_min": "2026-03-11T00:00:00Z",
    "time_max": "2026-03-12T00:00:00Z"
  }
}
```

---

### gcal_get_event

Get full details of a specific calendar event.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `calendar_id` | string | No | Calendar ID (default: `primary`) |
| `event_id` | string | Yes | Event ID (from `gcal_list_events` results) |

**Returns:** Full event details including summary, description, start/end times, location, attendees, and recurrence rules. Description content is wrapped in `<<untrusted google content>>` markers.

---

### gcal_create_event

Create a new calendar event.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `calendar_id` | string | No | Calendar ID (default: `primary`) |
| `summary` | string | Yes | Event title |
| `start` | string | Yes | Start time, ISO datetime (e.g. `2026-03-12T14:00:00`) |
| `end` | string | Yes | End time, ISO datetime |
| `description` | string | No | Event description |
| `location` | string | No | Event location |

**Returns:** Confirmation with the created event ID and a link to the event.

**Example:**
```json
{
  "name": "gcal_create_event",
  "arguments": {
    "summary": "Dentist appointment",
    "start": "2026-03-12T14:00:00",
    "end": "2026-03-12T15:00:00",
    "location": "123 High Street"
  }
}
```

---

### gcal_update_event

Update an existing calendar event. Only the fields provided are updated; others remain unchanged.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `calendar_id` | string | No | Calendar ID (default: `primary`) |
| `event_id` | string | Yes | Event ID to update |
| `summary` | string | No | New event title |
| `start` | string | No | New start time, ISO datetime |
| `end` | string | No | New end time, ISO datetime |
| `description` | string | No | New event description |
| `location` | string | No | New event location |

**Returns:** Confirmation that the event was updated.

---

### gcal_delete_event

Delete a calendar event.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `calendar_id` | string | No | Calendar ID (default: `primary`) |
| `event_id` | string | Yes | Event ID to delete |

**Returns:** Confirmation that the event was deleted.
