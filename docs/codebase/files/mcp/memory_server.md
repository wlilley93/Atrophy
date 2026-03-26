# mcp/memory_server.py - MCP Memory Server

**Line count:** ~4817 lines  
**Dependencies:** `sqlite3`, `json`, `os`, `sys`, `pathlib`, `datetime`, `re`, `fcntl`  
**Purpose:** Expose companion memory as MCP tools for Claude to call during conversation

## Overview

This Python module implements the MCP (Model Context Protocol) memory server. It exposes the companion's SQLite memory as tools that Claude can call during conversation to recall past sessions, search history, review threads, and manage observations.

**Protocol:** JSON-RPC 2.0 over stdio

**Environment variables:**
- `COMPANION_DB` - Path to SQLite database
- `AGENT` - Agent name
- `OBSIDIAN_VAULT` - Obsidian vault path
- `AGENT_DIR` - Agent's Obsidian directory
- `ORG_DB` - Organization database path (optional)
- `ORG_SLUG` - Organization slug (optional)

## Tool Groups

The server exposes 9 grouped tools (v1.1.3+ architecture):

| Tool | Actions | Purpose |
|------|---------|---------|
| `memory` | remember, recall_session, recall_other_agent, search_similar, daily_digest | Memory recall and search |
| `threads` | get_threads, track_thread, manage_schedule, set_reminder, create_task | Thread and schedule management |
| `reflect` | observe, bookmark, review_observations, retire_observation, check_contradictions, detect_avoidance, compare_growth, prompt_journal | Observations and analysis |
| `notes` | read_note, write_note, search_notes, read_docs, search_docs, list_docs | Obsidian and docs access |
| `interact` | ask_user, send_telegram, defer_to_agent, create_agent, update_emotional_state, update_trust | Communication and agent management |
| `display` | render_canvas, render_memory_graph, set_timer, add_avatar_loop, create_artefact | Visual output and UI |
| `tools` | create_tool, list_tools, edit_tool, delete_tool | Custom tool management |
| `review_audit` | (standalone) | Audit log review |
| `self_status` | (standalone) | Full state snapshot |

## Action Routing

```python
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
    # ... more groups
}

def _route_grouped(params: dict) -> str:
    """Route grouped tool call to action handler."""
    action = params.get("action")
    if not action:
        return json.dumps({"error": "Missing 'action' parameter"})
    
    handler = _ACTION_ROUTES.get(group, {}).get(action)
    if not handler:
        return json.dumps({"error": f"Unknown action: {action}"})
    
    try:
        result = handler(params)
        return json.dumps({"content": result})
    except Exception as e:
        return json.dumps({"error": str(e)})
```

## Key Tools

### memory:remember

```python
def handle_remember(params: dict) -> str:
    """Hybrid search across all memory layers.
    
    Combines vector similarity and keyword matching.
    Searches observations, summaries, turns, bookmarks, and entities.
    """
    query = params.get("query", "")
    limit = params.get("limit", 10)
    
    # Vector search
    query_embedding = embed(query)
    vector_results = vector_search(query_embedding, limit=limit*2)
    
    # Keyword search (BM25)
    keyword_results = keyword_search(query, limit=limit*2)
    
    # Merge and rank
    merged = merge_results(vector_results, keyword_results, vector_weight=0.7)
    
    # Format results
    return format_results(merged[:limit])
```

**Parameters:**
- `query`: Search term
- `limit`: Max results (default 10)

**Returns:** Formatted search results from all memory layers.

### memory:recall_session

```python
def handle_recall_session(params: dict) -> str:
    """Full conversation replay from a specific session."""
    session_id = params.get("session_id")
    
    turns = db.execute(
        "SELECT role, content, timestamp FROM turns "
        "WHERE session_id = ? ORDER BY timestamp",
        (session_id,)
    ).fetchall()
    
    return format_turns(turns)
```

**Parameters:**
- `session_id`: Session ID to retrieve

**Returns:** All turns in chronological order.

### threads:track_thread

```python
def handle_track_thread(params: dict) -> str:
    """Create or update a conversation thread."""
    name = params.get("name")
    summary = params.get("summary", "")
    status = params.get("status", "active")
    
    # Upsert thread
    db.execute("""
        INSERT INTO threads (name, summary, status)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            summary = excluded.summary,
            status = excluded.status,
            last_updated = CURRENT_TIMESTAMP
    """, (name, summary, status))
    
    return f"Thread '{name}' updated with status: {status}"
```

**Parameters:**
- `name`: Thread name
- `summary`: Thread summary
- `status`: active, dormant, or resolved

