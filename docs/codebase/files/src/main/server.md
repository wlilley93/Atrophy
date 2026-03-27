# src/main/server.ts - HTTP API Server

**Dependencies:** `http`, `fs`, `path`, `crypto`, `./config`, `./memory`, `./session`, `./context`, `./inference`, `./vector-search`, `./logger`  
**Purpose:** Minimal HTTP API for headless access to chat, memory, and status

## Overview

This module exposes a minimal HTTP API using Node.js built-in `http` module (no Express/Flask dependency). It runs headless - no GUI, no TTS, no voice input. All endpoints except `/health` require bearer token authentication.

## Security

- Binds to localhost only by default (configurable via `--host`)
- Bearer token auth required on all endpoints except `/health`
- Token auto-generated on first run, stored in `~/.atrophy/server_token`

## Authentication

### loadOrCreateToken

```typescript
const TOKEN_PATH = path.join(USER_DATA, 'server_token');

function loadOrCreateToken(): string {
  try {
    if (fs.existsSync(TOKEN_PATH)) {
      const token = fs.readFileSync(TOKEN_PATH, 'utf-8').trim();
      if (token) return token;
    }
  } catch { /* generate new */ }

  const token = crypto.randomBytes(32).toString('base64url');
  fs.writeFileSync(TOKEN_PATH, token + '\n', { mode: 0o600 });
  return token;
}
```

**Purpose:** Load existing token or generate new one

**Security:** File mode 0o600 (owner read/write only)

### checkAuth

```typescript
function checkAuth(req: http.IncomingMessage): boolean {
  const auth = req.headers.authorization || '';
  if (!auth.startsWith('Bearer ')) return false;
  const provided = crypto.createHash('sha256').update(auth.slice(7)).digest();
  const expected = crypto.createHash('sha256').update(serverToken).digest();
  return crypto.timingSafeEqual(provided, expected);
}
```

**Purpose:** Verify bearer token using timing-safe comparison

**Why timing-safe:** Prevents timing attacks on token validation

## HTTP Helpers

### parseBody

```typescript
const MAX_BODY_SIZE = 1024 * 1024; // 1MB

function parseBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let totalSize = 0;
    req.on('data', (chunk: Buffer) => {
      totalSize += chunk.length;
      if (totalSize > MAX_BODY_SIZE) {
        req.destroy();
        reject(new Error('Request body too large'));
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString()));
    req.on('error', reject);
  });
}
```

**Purpose:** Parse request body with size limit

**Limit:** 1MB max

### sendJson

```typescript
function sendJson(res: http.ServerResponse, data: unknown, status = 200): void {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}
```

### parseQuery

```typescript
function parseQuery(url: string): Record<string, string> {
  const idx = url.indexOf('?');
  if (idx < 0) return {};
  const params: Record<string, string> = {};
  const qs = url.slice(idx + 1);
  for (const pair of qs.split('&')) {
    const [k, v] = pair.split('=');
    if (k) {
      try {
        params[decodeURIComponent(k)] = v !== undefined ? decodeURIComponent(v) : '';
      } catch { /* malformed - skip */ }
    }
  }
  return params;
}
```

## Route Handlers

### GET /health

```typescript
async function handleHealth(_req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  const config = getConfig();
  sendJson(res, {
    status: 'ok',
    agent: config.AGENT_NAME,
    display_name: config.AGENT_DISPLAY_NAME,
  });
}
```

**Auth:** Not required

**Response:**
```json
{
  "status": "ok",
  "agent": "xan",
  "display_name": "Xan"
}
```

### POST /chat

```typescript
async function handleChat(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }

  const body = await parseBody(req);
  let data: { message?: string };
  try {
    data = JSON.parse(body);
  } catch {
    sendJson(res, { error: 'invalid json' }, 400);
    return;
  }

  const message = (data.message || '').trim();
  if (!message) {
    sendJson(res, { error: 'empty message' }, 400);
    return;
  }

  if (inferLock) {
    sendJson(res, { error: 'inference in progress' }, 429);
    return;
  }

  inferLock = true;

  try {
    if (!session) {
      session = new Session();
      session.start();
      session.inheritCliSessionId();
    }
    if (!systemPrompt) {
      systemPrompt = loadSystemPrompt();
    }

    session.addTurn('will', message);

    let fullText = '';
    let sessionId = session.cliSessionId || '';
    let errored = false;

    await new Promise<void>((resolve) => {
      const emitter = streamInference(message, systemPrompt, session!.cliSessionId);

      // Timeout: 10 minutes
      let settled = false;
      const timeout = setTimeout(() => {
        if (!settled) {
          settled = true;
          errored = true;
          log.error('HTTP /chat inference timed out');
          if (!res.headersSent) sendJson(res, { error: 'inference timed out' }, 504);
          stopInference();
        }
        resolve();
      }, 10 * 60 * 1000);

      emitter.on('event', (evt: InferenceEvent) => {
        if (settled) return;
        switch (evt.type) {
          case 'StreamDone':
            settled = true;
            clearTimeout(timeout);
            fullText = evt.fullText;
            if (evt.sessionId) sessionId = evt.sessionId;
            resolve();
            break;
          case 'StreamError':
            settled = true;
            clearTimeout(timeout);
            errored = true;
            if (!res.headersSent) sendJson(res, { error: evt.message }, 500);
            resolve();
            break;
        }
      });
    });

    if (!errored) {
      session.addTurn('agent', fullText);
      session.setCliSessionId(sessionId);
      sendJson(res, { response: fullText, session_id: sessionId });
    }
  } finally {
    inferLock = false;
  }
}
```

