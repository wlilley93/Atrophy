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
import { streamInference, stopInference, resetMcpConfig, InferenceEvent } from './inference';
import { search as vectorSearch } from './vector-search';
import { switchboard } from './channels/switchboard';
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

// Rate limiting for auth failures - sliding window of timestamps
const AUTH_FAIL_WINDOW_MS = 60_000; // 1 minute
const AUTH_FAIL_MAX = 10; // max failures per window
const _authFailures: number[] = [];

function checkAuth(req: http.IncomingMessage): boolean {
  // Check rate limit before attempting auth
  const now = Date.now();
  while (_authFailures.length > 0 && _authFailures[0] < now - AUTH_FAIL_WINDOW_MS) {
    _authFailures.shift();
  }
  if (_authFailures.length >= AUTH_FAIL_MAX) return false;

  const auth = req.headers.authorization || '';
  if (!auth.startsWith('Bearer ')) { _authFailures.push(now); return false; }
  const provided = crypto.createHash('sha256').update(auth.slice(7)).digest();
  const expected = crypto.createHash('sha256').update(serverToken).digest();
  const ok = crypto.timingSafeEqual(provided, expected);
  if (!ok) _authFailures.push(now);
  return ok;
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
        params[decodeURIComponent(k)] = v !== undefined ? decodeURIComponent(v) : '';
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

  try {
    inferLock = true;

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

  try {
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
  } catch (err) {
    inferLock = false;
    if (!res.headersSent) {
      sendJson(res, { error: String(err) }, 500);
    } else {
      res.write(`data: ${JSON.stringify({ type: 'error', message: String(err) })}\n\n`);
      res.end();
    }
    return;
  }

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

  try {
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
  } catch (err) {
    inferLock = false;
    if (!res.headersSent) {
      sendJson(res, { error: String(err) }, 500);
    } else {
      res.write(JSON.stringify({ type: 'error', message: String(err) }) + '\n');
      res.end();
    }
    return;
  }

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
// Meridian bridge auth (X-Channel-Key or Bearer token)
// ---------------------------------------------------------------------------

function checkMeridianAuth(req: http.IncomingMessage): boolean {
  // Accept the channel API key used by the Meridian platform
  const channelKey = req.headers['x-channel-key'];
  if (channelKey && typeof channelKey === 'string') {
    const expected = process.env.CHANNEL_API_KEY || '';
    if (expected && crypto.timingSafeEqual(
      crypto.createHash('sha256').update(channelKey).digest(),
      crypto.createHash('sha256').update(expected).digest(),
    )) {
      return true;
    }
  }
  // Fall back to standard bearer token auth
  return checkAuth(req);
}

// ---------------------------------------------------------------------------
// Meridian chat endpoint - routes through switchboard
// ---------------------------------------------------------------------------

/** Per-agent session for Meridian web chats. Separate from desktop/Telegram. */
const _meridianSessions: Map<string, Session> = new Map();

function getMeridianSession(agentName: string): Session {
  let session = _meridianSessions.get(agentName);
  if (!session) {
    session = new Session();
    session.start();
    _meridianSessions.set(agentName, session);
  }
  return session;
}

async function handleMeridianChat(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  if (!checkMeridianAuth(req)) {
    sendJson(res, { error: 'unauthorized' }, 401);
    return;
  }

  const body = await parseBody(req);
  let data: {
    entity_context?: string;
    channel?: string;
    question?: string;
    history?: { role: string; content: string }[];
  };
  try {
    data = JSON.parse(body);
  } catch {
    sendJson(res, { error: 'invalid json' }, 400);
    return;
  }

  const entityContext = (data.entity_context || '').trim();
  const question = (data.question || '').trim();
  const agentName = data.channel || 'general_montgomery';
  const history = Array.isArray(data.history) ? data.history : [];

  if (!entityContext) {
    sendJson(res, { error: 'entity_context is required' }, 400);
    return;
  }
  if (!question) {
    sendJson(res, { error: 'question is required' }, 400);
    return;
  }

  // SSE headers
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });

  // Build the contextual prompt that includes entity data and conversation history
  let prompt = '';
  if (history.length > 0) {
    const transcript = history
      .map(h => `${h.role === 'assistant' ? 'You' : 'User'}: ${h.content}`)
      .slice(-12)
      .join('\n\n');
    prompt += `Conversation so far:\n${transcript}\n\n`;
  }
  prompt += `[Meridian Eye - entity context]\n\n${entityContext}\n\nUser question: ${question}`;

  // Record the inbound envelope on the switchboard for audit trail
  const envelope = switchboard.createEnvelope(
    'meridian:web',
    `agent:${agentName}`,
    question,
    {
      type: 'user',
      metadata: {
        source: 'meridian_web',
        entityContext: entityContext.slice(0, 500),
        historyLength: history.length,
      },
    },
  );
  switchboard.record(envelope);

  // Switch config to the target agent, run inference, then restore.
  // This mirrors how the Telegram daemon dispatches per-agent.
  const config = getConfig();
  const originalAgent = config.AGENT_NAME;
  let emitter: ReturnType<typeof streamInference>;
  let streamEnded = false;

  const finalize = () => {
    if (streamEnded) return;
    streamEnded = true;
    // Restore original agent config
    if (originalAgent && originalAgent !== agentName) {
      try { config.reloadForAgent(originalAgent); } catch { /* best effort */ }
    }
  };

  try {
    // Reload config for the target agent so system prompt + MCP are correct
    config.reloadForAgent(agentName);
    resetMcpConfig();
    memory.initDb();

    const system = loadSystemPrompt();
    const agentSession = getMeridianSession(agentName);
    agentSession.inheritCliSessionId();

    try { agentSession.addTurn('will', question); } catch { /* session not started */ }

    emitter = streamInference(prompt, system, agentSession.cliSessionId, {
      senderName: 'Meridian Web User',
      source: 'server',
    });
  } catch (err) {
    finalize();
    res.write(`data: ${JSON.stringify({ type: 'error', error: String(err) })}\n\n`);
    res.write('data: [DONE]\n\n');
    res.end();
    return;
  }

  // Handle client disconnect
  res.on('close', () => {
    if (!streamEnded) {
      finalize();
      emitter.removeAllListeners();
      stopInference(agentName);
    }
  });

  let fullText = '';
  let lastSessionId: string | null = null;

  emitter.on('event', (evt: InferenceEvent) => {
    if (streamEnded) return;

    switch (evt.type) {
      case 'TextDelta':
        res.write(`data: ${JSON.stringify({ type: 'text_delta', text: evt.text })}\n\n`);
        break;

      case 'ToolUse':
        res.write(`data: ${JSON.stringify({ type: 'tool_use', name: evt.name })}\n\n`);
        break;

      case 'StreamDone':
        fullText = evt.fullText;
        lastSessionId = evt.sessionId || null;

        // Update session
        const agentSession = getMeridianSession(agentName);
        if (lastSessionId && lastSessionId !== agentSession.cliSessionId) {
          agentSession.setCliSessionId(lastSessionId);
        }
        if (fullText) {
          try { agentSession.addTurn('agent', fullText); } catch { /* ignore */ }
        }

        // Record response on switchboard
        const responseEnvelope = switchboard.createEnvelope(
          `agent:${agentName}`,
          'meridian:web',
          fullText.slice(0, 500),
          { type: 'agent', metadata: { source: 'meridian_web' } },
        );
        switchboard.record(responseEnvelope);

        finalize();
        res.write(`data: ${JSON.stringify({ type: 'done' })}\n\n`);
        res.write('data: [DONE]\n\n');
        res.end();
        break;

      case 'StreamError':
        finalize();
        res.write(`data: ${JSON.stringify({ type: 'error', error: evt.message })}\n\n`);
        res.write('data: [DONE]\n\n');
        res.end();
        break;
    }
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

    // CORS - allow localhost, Meridian/WorldMonitor origins, and bridge tunnel
    const origin = req.headers.origin || '';
    const CORS_PATTERN = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$|^https:\/\/(.*\.)?(worldmonitor\.app|worldmonitor\.atrophy\.app|bridge\.atrophy\.app)$/;
    if (origin && CORS_PATTERN.test(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Channel-Key');
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
      } else if (pathname === '/meridian/chat' && method === 'POST') {
        await handleMeridianChat(req, res);
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
    log.info(`Endpoints: /health, /chat, /chat/stream, /chat/stream-json, /meridian/chat, /status, /agents, /agents/create, /memory/search, /memory/threads, /session`);
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

// ---------------------------------------------------------------------------
// Meridian bridge server - lightweight HTTP server for the /meridian/chat
// endpoint. Runs during GUI/menubar mode alongside the Cloudflare Tunnel.
// Separate from the full startServer() which is used in --server mode.
// ---------------------------------------------------------------------------

let meridianServer: http.Server | null = null;

export function startMeridianServer(port = 3847, host = '127.0.0.1'): void {
  if (meridianServer) return; // already running

  // Load server token for bearer auth fallback
  serverToken = loadOrCreateToken();

  meridianServer = http.createServer(async (req, res) => {
    const url = req.url || '/';
    const pathname = url.split('?')[0];
    const method = req.method || 'GET';

    // CORS - allow Meridian/WorldMonitor origins and bridge tunnel
    const origin = req.headers.origin || '';
    const CORS_PATTERN = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$|^https:\/\/(.*\.)?(worldmonitor\.app|worldmonitor\.atrophy\.app|bridge\.atrophy\.app)$/;
    if (origin && CORS_PATTERN.test(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Channel-Key');
    }
    if (method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }

    try {
      if (pathname === '/health' && method === 'GET') {
        sendJson(res, { status: 'ok', service: 'meridian-bridge' });
      } else if (pathname === '/meridian/chat' && method === 'POST') {
        await handleMeridianChat(req, res);
      } else {
        sendJson(res, { error: 'not found' }, 404);
      }
    } catch (e) {
      log.error(`Meridian server error: ${method} ${pathname}: ${e}`);
      if (!res.headersSent) {
        sendJson(res, { error: 'internal server error' }, 500);
      }
    }
  });

  // Handle listen errors gracefully - EADDRINUSE from a stale process
  // should not crash the app or trigger the crash loop detector.
  meridianServer.on('error', (err: NodeJS.ErrnoException) => {
    if (err.code === 'EADDRINUSE') {
      log.warn(`Meridian bridge port ${port} already in use - skipping (another instance may be running)`);
      meridianServer = null;
    } else {
      log.error(`Meridian bridge server error: ${err.message}`);
      meridianServer = null;
    }
  });

  meridianServer.listen(port, host, () => {
    log.info(`Meridian bridge server: http://${host}:${port}`);
    log.info(`Endpoints: /health, /meridian/chat`);
    log.info(`Auth: X-Channel-Key or Bearer token`);
  });
}

export function stopMeridianServer(): void {
  if (meridianServer) {
    meridianServer.close();
    meridianServer = null;
    log.info('Meridian bridge server stopped');
  }
}
