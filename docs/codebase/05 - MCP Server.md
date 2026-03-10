# MCP Server

`mcp/memory_server.py` exposes the companion's memory and capabilities as MCP tools. Protocol is JSON-RPC 2.0 over stdio.

## Configuration

The MCP server is launched as a subprocess by the `claude` CLI. Configuration is written to `mcp/config.json` at runtime:

```json
{
  "mcpServers": {
    "memory": {
      "command": "/path/to/python",
      "args": ["mcp/memory_server.py"],
      "env": {
        "COMPANION_DB": "agents/<name>/data/memory.db",
        "OBSIDIAN_VAULT": "~/Library/Mobile Documents/.../The Atrophied Mind",
        "OBSIDIAN_AGENT_DIR": "<vault>/<agent_display_name>",
        "OBSIDIAN_AGENT_NOTES": "<vault>/<agent>/agents/<name>",
        "AGENT": "<name>"
      }
    }
  }
}
```

All tools are namespaced as `mcp__memory__*` in the Claude CLI's allowedTools list.

## Memory Tools

### remember

Hybrid search across all memory layers. Uses vector + BM25 search from `core/vector_search.py`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Search term or phrase |
| `limit` | integer | no | Max results per category (default 10) |

### recall_session

Full conversation replay from a specific session.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | integer | yes | Session ID to retrieve |

### get_threads

List conversation threads filtered by status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | string | no | `active`, `dormant`, `resolved`, or `all` (default: `active`) |

### track_thread

Create or update a conversation thread.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Short recognisable label |
| `summary` | string | no | Current state description |
| `status` | string | no | `active`, `dormant`, or `resolved` |

### observe

Record an observation about the user.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | yes | What was noticed, stated plainly |

### bookmark

Mark a moment as significant.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `moment` | string | yes | What made this moment significant |
| `quote` | string | no | The exact words that mattered |

### review_observations

Review past observations with their IDs.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | no | Number to review (default 15) |

### retire_observation

Remove an observation that no longer holds.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `observation_id` | integer | yes | Observation to retire |
| `reason` | string | no | Why it no longer holds |

### check_contradictions

Search memory for what the user previously said about a topic to detect shifts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | yes | Topic or claim to check |
| `current_position` | string | no | What the user seems to be saying now |

### detect_avoidance

Check if the user has been consistently steering away from a topic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | yes | Topic suspected of being avoided |

### compare_growth

Compare old observations against recent ones to notice changes over time.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | yes | Pattern or behavior to track |

### search_similar

Pure vector search -- find semantically similar memories (no keyword component).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | yes | Concept to find similar memories for |
| `limit` | integer | no | Max results (default 5) |

### daily_digest

Read recent reflections and session summaries for day-start orientation. No parameters.

## Communication Tools

### ask_will

Send a question or confirmation request to the user via Telegram. Blocks until reply (up to 2 minutes).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | string | yes | Question or request |
| `action_type` | string | no | `question`, `confirmation`, or `permission` |

For `confirmation`/`permission`, sends Yes/No inline keyboard buttons. For `question`, sends a message and waits for a text reply.

### send_telegram

Send a proactive Telegram message. Rate limited to 5 per day.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | string | yes | Message to send |
| `reason` | string | no | Why (logged for audit, not sent) |

## Obsidian Tools

### read_note

Read a note from the Obsidian vault.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Path relative to vault root |

### write_note

Write or append to a note. New notes get YAML frontmatter (type, created, updated, agent, tags).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Path relative to vault root |
| `content` | string | yes | Markdown content |
| `mode` | string | no | `overwrite` or `append` (default: `append`) |

### search_notes

Search the vault for notes containing a query.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Search term |
| `limit` | integer | no | Max results (default 10) |

### prompt_journal

Leave a journal prompt for the user in Obsidian.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | yes | One question, specific to the moment |
| `context` | string | no | Why this prompt (for the companion's memory) |

## Emotional State Tools

### update_emotional_state

Manually adjust emotional state for nuanced shifts beyond automatic detection.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `deltas` | object | yes | e.g., `{"connection": 0.1, "frustration": -0.05}` |

### update_trust

Adjust trust in a specific domain. Max +/-0.05 per call.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `domain` | string | yes | `emotional`, `intellectual`, `creative`, or `practical` |
| `delta` | number | yes | Amount to adjust |

## Display Tools

### render_canvas

Render HTML to the canvas overlay in the GUI window.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `html` | string | yes | Complete HTML document |

### render_memory_graph

Generate and render a visual graph of threads and observations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `focus` | string | no | Thread or entity to highlight |

## Autonomy Tools

### manage_schedule

View or modify launchd scheduled tasks.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `list`, `add`, `remove`, or `edit` |
| `name` | string | no | Job name (for add/remove/edit) |
| `cron` | string | no | Cron schedule (for add/edit) |
| `script` | string | no | Script path (for add) |

### review_audit

Review the tool call audit log.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | no | Recent entries to show (default 20) |
| `flagged_only` | boolean | no | Only show flagged calls |