**Auth:** Required

**Request:**
```json
{ "message": "Hello" }
```

**Response:**
```json
{
  "response": "Hello! How can I help?",
  "session_id": "atrophy-xan-12345"
}
```

**Error codes:**
- 401: Unauthorized (missing/invalid token)
- 400: Invalid JSON or empty message
- 429: Inference in progress
- 500: Inference error
- 504: Inference timeout (10 minutes)

### GET /memory/search

```typescript
async function handleMemorySearch(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }

  const query = parseQuery(req.url || '').q;
  if (!query) {
    sendJson(res, { error: 'missing q parameter' }, 400);
    return;
  }

  const results = await vectorSearch(query, 10);
  sendJson(res, { results });
}
```

**Auth:** Required

**Query:** `?q=search+term`

**Response:**
```json
{
  "results": [ /* search results */ ]
}
```

### GET /status

```typescript
async function handleStatus(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }

  const config = getConfig();
  sendJson(res, {
    agent: config.AGENT_NAME,
    display_name: config.AGENT_DISPLAY_NAME,
    session_active: !!session,
    session_id: session?.cliSessionId || null,
  });
}
```

**Auth:** Required

**Response:**
```json
{
  "agent": "xan",
  "display_name": "Xan",
  "session_active": true,
  "session_id": "atrophy-xan-12345"
}
```

## Server Startup

```typescript
let httpServer: http.Server | null = null;

export function startServer(port = 5000, host = 'localhost'): void {
  if (httpServer) {
    log.warn('server already running');
    return;
  }

  serverToken = loadOrCreateToken();
  log.info(`server token: ${serverToken.slice(0, 8)}...`);

  httpServer = http.createServer(async (req, res) => {
    const url = req.url || '/';
    const method = req.method || 'GET';

    try {
      if (method === 'GET' && url === '/health') {
        await handleHealth(req, res);
      } else if (method === 'POST' && url === '/chat') {
        await handleChat(req, res);
      } else if (method === 'GET' && url.startsWith('/memory/search')) {
        await handleMemorySearch(req, res);
      } else if (method === 'GET' && url === '/status') {
        await handleStatus(req, res);
      } else {
        sendJson(res, { error: 'not found' }, 404);
      }
    } catch (err) {
      log.error(`server error: ${err}`);
      if (!res.headersSent) {
        sendJson(res, { error: 'internal error' }, 500);
      }
    }
  });

  httpServer.listen(port, host, () => {
    log.info(`server listening on http://${host}:${port}`);
  });
}
```

**Default binding:** `localhost:5000`

**Token logging:** Only first 8 chars logged for security

### stopServer

```typescript
export async function stopServer(): Promise<void> {
  if (!httpServer) return;

  return new Promise((resolve) => {
    httpServer!.close(() => {
      httpServer = null;
      session = null;
      systemPrompt = '';
      inferLock = false;
      log.info('server stopped');
      resolve();
    });
  });
}
```

**Purpose:** Stop server and reset state

## Module State

```typescript
let session: Session | null = null;
let systemPrompt = '';
let inferLock = false;
```

**Purpose:** Maintain session state across HTTP requests

**inferLock:** Prevents concurrent inference (429 response if busy)

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read/Write | `~/.atrophy/server_token` | Token storage |

## Exported API

| Function | Purpose |
|----------|---------|
| `startServer(port, host)` | Start HTTP server |
| `stopServer()` | Stop HTTP server |

## See Also

- `src/main/ipc/system.ts` - server:start, server:stop IPC handlers
- `src/main/session.ts` - Session management
- `src/main/inference.ts` - streamInference for /chat
- `src/main/vector-search.ts` - Vector search for /memory/search
