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
import { streamInference, stopInference, InferenceEvent } from './inference';
import { search as vectorSearch } from './vector-search';
import { createLogger } from './logger';

const log = createLogger('server');

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

function sendJson(res: http.ServerResponse, data: unknown, status = 200): void {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

function checkAuth(req: http.IncomingMessage): boolean {
  const auth = req.headers.authorization || '';
  if (!auth.startsWith('Bearer ')) return false;
  const provided = crypto.createHash('sha256').update(auth.slice(7)).digest();
  const expected = crypto.createHash('sha256').update(serverToken).digest();
  return crypto.timingSafeEqual(provided, expected);
}

function parseQuery(url: string): Record<string, string> {
  const idx = url.indexOf('?');
  if (idx < 0) return {};
  const params: Record<string, string> = {};
  const qs = url.slice(idx + 1);
  for (const pair of qs.split('&')) {
    const [k, v] = pair.split('=');
    if (k) {
      try {
        params[decodeURIComponent(k)] = decodeURIComponent(v || '');
      } catch { /* malformed percent-encoding - skip */ }
    }
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

      // Timeout: if no response after 10 minutes, give up
      const timeout = setTimeout(() => {
        if (!errored) {
          errored = true;
          log.error('HTTP /chat inference timed out');
          sendJson(res, { error: 'inference timed out' }, 504);
          stopInference();
        }
        resolve();
      }, 10 * 60 * 1000);

      emitter.on('event', (evt: InferenceEvent) => {
        switch (evt.type) {
          case 'StreamDone':
            clearTimeout(timeout);
            fullText = evt.fullText;
            if (evt.sessionId) sessionId = evt.sessionId;
            resolve();
            break;
          case 'StreamError':
            clearTimeout(timeout);
            errored = true;
            sendJson(res, { error: evt.message }, 500);
            resolve();
            break;
        }
      });
    });

    if (errored) return;

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
    session.inheritCliSessionId();
  }
  if (!systemPrompt) {
    systemPrompt = loadSystemPrompt();
  }

  session.addTurn('will', message);

  let fullText = '';
  let sessionId = session.cliSessionId || '';

  let emitter: ReturnType<typeof streamInference>;
  try {
    emitter = streamInference(message, systemPrompt, session.cliSessionId);
  } catch (err) {
    inferLock = false;
    res.write(`data: ${JSON.stringify({ type: 'error', message: String(err) })}\n\n`);
    res.end();
    return;
  }
  let streamEnded = false;

  function finalize() {
    if (streamEnded) return;
    streamEnded = true;
    inferLock = false;
  }

  // Clean up on client disconnect - release lock, stop inference, remove listeners
  res.on('close', () => {
    if (!streamEnded) {
      finalize();
      emitter.removeAllListeners();
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

        finalize();
        res.write(`data: ${JSON.stringify({ type: 'done', full_text: fullText })}\n\n`);
        res.end();
        break;
      case 'StreamError':
        finalize();
        res.write(`data: ${JSON.stringify({ type: 'error', message: evt.message })}\n\n`);
        res.end();
        break;
    }
  });
}

async function handleChatStreamJson(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
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

  // NDJSON - one JSON object per line, compatible with Claude CLI stream-json format
  res.writeHead(200, {
    'Content-Type': 'application/x-ndjson',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });

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

  let emitter: ReturnType<typeof streamInference>;
  try {
    emitter = streamInference(message, systemPrompt, session.cliSessionId);
  } catch (err) {
    inferLock = false;
    res.write(JSON.stringify({ type: 'error', error: String(err) }) + '\n');
    res.end();
    return;
  }
  let streamEnded = false;

  function finalize() {
    if (streamEnded) return;
    streamEnded = true;
    inferLock = false;
  }

  res.on('close', () => {
    if (!streamEnded) {
      finalize();
      emitter.removeAllListeners();
      stopInference();
    }
  });

  emitter.on('event', (evt: InferenceEvent) => {
    if (streamEnded) return;

    switch (evt.type) {
      case 'TextDelta':
        res.write(JSON.stringify({
          type: 'assistant',
          subtype: 'text_delta',
          text: evt.text,
        }) + '\n');
        break;
      case 'SentenceReady':
        res.write(JSON.stringify({
          type: 'assistant',
          subtype: 'sentence',
          text: evt.sentence,
          index: evt.index,
        }) + '\n');
        break;
      case 'ToolUse':
        res.write(JSON.stringify({
          type: 'tool_use',
          name: evt.name,
        }) + '\n');
        break;
      case 'Compacting':
        res.write(JSON.stringify({
          type: 'system',
          subtype: 'compacting',
        }) + '\n');
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

        finalize();
        res.write(JSON.stringify({
          type: 'result',
          subtype: 'success',
          text: fullText,
          session_id: sessionId,
        }) + '\n');
        res.end();
        break;
      case 'StreamError':
        finalize();
        res.write(JSON.stringify({
          type: 'result',
          subtype: 'error',
          error: evt.message,
        }) + '\n');
        res.end();
        break;
    }
  });
}

async function handleStatus(_req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(_req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }
  const config = getConfig();
  const { getStatus } = await import('./status');
  const userStatus = getStatus();
  sendJson(res, {
    status: 'ok',
    agent: config.AGENT_NAME,
    display_name: config.AGENT_DISPLAY_NAME,
    user_status: userStatus.status,
    since: userStatus.since,
  });
}

async function handleAgents(_req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(_req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }
  const { discoverAgents } = await import('./agent-manager');
  const agents = discoverAgents();
  sendJson(res, { agents });
}