### reflect:observe

```python
def handle_observe(params: dict) -> str:
    """Record an observation about the user."""
    content = params.get("content")
    source_turn = params.get("source_turn")
    confidence = params.get("confidence", 0.5)
    valid_from = params.get("valid_from")
    
    db.execute("""
        INSERT INTO observations 
        (content, source_turn, confidence, valid_from, learned_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (content, source_turn, confidence, valid_from))
    
    obs_id = db.last_insert_rowid()
    
    # Background embedding
    embed_async('observations', obs_id, content)
    
    return f"Observation recorded (ID: {obs_id})"
```

**Parameters:**
- `content`: Observation text
- `source_turn`: Source turn ID (optional)
- `confidence`: 0.0-1.0 confidence (default 0.5)
- `valid_from`: When fact became true (optional)

### interact:ask_user

```python
def handle_ask_user(params: dict) -> str:
    """Ask the user a question via GUI dialog.
    
    Blocks waiting for user response.
    """
    question = params.get("question")
    action_type = params.get("action_type", "question")  # question, confirmation, permission, secure_input
    input_type = params.get("input_type", "text")  # For secure_input: password, email, url, number
    label = params.get("label", "")  # For secure_input: field label
    destination = params.get("destination", "")  # Where to save secure input: secret:KEY or config:KEY
    
    # Write request file for main process to poll
    request_id = str(uuid.uuid4())
    write_ask_request(request_id, question, action_type, input_type, label, destination)
    
    # Poll for response
    response = poll_ask_response(request_id, timeout=300)
    
    return response
```

**Parameters:**
- `question`: Question to ask
- `action_type`: question, confirmation, permission, or secure_input
- `input_type`: For secure_input - password, email, url, number
- `label`: Field label for secure_input
- `destination`: Where to save secure input (secret:KEY or config:KEY)

**Returns:** User's response.

### interact:send_telegram

```python
def handle_send_telegram(params: dict) -> str:
    """Send a message to the user via Telegram."""
    message = params.get("message")
    
    # Write to switchboard queue for Electron app to process
    write_switchboard_envelope({
        "from": f"mcp:{AGENT_NAME}",
        "to": "telegram:daemon",
        "text": message,
        "type": "agent",
    })
    
    return "Message queued for Telegram delivery"
```

**Parameters:**
- `message`: Message to send

**Returns:** Confirmation of queued delivery.

## Switchboard Integration

The server can send messages to the Electron app via a file-based queue:

```python
SWITCHBOARD_QUEUE = os.path.expanduser("~/.atrophy/.switchboard_queue.json")

def write_switchboard_envelope(envelope: dict):
    """Write envelope to switchboard queue file."""
    # Atomic append with file locking
    with open(SWITCHBOARD_QUEUE, "r+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            queue = json.load(f)
            queue.append(envelope)
            f.seek(0)
            f.truncate()
            json.dump(queue, f)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

**Flow:**
1. MCP tool writes envelope to queue file
2. Electron app polls queue every 2 seconds
3. Electron app routes envelope via switchboard
4. Response routed back to MCP server

## Database Connection

```python
def get_db() -> sqlite3.Connection:
    """Get database connection with WAL mode."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

**Settings:**
- `journal_mode = WAL` - Concurrent reads during writes
- `foreign_keys = ON` - Referential integrity

## Embedding Integration

```python
def embed_async(table: str, row_id: int, text: str):
    """Fire-and-forget background embedding."""
    # Write to embedding queue for main process to process
    with open(EMBED_QUEUE, "a") as f:
        json.dump({
            "table": table,
            "row_id": row_id,
            "text": text,
        }, f)
        f.write("\n")
```

**Purpose:** Queue embeddings for main process to compute asynchronously.

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | SQLite database |
| `~/.atrophy/.switchboard_queue.json` | Switchboard message queue |
| `~/.atrophy/.embed_queue.json` | Embedding queue |
| `~/.atrophy/.ask_request.json` | Ask-user request file |
| `~/.atrophy/.ask_response.json` | Ask-user response file |

## Exported API

| Function | Purpose |
|----------|---------|
| `main()` | MCP server entry point |
| `handle_message(msg)` | Route JSON-RPC message |
| `handle_grouped_tool(group, params)` | Route grouped tool call |
| `handle_standalone_tool(name, params)` | Route standalone tool call |

## See Also

- `src/main/mcp-registry.ts` - MCP server registry in Electron
- `src/main/memory.ts` - Database operations in Electron
- `db/schema.sql` - Database schema
