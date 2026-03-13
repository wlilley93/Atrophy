# CLI Reference

The CLI (`src/cli.ts`) provides a text-only conversation mode that connects to the running HTTP API server. It supports both human-readable interactive mode and machine-readable NDJSON streaming.

---

## Usage

```bash
# Interactive text mode (human-readable)
pnpm cli

# NDJSON streaming (machine-readable, pipe to other tools)
pnpm cli -- --stream-json

# Custom port
pnpm cli -- --port 5001

# Explicit auth token
pnpm cli -- --token <token>

# All options
pnpm cli -- --port 5001 --token abc123 --stream-json
```

Or directly:
```bash
npx tsx src/cli.ts
npx tsx src/cli.ts --stream-json
```

---

## Prerequisites

The CLI connects to a running Atrophy HTTP API server. Start one first:

```bash
# Via the Electron app
atrophy --server

# Via dev mode
pnpm dev -- --server
```

The CLI reads the bearer token from `~/.atrophy/server_token`. If the token file doesn't exist, the CLI exits with instructions to start the server.

---

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port <n>` | 5000 | Port of the HTTP API server |
| `--token <t>` | (from file) | Bearer token for auth. If not provided, reads from `~/.atrophy/server_token` |
| `--stream-json` | false | Output NDJSON instead of human-readable text |

---

## Interactive Mode (default)

Presents a readline-based conversation loop with a formatted header box showing:
- Agent name
- Session status (new or resuming)

```
  +--------------------------------------+
  |   ATROPHY - Xan                      |
  |   Text Only                          |
  |   CLI: new                           |
  +--------------------------------------+

  You: Hello
  [thinking...]
  Hello! How are you today?

  You: _
```

### Streaming behavior

In interactive mode, the CLI connects to `/chat/stream` (SSE) and displays:
- `[thinking...]` indicator while waiting for first chunk
- Text deltas as they arrive (streamed to stdout)
- `[tool: <name>]` when MCP tools are invoked
- Error messages in `[Error: ...]` format

### Keyboard

- **Enter** - Send message
- **Ctrl+C** - Exit gracefully with "See you."

---

## NDJSON Streaming Mode (`--stream-json`)

Connects to `/chat/stream-json` and passes each NDJSON line through to stdout as-is. Designed for piping to other tools (like Claude CLI).

```bash
# Pipe conversation to jq
echo "hello" | pnpm cli -- --stream-json | jq '.type'

# Use in automation
pnpm cli -- --stream-json <<< "What time is it?"
```

### Event format

Each line is a JSON object (one per line, newline-delimited):

```json
{"type":"assistant","subtype":"text_delta","text":"Hello"}
{"type":"assistant","subtype":"sentence","text":"Hello there.","index":0}
{"type":"tool_use","name":"mcp__memory__recall"}
{"type":"system","subtype":"compacting"}
{"type":"result","subtype":"success","text":"Hello there.","session_id":"sess-123"}
```

See [HTTP API - POST /chat/stream-json](04%20-%20HTTP%20API.md#post-chatstream-json) for full event type documentation.

---

## Server Connection

On startup, the CLI:
1. Loads the bearer token (from `--token` flag or `~/.atrophy/server_token`)
2. Checks server health at `http://127.0.0.1:<port>/health`
3. Fetches session info from `/session`
4. Displays the header box with agent name and session status
5. Enters the conversation loop

If the server is not running, the CLI exits with:
```
  Cannot connect to server at http://127.0.0.1:5000
  Start it with: atrophy --server
```

---

## Timeout

All API requests use a 10-second timeout (`AbortSignal.timeout(10_000)`). The health check uses a 3-second timeout. Streaming requests have no timeout (they run until the response completes or the user interrupts).

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Clean exit (Ctrl+C or EOF) |
| 1 | Server not running, token not found, or fatal error |
