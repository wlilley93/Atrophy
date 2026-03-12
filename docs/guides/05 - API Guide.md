# API Guide

Atrophy runs as a headless HTTP server for remote access, web frontends, and programmatic integration. No GUI, no TTS, no voice input - just a REST API over localhost.

The server is implemented in `src/main/server.ts` using Node's built-in `http` module (no Express or other framework). It runs inside the Electron main process, sharing the same config, database, and inference pipeline as the GUI mode. This design keeps the codebase simple - the server is just an alternative interface to the same underlying agent system.

---

## Starting the Server

The server runs when the `--server` flag is passed to the Electron app. It can be combined with `--port` to change the listening port and `AGENT` to select which agent handles requests:

```bash
pnpm dev -- --server                    # localhost:5000 (development)
pnpm dev -- --server --port 8080        # custom port
AGENT=oracle pnpm dev -- --server       # run a specific agent
```

In a packaged `.app`, pass the flags via the command line or configure the launch arguments.

### Startup sequence

When the server starts (`startServer()` in `src/main/server.ts`), it performs a complete initialization of the agent system. This is the same initialization that the GUI mode performs, minus the window creation and voice pipeline:

1. Loads or creates the bearer token from `~/.atrophy/server_token`
2. Initializes the SQLite database (`memory.initDb()`)
3. Creates a new `Session` and starts it (assigns a session ID, retrieves the last CLI session ID for conversation continuity)
4. Loads the system prompt via `loadSystemPrompt()` (four-tier resolution: Obsidian skills, local skills, user prompts, bundle prompts)
5. Creates an `http.Server` bound to `host:port`

### Startup output

On successful start, the server prints a summary block to the console. This output confirms the agent, URL, and authentication details. The token is partially masked to prevent accidental exposure in terminal scrollback:

```
  Atrophy - HTTP API
  Agent: Xan
  http://127.0.0.1:5000
  Token: AbCdEfGh...WxYz
  Token file: /Users/you/.atrophy/server_token
  Endpoints: /health, /chat, /chat/stream, /memory/search, /memory/threads, /session
  Auth: Bearer token required on all endpoints except /health
```

The token preview shows the first 8 and last 4 characters.

### Agent selection

The `AGENT` environment variable controls which agent is loaded (default: `xan`). The agent's system prompt, memory database, and identity are all resolved from that name. Changing the agent requires restarting the server - there is no runtime agent switching endpoint.

### Binding to a custom host

By default the server binds to `127.0.0.1` (localhost only), which means it is only accessible from the same machine. To expose it on all network interfaces - for example, to access the API from another machine on your LAN - use the `--host` flag:

```bash
pnpm dev -- --server --host 0.0.0.0              # All interfaces, default port
pnpm dev -- --server --host 0.0.0.0 --port 8080  # All interfaces, custom port
```

The `startServer()` function accepts `port` (default `5000`) and `host` (default `'127.0.0.1'`) parameters. Bearer token auth still applies on all endpoints except `/health`, but binding to `0.0.0.0` exposes the API to your entire network - use with caution.

### Stopping the server

`stopServer()` closes the HTTP server and ends the current session (which triggers summary generation if the session had 4+ turns). The server also stops automatically on `app.on('will-quit')`. There is no graceful drain of in-flight requests - if an inference is running when the server stops, it will be killed.

---

## Authentication

All endpoints except `/health` require a Bearer token. This provides a simple authentication layer that prevents unauthorized access to the agent's memory and conversation state.

### Token generation

The token is auto-generated on first server start and stored at a well-known path:

```
~/.atrophy/server_token
```

The file is created with `0600` permissions (owner read/write only). The token itself is a 32-byte URL-safe random string generated using Node's cryptographic random number generator:

```typescript
crypto.randomBytes(32).toString('base64url')
```

This produces a 43-character string (256 bits of entropy). If the file exists but is empty, a new token is generated. The same token is reused across server restarts unless you explicitly delete the file.

### Retrieving the token

Read the token from the file system. The file contains just the token string followed by a newline:

```bash
cat ~/.atrophy/server_token
```

Or read it programmatically in a Node.js client:

```typescript
import { readFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

const TOKEN = readFileSync(join(homedir(), '.atrophy', 'server_token'), 'utf-8').trim();
```

### Using the token

Include the token in the `Authorization` header on every request. The format follows the standard Bearer token scheme:

```
Authorization: Bearer <token>
```

The server checks the header by extracting the value after `Bearer ` and comparing it directly to the stored token. There is no session-based auth, no expiry, and no refresh mechanism.

### Authentication failure

If the token is missing, malformed, or incorrect, every protected endpoint returns a 401 response with a JSON error body:

```
HTTP/1.1 401
Content-Type: application/json

{"error": "unauthorized"}
```

### Rotating the token

Delete the token file and restart the server. A new token will be generated automatically. Any existing clients will need to read the new token from the file:

```bash
rm ~/.atrophy/server_token
# Restart the server - a new token is created
```

---

## Endpoints

The server supports 6 endpoints. All responses use `Content-Type: application/json` unless otherwise noted. Each endpoint is documented with its full request/response format, error cases, and behavioral details.

### Route matching

Routes are matched by exact pathname (the URL path before `?`) and HTTP method. The server uses a simple if/else chain in the request handler - there is no router framework. Any unmatched route returns a 404:

```
HTTP/1.1 404
Content-Type: application/json

{"error": "not found"}
```

---

### GET /health

Health check. **No authentication required.**

Returns the current agent's name and display name. Use this to verify the server is running and which agent is loaded. This is the only endpoint that does not require a Bearer token, making it suitable for monitoring tools and load balancers.

**Request:**

```
GET /health HTTP/1.1
Host: localhost:5000
```

**Response:**

```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "status": "ok",
  "agent": "xan",
  "display_name": "Xan"
}
```

**Response schema:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | Always `"ok"` |
| `agent` | `string` | Agent's internal name (directory name) |
| `display_name` | `string` | Agent's human-readable display name |

**Example:**

```bash
curl http://localhost:5000/health
```

```bash
# Expected output:
# {"status":"ok","agent":"xan","display_name":"Xan"}
```

---

### POST /chat

Send a message and receive the full response when inference completes. This is a blocking call - the HTTP response is not sent until the agent finishes generating its entire reply. Use this endpoint for simple integrations where you do not need real-time streaming.

**Authentication:** Required (Bearer token).

**Request:**

```
POST /chat HTTP/1.1
Host: localhost:5000
Authorization: Bearer <token>
Content-Type: application/json

{
  "message": "What have we been talking about lately?"
}
```

**Request schema:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | `string` | Yes | The user's message. Whitespace is trimmed; empty strings are rejected. |

**Success response (200):**

```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "response": "We've been discussing your work on the Electron rewrite, specifically the config module and how the three-tier resolution works. You also mentioned wanting to set up the heartbeat daemon.",
  "session_id": 42
}
```

**Response schema:**

| Field | Type | Description |
|-------|------|-------------|
| `response` | `string` | The agent's complete response text |
| `session_id` | `number` | The internal session ID (integer, from the `sessions` table) |

**Error responses:**

| Status | Body | Condition |
|--------|------|-----------|
| 400 | `{"error": "invalid json"}` | Request body is not valid JSON |
| 400 | `{"error": "empty message"}` | `message` field is missing, empty, or whitespace-only |
| 401 | `{"error": "unauthorized"}` | Missing or invalid Bearer token |
| 429 | `{"error": "inference in progress"}` | Another `/chat` or `/chat/stream` request is currently being processed |
| 500 | `{"error": "inference failed: ..."}` | The Claude CLI subprocess failed (error message from the stream is included) |

**Behavior details:**

The chat endpoint manages session state transparently. If no session exists when the first request arrives, one is created automatically. The full lifecycle of a single request is as follows:

- The server creates a `Session` on the first request if one does not exist
- The system prompt is loaded lazily on the first request
- The user's message is recorded as a turn in the session history before inference begins
- The agent's response is recorded as a turn after inference completes
- The CLI session ID is persisted for conversation continuity across requests
- A boolean mutex (`inferLock`) prevents concurrent inference. Only one `/chat` or `/chat/stream` request is processed at a time

