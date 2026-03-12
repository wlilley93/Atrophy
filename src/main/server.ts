/**
 * Minimal HTTP API for Atrophy.
 * Port of server.py - Express.js instead of Flask.
 *
 * Exposes chat, memory, and status endpoints.
 * Runs headless - no GUI, no TTS, no voice input.
 *
 * Security:
 *   - Binds to localhost only by default
 *   - Bearer token auth required on all endpoints except /health
 *   - Token auto-generated on first run, stored in ~/.atrophy/server_token
 */

import * as http from 'http';
import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
import { getConfig, USER_DATA } from './config';
import * as memory from './memory';
import { Session } from './session';
import { loadSystemPrompt } from './context';
import { streamInference, InferenceEvent } from './inference';
import { search as vectorSearch } from './vector-search';

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

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

let serverToken = '';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let session: Session | null = null;
let systemPrompt = '';
let inferLock = false;

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

function parseBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks).toString()));
    req.on('error', reject);
  });
}

function sendJson(res: http.ServerResponse, data: unknown, status = 200): void {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

function checkAuth(req: http.IncomingMessage): boolean {
  const auth = req.headers.authorization || '';
  return auth.startsWith('Bearer ') && auth.slice(7) === serverToken;
}

function parseQuery(url: string): Record<string, string> {
  const idx = url.indexOf('?');
  if (idx < 0) return {};
  const params: Record<string, string> = {};
  const qs = url.slice(idx + 1);
  for (const pair of qs.split('&')) {
    const [k, v] = pair.split('=');
    if (k) params[decodeURIComponent(k)] = decodeURIComponent(v || '');
  }
  return params;
}

// ---------------------------------------------------------------------------
// Route handlers
// ---------------------------------------------------------------------------

async function handleHealth(_req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  const config = getConfig();
  sendJson(res, {
    status: 'ok',
    agent: config.AGENT_NAME,
    display_name: config.AGENT_DISPLAY_NAME,
  });
}

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
    }
    if (!systemPrompt) {
      systemPrompt = loadSystemPrompt();
    }

    session.addTurn('will', message);

    let fullText = '';
    let sessionId = session.cliSessionId || '';

    await new Promise<void>((resolve) => {
      const emitter = streamInference(message, systemPrompt, session!.cliSessionId);

      emitter.on('event', (evt: InferenceEvent) => {
        switch (evt.type) {
          case 'StreamDone':
            fullText = evt.fullText;
            if (evt.sessionId) sessionId = evt.sessionId;
            resolve();
            break;
          case 'StreamError':
            sendJson(res, { error: evt.message }, 500);
            resolve();
            break;
        }
      });
    });

    if (sessionId && sessionId !== session.cliSessionId) {
      session.setCliSessionId(sessionId);
    }
    if (fullText) {
      session.addTurn('agent', fullText);
    }

    sendJson(res, { response: fullText, session_id: session.sessionId });
  } finally {
    inferLock = false;
  }
}

async function handleChatStream(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
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

  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });

  if (!session) {
    session = new Session();
    session.start();
  }
  if (!systemPrompt) {
    systemPrompt = loadSystemPrompt();
  }

  session.addTurn('will', message);

  let fullText = '';
  let sessionId = session.cliSessionId || '';

  const emitter = streamInference(message, systemPrompt, session.cliSessionId);
  let streamEnded = false;

  // Clean up on client disconnect - release lock and stop inference
  res.on('close', () => {
    if (!streamEnded) {
      streamEnded = true;
      inferLock = false;
      stopInference();
    }
  });

  emitter.on('event', (evt: InferenceEvent) => {
    if (streamEnded) return;

    switch (evt.type) {
      case 'TextDelta':
        res.write(`data: ${JSON.stringify({ type: 'text', content: evt.text })}\n\n`);
        break;
      case 'ToolUse':
        res.write(`data: ${JSON.stringify({ type: 'tool', name: evt.name })}\n\n`);
        break;
      case 'StreamDone':
        fullText = evt.fullText;
        if (evt.sessionId) sessionId = evt.sessionId;

        if (sessionId && sessionId !== session!.cliSessionId) {
          session!.setCliSessionId(sessionId);
        }
        if (fullText) {
          session!.addTurn('agent', fullText);
        }

        streamEnded = true;
        res.write(`data: ${JSON.stringify({ type: 'done', full_text: fullText })}\n\n`);
        inferLock = false;
        res.end();
        break;
      case 'StreamError':
        streamEnded = true;
        res.write(`data: ${JSON.stringify({ type: 'error', message: evt.message })}\n\n`);
        inferLock = false;
        res.end();
        break;
    }
  });
}

async function handleMemorySearch(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }

  const query = parseQuery(req.url || '');
  const q = (query.q || '').trim();
  const limit = parseInt(query.limit || '10', 10);

  if (!q) {
    sendJson(res, { error: 'missing q parameter' }, 400);
    return;
  }

  const results = await vectorSearch(q, limit);
  sendJson(res, { results });
}

async function handleMemoryThreads(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }

  const threads = memory.getActiveThreads();
  sendJson(res, { threads });
}

async function handleSession(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }

  const config = getConfig();
  sendJson(res, {
    session_id: session?.sessionId || null,
    cli_session_id: session?.cliSessionId || null,
    agent: config.AGENT_NAME,
    display_name: config.AGENT_DISPLAY_NAME,
  });
}

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------

let httpServer: http.Server | null = null;

export function startServer(port = 5000, host = '127.0.0.1'): void {
  serverToken = loadOrCreateToken();

  memory.initDb();
  session = new Session();
  session.start();
  systemPrompt = loadSystemPrompt();

  httpServer = http.createServer(async (req, res) => {
    const url = req.url || '/';
    const pathname = url.split('?')[0];
    const method = req.method || 'GET';

    try {
      if (pathname === '/health' && method === 'GET') {
        await handleHealth(req, res);
      } else if (pathname === '/chat' && method === 'POST') {
        await handleChat(req, res);
      } else if (pathname === '/chat/stream' && method === 'POST') {
        await handleChatStream(req, res);
      } else if (pathname === '/memory/search' && method === 'GET') {
        await handleMemorySearch(req, res);
      } else if (pathname === '/memory/threads' && method === 'GET') {
        await handleMemoryThreads(req, res);
      } else if (pathname === '/session' && method === 'GET') {
        await handleSession(req, res);
      } else {
        sendJson(res, { error: 'not found' }, 404);
      }
    } catch (e) {
      console.log(`[server] Error handling ${method} ${pathname}: ${e}`);
      if (!res.headersSent) {
        sendJson(res, { error: 'internal server error' }, 500);
      }
    }
  });

  httpServer.listen(port, host, () => {
    const config = getConfig();
    console.log(`\n  Atrophy - HTTP API`);
    console.log(`  Agent: ${config.AGENT_DISPLAY_NAME}`);
    console.log(`  http://${host}:${port}`);
    console.log(`  Token: ${serverToken.slice(0, 8)}...${serverToken.slice(-4)}`);
    console.log(`  Token file: ${TOKEN_PATH}`);
    console.log(`  Endpoints: /health, /chat, /chat/stream, /memory/search, /memory/threads, /session`);
    console.log(`  Auth: Bearer token required on all endpoints except /health\n`);
  });
}

export function stopServer(): void {
  if (httpServer) {
    httpServer.close();
    httpServer = null;
  }
  if (session) {
    session.end(systemPrompt);
  }
}