async function handleAgentsCreate(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }

  const raw = await parseBody(req);
  let body: {
    leaderName?: string;
    displayName?: string;
    description?: string;
    orgContext?: {
      slug: string;
      tier: number;
      role: string;
      reportsTo: string | null;
    };
    personality?: Record<string, number>;
    mcpServers?: string[];
    jobTypes?: string[];
    hasTelegram?: boolean;
    hasVoice?: boolean;
    hasAvatar?: boolean;
    soul?: string;
    openingLine?: string;
  };
  try {
    body = JSON.parse(raw);
  } catch {
    sendJson(res, { error: 'invalid json' }, 400);
    return;
  }

  if (!body.leaderName || !body.displayName || !body.orgContext) {
    sendJson(res, { error: 'leaderName, displayName, and orgContext are required' }, 400);
    return;
  }

  try {
    const { validateProvisioningRequest } = await import('./hierarchy-guard');
    const { createAgent, wireAgent } = await import('./create-agent');
    type CreateAgentOptions = Parameters<typeof createAgent>[0];

    // Load leader's manifest to validate provisioning rights
    const { discoverAgents } = await import('./agent-manager');
    const agents = discoverAgents();
    const leader = agents.find((a: { name: string }) => a.name === body.leaderName);
    if (!leader) {
      sendJson(res, { error: `Leader agent "${body.leaderName}" not found` }, 404);
      return;
    }

    // Read leader's manifest
    const manifestPath = path.join(
      process.env.HOME || '/tmp', '.atrophy', 'agents', body.leaderName!, 'data', 'agent.json',
    );
    let leaderManifest: Record<string, unknown> = {};
    try {
      leaderManifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    } catch {
      sendJson(res, { error: `Could not read leader manifest at ${manifestPath}` }, 500);
      return;
    }

    // Validate hierarchy
    const violations = validateProvisioningRequest(body.leaderName, leaderManifest, {
      targetName: body.displayName,
      targetTier: body.orgContext!.tier,
      targetOrg: body.orgContext!.slug,
      mcpServers: body.mcpServers || [],
      jobTypes: body.jobTypes || [],
      hasTelegram: body.hasTelegram || false,
      hasVoice: body.hasVoice || false,
      hasAvatar: body.hasAvatar || false,
      personality: body.personality,
    });

    if (violations.length > 0) {
      sendJson(res, {
        error: 'Provisioning request denied',
        violations: violations.map((v: { field: string; reason: string }) => `${v.field}: ${v.reason}`),
      }, 403);
      return;
    }

    // Build create options
    const opts: CreateAgentOptions = {
      displayName: body.displayName,
      description: body.description,
      openingLine: body.openingLine || `${body.displayName} reporting for duty.`,
      orgContext: {
        slug: body.orgContext!.slug,
        tier: body.orgContext!.tier,
        role: body.orgContext!.role,
        reportsTo: body.orgContext!.reportsTo,
        allowedMcpServers: body.mcpServers,
        allowedJobTypes: body.jobTypes,
      },
      mcp: body.mcpServers ? { include: body.mcpServers } : undefined,
    };

    // Create and wire
    const manifest = createAgent(opts);
    wireAgent(manifest.name, manifest);

    sendJson(res, { ok: true, name: manifest.name, manifest });
  } catch (e) {
    sendJson(res, { error: String(e) }, 500);
  }
}

async function handleMemorySearch(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkAuth(req)) { sendJson(res, { error: 'unauthorized' }, 401); return; }

  const query = parseQuery(req.url || '');
  const q = (query.q || '').trim();
  const limit = Math.min(Math.max(1, parseInt(query.limit || '10', 10) || 10), 100);

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
  session.inheritCliSessionId();
  systemPrompt = loadSystemPrompt();

  httpServer = http.createServer(async (req, res) => {
    const url = req.url || '/';
    const pathname = url.split('?')[0];
    const method = req.method || 'GET';

    // CORS - restrict to localhost only
    const origin = req.headers.origin || '';
    if (origin && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    }
    if (method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }

    try {
      if (pathname === '/health' && method === 'GET') {
        await handleHealth(req, res);
      } else if (pathname === '/chat' && method === 'POST') {
        await handleChat(req, res);
      } else if (pathname === '/chat/stream' && method === 'POST') {
        await handleChatStream(req, res);
      } else if (pathname === '/chat/stream-json' && method === 'POST') {
        await handleChatStreamJson(req, res);
      } else if (pathname === '/status' && method === 'GET') {
        await handleStatus(req, res);
      } else if (pathname === '/agents' && method === 'GET') {
        await handleAgents(req, res);
      } else if (pathname === '/agents/create' && method === 'POST') {
        await handleAgentsCreate(req, res);
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
      log.error(`Error handling ${method} ${pathname}: ${e}`);
      if (!res.headersSent) {
        sendJson(res, { error: 'internal server error' }, 500);
      }
    }
  });

  httpServer.listen(port, host, () => {
    const config = getConfig();
    log.info(`Atrophy - HTTP API`);
    log.info(`Agent: ${config.AGENT_DISPLAY_NAME}`);
    log.info(`http://${host}:${port}`);
    log.info(`Token: ${serverToken.slice(0, 8)}...${serverToken.slice(-4)}`);
    log.info(`Token file: ${TOKEN_PATH}`);
    log.info(`Endpoints: /health, /chat, /chat/stream, /chat/stream-json, /status, /agents, /agents/create, /memory/search, /memory/threads, /session`);
    log.info(`Auth: Bearer token required on all endpoints except /health`);
  });
}

export async function stopServer(): Promise<void> {
  stopInference();
  if (httpServer) {
    httpServer.close();
    httpServer = null;
  }
  if (session) {
    await session.end(systemPrompt);
    session = null;
  }
}