**Example:**

```bash
TOKEN=$(cat ~/.atrophy/server_token)

curl -X POST http://localhost:5000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "How are you?"}'
```

```bash
# Expected output:
# {"response":"I'm here. What's on your mind?","session_id":1}
```

---

### POST /chat/stream

Send a message and receive a streaming response via Server-Sent Events (SSE). Tokens arrive incrementally as the agent generates them. This is the preferred endpoint for interactive UIs because the user sees text appearing in real time rather than waiting for the full response.

**Authentication:** Required (Bearer token).

**Request:**

```
POST /chat/stream HTTP/1.1
Host: localhost:5000
Authorization: Bearer <token>
Content-Type: application/json

{
  "message": "Tell me something interesting."
}
```

**Request schema:**

Same as `/chat` - a JSON body with a `message` field.

**Response headers:**

The response uses the standard SSE content type. The `Cache-Control` and `Connection` headers ensure the stream is not buffered by intermediaries:

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**SSE event format:**

Each event is a `data:` line containing a JSON object with a `type` field, followed by two newlines (`\n\n`). This follows the standard SSE specification:

```
data: {"type": "text", "content": "The"}\n\n
```

**Event types:**

The stream emits four types of events. Text events arrive most frequently (one per token chunk), while tool and done events mark significant state transitions:

| Type | Fields | Description |
|------|--------|-------------|
| `text` | `content: string` | A chunk of generated text. These arrive incrementally as the model generates tokens. |
| `tool` | `name: string` | The agent invoked an MCP tool. The `name` field contains the tool name (e.g. `"remember"`, `"search_memory"`, `"read_thread"`). |
| `error` | `message: string` | An error occurred during inference. The stream ends after this event. |
| `done` | `full_text: string` | Generation complete. Contains the full assembled response text. This is always the last event. |

**Complete SSE stream example:**

This example shows a typical stream with text generation, a tool invocation in the middle, and the final done event. Notice how text events can split words at arbitrary boundaries:

```
data: {"type": "text", "content": "The"}

data: {"type": "text", "content": " interesting thing"}

data: {"type": "text", "content": " about memory is"}

data: {"type": "text", "content": "..."}

data: {"type": "tool", "name": "search_memory"}

data: {"type": "text", "content": " I recall that you mentioned"}

data: {"type": "text", "content": " working on the config module"}

data: {"type": "text", "content": " last week."}

data: {"type": "done", "full_text": "The interesting thing about memory is... I recall that you mentioned working on the config module last week."}
```

**Error responses (before streaming starts):**

These errors are returned as standard HTTP responses before the SSE stream begins:

| Status | Body | Condition |
|--------|------|-----------|
| 400 | `{"error": "invalid json"}` | Request body is not valid JSON |
| 400 | `{"error": "empty message"}` | `message` field is missing, empty, or whitespace-only |
| 401 | `{"error": "unauthorized"}` | Missing or invalid Bearer token |
| 429 | `{"error": "inference in progress"}` | Another request is currently being processed |

Note: If an error occurs after the SSE stream has started (headers already sent with 200), the error is delivered as an SSE event with `type: "error"` rather than as an HTTP status code. This is a consequence of the SSE protocol - once the 200 response has been sent, the status code cannot be changed.

**Behavior details:**

The streaming endpoint shares the same session management as `/chat`. The key differences are in how events are delivered and when the mutex is released:

- Same session and turn management as `/chat`
- The mutex (`inferLock`) is released when the `done` or `error` event is emitted
- The connection is closed (`res.end()`) after `done` or `error`
- Text delta events correspond to raw token chunks from the Claude CLI - they may split words at arbitrary boundaries

**Example with curl:**

The `-N` flag is essential for seeing SSE events in real time. Without it, curl buffers the output and you see nothing until the stream ends:

```bash
TOKEN=$(cat ~/.atrophy/server_token)

curl -N -X POST http://localhost:5000/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me something interesting."}'
```

**Parsing SSE events:**

Each line starting with `data: ` contains a JSON payload. Lines not starting with `data: ` (including empty lines) should be ignored. The double newline `\n\n` separates events. Here is pseudocode for a minimal SSE parser:

```
// Pseudo-code for parsing
for each line in stream:
    if line starts with "data: ":
        payload = JSON.parse(line.substring(6))
        switch payload.type:
            "text"  -> append payload.content to output
            "tool"  -> display tool usage indicator
            "error" -> handle error, stop reading
            "done"  -> stream complete, payload.full_text has the full response
```

---

### GET /memory/search

Search the agent's memory using vector search. Queries are embedded and compared against stored embeddings for semantic similarity. This endpoint is useful for building external tools that need to query what the agent remembers about specific topics.

**Authentication:** Required (Bearer token).

**Request:**

```
GET /memory/search?q=project+deadline&limit=5 HTTP/1.1
Host: localhost:5000
Authorization: Bearer <token>
```

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `q` | `string` | Yes | - | Search query text. URL-encoded. |
| `limit` | `integer` | No | `10` | Maximum number of results to return. |

**Success response (200):**

```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "results": [
    {
      "content": "The user mentioned they've been working on the Electron rewrite, specifically porting the config module.",
      "score": 0.82,
      "source": "turns",
      "timestamp": "2026-03-09T14:30:00"
    },
    {
      "content": "Discussion about the three-tier config resolution and how agent-level settings override user-level settings.",
      "score": 0.76,
      "source": "summaries",
      "timestamp": "2026-03-09T15:00:00"
    }
  ]
}
```

**Result schema:**

Each result object contains the matched content, a similarity score, and metadata about where it came from:

| Field | Type | Description |
|-------|------|-------------|
| `results` | `array` | Array of search result objects |
| `results[].content` | `string` | The matched text content |
| `results[].score` | `number` | Similarity score (0.0 to 1.0, higher is more relevant) |
| `results[].source` | `string` | Source table (e.g. `"turns"`, `"summaries"`, `"observations"`) |
| `results[].timestamp` | `string` | ISO 8601 timestamp of the matched content |

**Error responses:**

| Status | Body | Condition |
|--------|------|-----------|
| 400 | `{"error": "missing q parameter"}` | `q` parameter is missing or empty |
| 401 | `{"error": "unauthorized"}` | Missing or invalid Bearer token |

**Example:**

```bash
TOKEN=$(cat ~/.atrophy/server_token)

curl "http://localhost:5000/memory/search?q=project+deadline&limit=5" \
  -H "Authorization: Bearer $TOKEN"
```

**Notes:**

The search uses the `vectorSearch()` function from `src/main/vector-search.ts`, which performs a hybrid keyword and semantic search. Results are ranked by cosine similarity between the query embedding and stored embeddings. The embedding model is `all-MiniLM-L6-v2` (384 dimensions) running locally via Transformers.js - no data is sent to external services. This endpoint is not affected by the inference mutex and responds immediately, making it safe to call while an inference is in progress.

---

### GET /memory/threads

List active conversation threads from the agent's memory. Threads represent ongoing topics or projects that the agent is tracking across sessions. This endpoint gives external tools visibility into what the agent considers its current active areas of conversation.

**Authentication:** Required (Bearer token).

**Request:**

```
GET /memory/threads HTTP/1.1
Host: localhost:5000
Authorization: Bearer <token>
```

**Success response (200):**

```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "threads": [
    {
      "id": 1,
      "name": "Electron rewrite",
      "last_updated": "2026-03-09T14:30:00",
      "summary": "Porting the Python companion app to Electron/TypeScript/Svelte. Currently working on config, memory, and inference modules.",
      "status": "active"
    },
    {
      "id": 2,
      "name": "career transition",
      "last_updated": "2026-03-08T20:00:00",
      "summary": "Discussing potential move to a new role. Weighing stability against growth.",
      "status": "active"
    }
  ]
}
```

**Thread schema:**

Each thread object contains identifying information, a summary of the topic, and its current status:

| Field | Type | Description |
|-------|------|-------------|
| `threads` | `array` | Array of thread objects |
| `threads[].id` | `number` | Thread ID |
| `threads[].name` | `string` | Thread name/title |
| `threads[].last_updated` | `string\|null` | ISO 8601 timestamp of last update |
| `threads[].summary` | `string\|null` | Brief summary of the thread |
| `threads[].status` | `string` | Thread status: `"active"`, `"dormant"`, or `"resolved"` |

**Error responses:**

| Status | Body | Condition |
|--------|------|-----------|
| 401 | `{"error": "unauthorized"}` | Missing or invalid Bearer token |

**Example:**

```bash
TOKEN=$(cat ~/.atrophy/server_token)

curl http://localhost:5000/memory/threads \
  -H "Authorization: Bearer $TOKEN"
```

**Notes:**

This endpoint uses `memory.getActiveThreads()` which returns threads with `status = 'active'`. Dormant and resolved threads are excluded from the response. This endpoint is not affected by the inference mutex and responds immediately.

---

### GET /session

Current session metadata. Returns information about the running server session and the active agent. Use this to check the server's state without triggering any side effects - it reads from in-memory state only.

**Authentication:** Required (Bearer token).

**Request:**

```
GET /session HTTP/1.1
Host: localhost:5000
Authorization: Bearer <token>
```

**Success response (200):**

```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "session_id": 42,
  "cli_session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "agent": "xan",
  "display_name": "Xan"
}
```

**Response schema:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `number\|null` | Internal session ID (from the `sessions` table). `null` if no session has been created yet. |
| `cli_session_id` | `string\|null` | Claude CLI session ID (used for `--resume`). `null` if no inference has run yet. |
| `agent` | `string` | Agent's internal name |
| `display_name` | `string` | Agent's human-readable display name |

**Error responses:**

| Status | Body | Condition |
|--------|------|-----------|
| 401 | `{"error": "unauthorized"}` | Missing or invalid Bearer token |

**Example:**

```bash
TOKEN=$(cat ~/.atrophy/server_token)

curl http://localhost:5000/session \
  -H "Authorization: Bearer $TOKEN"
```

**Notes:**

The `session_id` is an integer assigned by the SQLite database when the session is created. The `cli_session_id` is a UUID assigned by the Claude CLI on first inference and reused for conversation continuity via the `--resume` flag. This endpoint is not affected by the inference mutex and responds immediately.

---

## Error Handling

The server uses a consistent error format across all endpoints. Understanding the error model helps clients handle failures gracefully.

### Error response format

All errors return JSON with an `error` field containing a human-readable description:

```json
{"error": "description of what went wrong"}
```

### HTTP status codes

The server uses standard HTTP status codes. The table below lists every status code the server can return, along with the situations that trigger each one:

| Status | Meaning | When it occurs |
|--------|---------|----------------|
| 200 | Success | Request processed successfully |
| 400 | Bad request | Missing or empty required field, invalid JSON body |
| 401 | Unauthorized | Missing or invalid Bearer token |
| 404 | Not found | Unknown endpoint or wrong HTTP method |
| 429 | Too many requests | Inference already in progress (mutex held) |
| 500 | Server error | Inference failure, internal exception, or unhandled error |

### Unhandled exceptions

The request handler wraps all route logic in a try/catch. If any route throws an unhandled exception, the server returns a generic 500 error rather than exposing internal details. The actual exception is logged to stdout for debugging:

```
HTTP/1.1 500
Content-Type: application/json

{"error": "internal server error"}
```

The exception is logged to stdout: `[server] Error handling POST /chat: <error>`.

### Streaming errors

For `/chat/stream`, errors that occur after the SSE response headers have been sent (HTTP 200 already written) are delivered as SSE events rather than HTTP status codes. This is a fundamental constraint of HTTP - once the response has started, the status code cannot be changed:

```
data: {"type": "error", "message": "inference failed: Claude CLI process exited with code 1"}
```

The stream is then closed. The inference mutex is released.

---

## Concurrency Model

The server holds a boolean mutex (`inferLock`) during inference. This is a deliberate design choice rather than a limitation - the agent maintains conversational state (session history, CLI session ID, turn order) and concurrent inference would corrupt it.

The implications of this model are:

- **One inference at a time**: Only one `/chat` or `/chat/stream` request is processed at a time
- **No queuing**: Additional inference requests receive `429` immediately rather than waiting
- **Non-blocking reads**: `/health`, `/memory/search`, `/memory/threads`, and `/session` are never blocked by inference and respond immediately
- **Turn ordering**: The mutex ensures the agent's conversational state is never corrupted by concurrent writes

### Practical implications

If you are building a client that sends messages programmatically, you need to account for the single-inference constraint:

1. Wait for the response (or SSE `done` event) before sending the next message
2. Handle `429` gracefully - retry after a short delay or display "agent is thinking"
3. Use `/session` to check the current state without triggering inference

---

## Session Lifecycle in Server Mode

The server creates a single `Session` on startup. This session persists across all requests until the server is stopped, maintaining conversation continuity for the entire server lifetime.

### Session creation

On `startServer()`, the session is initialized with full state:

1. A new session row is inserted into the `sessions` table
2. The last CLI session ID is retrieved for conversation continuity
3. The system prompt is loaded

### Turn recording

Each `/chat` or `/chat/stream` request records two turns. The user turn is written before inference begins, and the agent turn is written after inference completes:

1. Records the user's message as a `will` turn
2. After inference completes, records the agent's response as an `agent` turn
3. Updates the CLI session ID if it changed

### Session end

On `stopServer()`, the session is finalized with a summary. The summary generation uses a oneshot inference call that is separate from the conversation stream:

1. If the session has 4+ turns, a summary is generated via `runInferenceOneshot()` using a summarization prompt
2. The summary is stored in the `summaries` table
3. The session row is updated with `ended_at`, summary, and mood

---

## Configuration

### Relevant environment variables

These environment variables affect server mode behavior. They use the same resolution system as the GUI mode, so values can come from the shell, `config.json`, or agent manifest:

| Variable | Default | Effect on server mode |
|----------|---------|----------------------|
| `AGENT` | `xan` | Which agent to load |
| `ATROPHY_DATA` | `~/.atrophy` | Root for runtime data (token file, memory DBs) |
| `CLAUDE_BIN` | `claude` | Path to Claude CLI binary used for inference |
| `CLAUDE_EFFORT` | `medium` | Inference effort level (`low`, `medium`, `high`) |
| `ADAPTIVE_EFFORT` | `true` | Auto-adjust effort by query complexity |
| `PYTHON_PATH` | (auto-detected) | Path to Python 3 binary for MCP servers |
| `OBSIDIAN_VAULT` | (default path) | Path to Obsidian vault for prompt resolution |

### How server mode differs from GUI/App

Server mode intentionally omits all GUI-specific features. The following table provides a complete feature comparison so you know exactly what is and is not available when running headless:

| Feature | GUI/App | Server |
|---------|---------|--------|
| Voice input | Yes | No |
| TTS output | Yes | No |
| Avatar | Yes | No |
| Wake words | Yes | No |
| Window / tray | Yes | No |
| Dock icon | Visible (GUI) or hidden (app) | Hidden |
| Heartbeat/cron | Via launchd jobs | Via launchd jobs (independent) |
| Memory | Full | Full |
| MCP tools | Full | Full |
| Session tracking | Full | Full |
| Emotional state | Updated per turn | Not updated (no agency context in server mode) |
| Agent deferral | Supported | Not supported |
| Sentinel checks | 5-minute interval | Not running |
| Queue polling | 10-second interval | Not running |

### Server-specific behavior

The server mode initializes its own session and system prompt independently. It does not share state with the GUI mode - if both are running, they maintain separate sessions (though they share the same memory database, which could lead to conflicts). For this reason, running both modes simultaneously against the same agent is not recommended.

---

## Integration Examples

These examples demonstrate how to connect to the API from different languages and environments. Each example covers the full set of endpoints - health check, blocking chat, streaming chat, memory search, thread listing, and session info.

### TypeScript / Node.js

This example uses Node's built-in `fetch` (available in Node 18+) to interact with all endpoints. It reads the token from the filesystem and demonstrates both blocking and streaming chat:

```typescript
import { readFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

const BASE = 'http://localhost:5000';
const TOKEN = readFileSync(join(homedir(), '.atrophy', 'server_token'), 'utf-8').trim();
const HEADERS = {
  Authorization: `Bearer ${TOKEN}`,
  'Content-Type': 'application/json',
};

// Health check
const health = await fetch(`${BASE}/health`);
const healthData = await health.json();
console.log(`Agent: ${healthData.display_name} (${healthData.agent})`);

// Simple chat
const resp = await fetch(`${BASE}/chat`, {
  method: 'POST',
  headers: HEADERS,
  body: JSON.stringify({ message: 'Hello' }),
});
const data = await resp.json();
console.log(data.response);

// Streaming chat
const stream = await fetch(`${BASE}/chat/stream`, {
  method: 'POST',
  headers: HEADERS,
  body: JSON.stringify({ message: 'Tell me about my week' }),
});
const reader = stream.body!.getReader();
const decoder = new TextDecoder();
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const text = decoder.decode(value);
  for (const line of text.split('\n')) {
    if (line.startsWith('data: ')) {
      const event = JSON.parse(line.slice(6));
      switch (event.type) {
        case 'text':
          process.stdout.write(event.content);
          break;
        case 'tool':
          console.log(`\n[tool: ${event.name}]`);
          break;
        case 'error':
          console.error(`\nError: ${event.message}`);
          break;
        case 'done':
          console.log('\n--- Done ---');
          break;
      }
    }
  }
}

// Memory search
const searchResp = await fetch(
  `${BASE}/memory/search?q=project+deadline&limit=5`,
  { headers: HEADERS },
);
const results = await searchResp.json();
for (const r of results.results) {
  console.log(`[${r.score.toFixed(2)}] ${r.content}`);
}

// Get active threads
const threadsResp = await fetch(`${BASE}/memory/threads`, { headers: HEADERS });
const threads = await threadsResp.json();
for (const t of threads.threads) {
  console.log(`${t.name} (${t.status}): ${t.summary}`);
}

// Session info
const sessionResp = await fetch(`${BASE}/session`, { headers: HEADERS });
const sessionData = await sessionResp.json();
console.log(`Session: ${sessionData.session_id}, CLI: ${sessionData.cli_session_id}`);
```

### JavaScript (Browser)

This browser example demonstrates both blocking and streaming chat with DOM updates. Note that the token must be provided manually since the browser cannot read the filesystem:

```javascript
const BASE = 'http://localhost:5000';
const TOKEN = 'your-token-here'; // Retrieve from server_token file
const headers = {
  Authorization: `Bearer ${TOKEN}`,
  'Content-Type': 'application/json',
};

// Simple chat
const resp = await fetch(`${BASE}/chat`, {
  method: 'POST',
  headers,
  body: JSON.stringify({ message: 'Hello' }),
});
const data = await resp.json();
console.log(data.response);

// Streaming chat with DOM updates
const outputEl = document.getElementById('output');
const stream = await fetch(`${BASE}/chat/stream`, {
  method: 'POST',
  headers,
  body: JSON.stringify({ message: 'Tell me about my week' }),
});

const reader = stream.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const text = decoder.decode(value);
  for (const line of text.split('\n')) {
    if (line.startsWith('data: ')) {
      const event = JSON.parse(line.slice(6));
      if (event.type === 'text') {
        outputEl.textContent += event.content;
      } else if (event.type === 'tool') {
        outputEl.textContent += `\n[using ${event.name}]\n`;
      } else if (event.type === 'done') {
        console.log('Stream complete');
      } else if (event.type === 'error') {
        outputEl.textContent += `\nError: ${event.message}`;
      }
    }
  }
}
```

### Python (requests)

This Python example uses the `requests` library for synchronous calls and its streaming mode for SSE. The token is read from the filesystem using `pathlib`:

