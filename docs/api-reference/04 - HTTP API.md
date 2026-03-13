# HTTP API Reference

The HTTP API server (`src/main/server.ts`) provides headless access to Atrophy's inference, memory, and session management. Port of the Python `server.py`.

---

## Architecture

```
HTTP Server (Node.js http module)
  Binds to 127.0.0.1:5000 (default)
  Bearer token auth (auto-generated)
        |
        v
  Route handlers
    /health, /status     (no auth)
    /chat                (sync response)
    /chat/stream         (SSE streaming)
    /chat/stream-json    (NDJSON streaming)
    /agents              (agent list)
    /memory/search       (vector search)
    /memory/threads      (active threads)
    /session             (session info)
```

---

## Starting the Server

The server starts in `--server` mode from the Electron main process:

```bash
# Via Electron
atrophy --server

# Via dev mode
pnpm dev -- --server
```

On startup, the server:
1. Loads or generates a bearer token at `~/.atrophy/server_token`
2. Initializes the SQLite database
3. Creates a new Session
4. Loads the system prompt
5. Binds to `127.0.0.1:5000`

---

## Authentication

All endpoints except `/health` and `/status` require a Bearer token.

The token is auto-generated on first run and stored at `~/.atrophy/server_token` with permissions `0600`. The token is a 32-byte `base64url`-encoded string (43 characters).

```bash
# Read the token
cat ~/.atrophy/server_token

# Use in requests
curl -H "Authorization: Bearer $(cat ~/.atrophy/server_token)" http://127.0.0.1:5000/session
```

Token comparison uses `crypto.timingSafeEqual()` to prevent timing attacks.

**Error response (401):**
```json
{"error": "unauthorized"}
```

---

## Endpoints

### GET /health

No auth required. Returns agent identity and server status.

**Response:**
```json
{
  "status": "ok",
  "agent": "xan",
  "display_name": "Xan"
}
```

### GET /status

No auth required. Returns agent identity and user presence status.

**Response:**
```json
{
  "status": "ok",
  "agent": "xan",
  "display_name": "Xan",
  "user_status": "online",
  "since": "2026-03-13T10:00:00.000Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `user_status` | string | `"online"` or `"away"` |
| `since` | string | ISO 8601 timestamp of last status change |

### POST /chat

Synchronous chat - sends a message, waits for full response. Auth required.

**Request:**
```json
{"message": "Hello, how are you?"}
```

**Response:**
```json
{
  "response": "I'm doing well, thanks for asking.",
  "session_id": "abc-123"
}
```

**Error responses:**

| Status | Body | Condition |
|--------|------|-----------|
| 400 | `{"error": "invalid json"}` | Malformed request body |
| 400 | `{"error": "empty message"}` | Missing or blank message |
| 429 | `{"error": "inference in progress"}` | Another request is being processed |
| 500 | `{"error": "..."}` | Inference engine error |

### POST /chat/stream

Server-Sent Events (SSE) streaming. Auth required. Returns text deltas as they arrive from Claude.

**Request:**
```json
{"message": "Tell me a story"}
```

**Response headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**Event types:**

| Event | Fields | Description |
|-------|--------|-------------|
| `text` | `content: string` | Partial text chunk |
| `tool` | `name: string` | MCP tool being invoked |
| `done` | `full_text: string` | Stream complete, full response |
| `error` | `message: string` | Error occurred |

**Example stream:**
```
data: {"type":"text","content":"Once upon "}

data: {"type":"text","content":"a time..."}

data: {"type":"tool","name":"mcp__memory__observe"}

data: {"type":"done","full_text":"Once upon a time..."}

```

**Client disconnect handling:** When the client disconnects mid-stream, the server releases the inference lock, removes event listeners, and stops the Claude subprocess.

### POST /chat/stream-json

NDJSON (Newline-Delimited JSON) streaming. Auth required. Compatible with Claude CLI `stream-json` format. One JSON object per line.

**Request:**
```json
{"message": "Tell me a story"}
```

**Response headers:**
```
Content-Type: application/x-ndjson
Cache-Control: no-cache
Connection: keep-alive
```

**Event types:**

| Type | Subtype | Fields | Description |
|------|---------|--------|-------------|
| `assistant` | `text_delta` | `text: string` | Partial text chunk |
| `assistant` | `sentence` | `text: string, index: number` | Complete sentence (for TTS) |
| `tool_use` | - | `name: string` | MCP tool invocation |
| `system` | `compacting` | - | Context window compaction |
| `result` | `success` | `text: string, session_id: string` | Stream complete |
| `result` | `error` | `error: string` | Error occurred |

**Example stream:**
```
{"type":"assistant","subtype":"text_delta","text":"Once upon "}
{"type":"assistant","subtype":"text_delta","text":"a time..."}
{"type":"assistant","subtype":"sentence","text":"Once upon a time...","index":0}
{"type":"tool_use","name":"mcp__memory__observe"}
{"type":"result","subtype":"success","text":"Once upon a time...","session_id":"sess-123"}
```

### GET /agents

Returns discovered agent list. Auth required.

**Response:**
```json
{
  "agents": [
    {"name": "xan", "displayName": "Xan", "enabled": true},
    {"name": "nova", "displayName": "Nova", "enabled": true}
  ]
}
```

### GET /memory/search?q=...&limit=...

Vector similarity search across agent memory. Auth required.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | required | Search query |
| `limit` | number | 10 | Max results |

**Response:**
```json
{
  "results": [
    {"content": "User mentioned loving rainy days", "score": 0.92, "source": "memory"}
  ]
}
```

**Error:** `{"error": "missing q parameter"}` (400) if `q` is empty.

### GET /memory/threads

Returns active conversation threads. Auth required.

**Response:**
```json
{
  "threads": [
    {"id": "thread-1", "topic": "Weekend plans", "turn_count": 8}
  ]
}
```

### GET /session

Returns current session info. Auth required.

**Response:**
```json
{
  "session_id": "abc-123",
  "cli_session_id": "cli-456",
  "agent": "xan",
  "display_name": "Xan"
}
```

---

## Body Size Limit

Request bodies are limited to 1MB (`MAX_BODY_SIZE = 1024 * 1024`). Requests exceeding this limit are rejected and the connection is destroyed.

---

## Concurrency

The server uses a simple lock (`inferLock`) to prevent concurrent inference. Only one `/chat`, `/chat/stream`, or `/chat/stream-json` request can run at a time. Additional requests receive a `429` response.

---

## Error Handling

All endpoints are wrapped in a try/catch that returns `{"error": "internal server error"}` (500) for unexpected errors. The error is logged via the `server` logger.

Unknown routes return `{"error": "not found"}` (404).
