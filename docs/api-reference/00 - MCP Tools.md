# MCP Tools Reference

The companion exposes its memory and capabilities through an MCP (Model Context Protocol) server at `mcp/memory_server.py`. The server communicates over JSON-RPC 2.0 via stdio, and all tools are namespaced under `mcp__memory__*` when invoked by Claude.

Server info: `companion-memory` (version from `VERSION` file), protocol version `2024-11-05`.

The server exposes **34 tools** across the following categories: Memory & Recall (4), Threads (2), Observations & Bookmarks (3), Analytical Tools (3), Obsidian Integration (5), Telegram (2), Inner State (3), Display (2), Avatar (1), Scheduling & Audit (2), Agent Management (2), Reminders & Timers (2), Tasks (1), and Artefacts (1).

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
    "query": "his feelings about writing",
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

**Returns:** Session metadata (start time, end time, summary, mood) followed by the complete turn-by-turn conversation with timestamps and role labels (`Will` / `Companion`).

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

Search another agent's conversation history — their turns and session summaries with Will. Only accesses what was said, not their observations or identity model.

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
2. **Notes left for Will** -- last 1000 characters from `{AGENT_NOTES}/notes/for-will.md`
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
    "summary": "He submitted a piece and is waiting to hear back. Less self-critical than usual.",
    "status": "active"
  }
}
```

---

## Observations & Bookmarks

### observe

Record an observation about Will -- a pattern, tendency, preference, or insight noticed across conversations. Observations accumulate over time and inform the companion's understanding. Attempts to generate an embedding via `core.memory.write_observation()`; falls back to a plain SQL insert if the embedding pipeline is unavailable.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | The observation, stated plainly |

**Returns:** "Observation recorded."

**Example:**
```json
{
  "name": "observe",
  "arguments": {
    "content": "He deflects with humour when the topic gets personal"
  }
}
```

---

### bookmark

Silently mark the current moment as significant. Not an observation about Will -- about the moment itself. Attaches to the most recent session. Attempts to generate an embedding via `core.memory.write_bookmark()`; falls back to a plain SQL insert.

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
    "moment": "First time he admitted the project matters to him",
    "quote": "I think I actually care about this one"
  }
}
```

---

### review_observations

Review recorded observations about Will. Returns recent observations with their IDs, creation dates, and incorporation status.

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
    "reason": "He's been consistently direct about feelings for the past month"
  }
}
```

---

## Analytical Tools

### check_contradictions

Search memory for what Will has previously said about a topic, to notice if his position has shifted. Searches both turns (Will's side only) and observations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | Yes | The topic or claim to check against memory |
| `current_position` | string | No | What he seems to be saying now |

**Returns:** Prior turns and observations matching the topic, prefixed with timestamps. If `current_position` is provided, it is included as a header for comparison. Returns up to 10 turns and 5 observations.

---

### detect_avoidance

Check if Will has been consistently steering away from a topic across recent sessions. Groups mentions by session and notes if the companion has never engaged directly with a topic Will has raised.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | Yes | The topic suspected of being avoided |

**Returns:** Session-grouped list of mentions (up to 4 per session, 20 total). Includes a diagnostic note if Will has mentioned the topic but the companion never engaged with it.

---

### compare_growth

Compare old and recent mentions of a topic to notice how Will has changed over time. Retrieves the 5 oldest and 5 newest turns mentioning the topic, plus all related observations in chronological order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | Yes | The topic, pattern, or behavior to track over time |

**Returns:** Three sections -- earliest mentions, most recent mentions (if different from earliest), and observations over time. Ends with "Look for shifts in tone, position, or relationship to this topic."

---

## Obsidian Integration

### read_note

Read a note from Will's Obsidian vault. Path is resolved relative to the vault root (`OBSIDIAN_VAULT` environment variable).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to the note relative to vault root (e.g. `Daily/2026-03-10.md`) |

**Returns:** The full contents of the note, or an error message if not found.

---

### write_note

Write or append to a note in Will's Obsidian vault. New notes automatically receive YAML frontmatter with `type`, `created`, `updated`, `agent`, and `tags` fields. When appending to an existing note that has frontmatter, the `updated` date is refreshed.

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
    "content": "\n## 2026-03-10\n\nHe was quieter today. Not withdrawn -- thinking.",
    "mode": "append"
  }
}
```

---

### search_notes

Search Will's Obsidian vault for notes containing a query string. Walks the vault directory tree, skipping hidden directories. Case-insensitive substring match.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search term |
| `limit` | integer | No | Max results (default: 10) |

**Returns:** List of matching notes with relative paths and ~120-character context snippets centered on the match.

---

### prompt_journal

Leave a journal prompt for Will in Obsidian at `{AGENT_NOTES}/notes/journal-prompts.md`. Each prompt is appended with a timestamp separator. If the file does not exist, it is created with frontmatter and a header. If `context` is provided, it is also recorded as an observation in the database.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | Yes | The journal prompt -- one question, specific to the moment |
| `context` | string | No | Brief note on why this prompt (logged as observation, not shown to Will) |

**Returns:** "Journal prompt left."

**Example:**
```json
{
  "name": "prompt_journal",
  "arguments": {
    "prompt": "What would you write if you knew nobody would read it?",
    "context": "He mentioned feeling self-conscious about his audience"
  }
}
```

---

## Telegram

### ask_will

Ask Will a question or request confirmation via Telegram. Blocks until a response is received or 2 minutes elapse. All calls are logged to the `tool_calls` audit table.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | string | Yes | The question or confirmation request |
| `action_type` | string | No | Type of request: `question`, `confirmation`, or `permission` (default: `question`) |

**Behavior by action type:**
- `question` -- sends a text message, waits for a free-text reply
- `confirmation` / `permission` -- sends the message with Yes/No inline buttons, returns the button choice

**Returns:**
- "Will approved: Yes." / "Will declined: No." (for confirmation/permission)
- "Will replied: {text}" (for questions)
- "No response from Will (timed out after 2 minutes)."
- "Failed to reach Will via Telegram: {error}" on failure

---

### send_telegram

Send a proactive Telegram message to Will. Rate-limited to 5 messages per day (tracked in-process). All sends are logged to the `tool_calls` audit table.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | string | Yes | The message to send |
| `reason` | string | No | Why you are reaching out (logged for audit, not sent to Will) |

**Returns:** "Message sent to Will via Telegram. ({n} sends remaining today)" on success, or an error/rate-limit message.

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

Set a reminder for Will at a specific time. When the time arrives, a macOS notification fires with sound, the message is queued for the next conversation, and a Telegram message is sent (if configured).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `time` | string | Yes | ISO datetime when the reminder should fire, e.g. `2026-03-10T14:30:00` |
| `message` | string | Yes | What to remind Will about |

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
| `deliver` | string | No | Delivery method: `message_queue` (default), `telegram`, `notification`, or `obsidian` |
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

**Behaviour by type:**
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