```python
import json
from pathlib import Path

import requests

BASE = "http://localhost:5000"
TOKEN = (Path.home() / ".atrophy" / "server_token").read_text().strip()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# Health check (no auth needed)
health = requests.get(f"{BASE}/health")
print(f"Agent: {health.json()['display_name']}")

# Simple chat
resp = requests.post(f"{BASE}/chat", headers=HEADERS, json={"message": "Hello"})
data = resp.json()
print(data["response"])

# Streaming chat
resp = requests.post(
    f"{BASE}/chat/stream",
    headers=HEADERS,
    json={"message": "Tell me about my week"},
    stream=True,
)
for line in resp.iter_lines(decode_unicode=True):
    if line.startswith("data: "):
        event = json.loads(line[6:])
        if event["type"] == "text":
            print(event["content"], end="", flush=True)
        elif event["type"] == "tool":
            print(f"\n[tool: {event['name']}]", end="", flush=True)
        elif event["type"] == "error":
            print(f"\nError: {event['message']}")
        elif event["type"] == "done":
            print()

# Memory search
resp = requests.get(
    f"{BASE}/memory/search",
    headers=HEADERS,
    params={"q": "project deadline", "limit": 5},
)
for r in resp.json()["results"]:
    print(f"[{r['score']:.2f}] {r['content']}")

# List threads
resp = requests.get(f"{BASE}/memory/threads", headers=HEADERS)
for t in resp.json()["threads"]:
    print(f"{t['name']} ({t['status']})")

# Session info
resp = requests.get(f"{BASE}/session", headers=HEADERS)
session = resp.json()
print(f"Session: {session['session_id']}, Agent: {session['display_name']}")
```

### curl (shell scripts)

This shell script demonstrates all endpoints using curl and jq for JSON formatting. It reads the token once and reuses it across all requests:

```bash
#!/usr/bin/env bash
# Atrophy API shell client

BASE="http://localhost:5000"
TOKEN=$(cat ~/.atrophy/server_token)

# Health check
echo "--- Health ---"
curl -s "$BASE/health" | jq .

# Chat
echo "--- Chat ---"
curl -s -X POST "$BASE/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}' | jq .

# Streaming chat (prints events as they arrive)
echo "--- Stream ---"
curl -N -s -X POST "$BASE/chat/stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me something interesting."}'

# Memory search
echo "--- Memory Search ---"
curl -s "$BASE/memory/search?q=project+deadline&limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Threads
echo "--- Threads ---"
curl -s "$BASE/memory/threads" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Session
echo "--- Session ---"
curl -s "$BASE/session" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

### JavaScript (EventSource - GET only)

The `/chat/stream` endpoint uses POST, so the native `EventSource` API (which only supports GET) cannot be used directly. Use `fetch` with a streaming reader as shown in the browser example above, or a library like `eventsource-parser` that supports custom fetch requests.

---

## Complete Endpoint Reference

This table provides a quick-reference summary of all endpoints, their authentication requirements, and whether they are affected by the inference mutex:

| Method | Path | Auth | Description | Mutex |
|--------|------|------|-------------|-------|
| GET | `/health` | No | Health check with agent info | No |
| POST | `/chat` | Yes | Blocking chat - full response | Yes |
| POST | `/chat/stream` | Yes | Streaming chat via SSE | Yes |
| GET | `/memory/search` | Yes | Vector search over agent memory | No |
| GET | `/memory/threads` | Yes | List active conversation threads | No |
| GET | `/session` | Yes | Current session metadata | No |

---

## Implementation Notes

These details are relevant if you are extending the server or debugging issues. They describe implementation choices that affect behavior:

- The server uses Node's built-in `http` module, not Express or any framework. This keeps the dependency surface minimal.
- Request body parsing is manual (`parseBody()` reads chunks and concatenates). There is no automatic JSON parsing middleware.
- Query string parsing is manual (`parseQuery()` splits on `&` and `=`). This handles simple cases but does not support nested parameters or arrays.
- No CORS headers are set by default - if you need cross-origin access from a browser, you would need to modify `src/main/server.ts` or use a reverse proxy.
- No rate limiting beyond the inference mutex. Read endpoints (`/health`, `/memory/search`, etc.) have no throttling.
- No request size limits beyond Node's default (the body is read fully into memory). Very large messages could theoretically consume significant memory.
- For production use behind a reverse proxy, bind to `127.0.0.1` (the default) and proxy from nginx or similar. This adds TLS termination and request size limits.
