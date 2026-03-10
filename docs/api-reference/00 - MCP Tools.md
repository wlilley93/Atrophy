# MCP Tools Reference

The companion exposes its memory and capabilities through an MCP (Model Context Protocol) server at `mcp/memory_server.py`. The server communicates over JSON-RPC 2.0 via stdio, and all tools are namespaced under `mcp__memory__*` when invoked by Claude.

Server info: `companion-memory` v1.0.0, protocol version `2024-11-05`.

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
