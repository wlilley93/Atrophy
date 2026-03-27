# src/main/voice-agent.ts - Hybrid Voice Agent System

**Dependencies:** `events`, `electron`, `fs`, `path`, `./inference`, `./context`, `./prompts`, `./memory`, `./config`, `./channels/telegram`, `./logger`  
**Purpose:** Hybrid ElevenLabs + Claude Code voice agent with cost-optimized routing

## Overview

This module implements a cost-optimized voice agent system using ElevenLabs Conversational AI with a custom routing LLM. Instead of running all inference through expensive models, it uses a cheap/fast model (gemini-2.5-flash-lite) for intent classification and routes heavy work to local Claude Code (free via CLI subscription).

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Voice Agent Flow                              │
│                                                                   │
│  1. User speaks ──▶ ElevenLabs STT                               │
│                                                                   │
│  2. gemini-2.5-flash-lite (routing brain)                        │
│     ├─ Simple response ──▶ Direct reply                          │
│     └─ Complex task ──▶ client_tool_call                         │
│                                                                   │
│  3. Local handlers                                               │
│     ├─ claude_code ──▶ Complex tasks, coding, analysis           │
│     ├─ recall_memory ──▶ SQLite memory search                    │
│     ├─ generate_artefact ──▶ Visual content                      │
│     └─ send_telegram ──▶ Telegram messages                       │
│                                                                   │
│  4. Result ──▶ Agent narrates via ElevenLabs TTS                 │
└─────────────────────────────────────────────────────────────────┘
```

**Cost optimization:**
- gemini-2.5-flash-lite on ElevenLabs: cheapest/fastest for routing
- Local Claude Code: free (Max subscription)
- Memory search: free (local SQLite)

## Constants

```typescript
const ELEVENLABS_API_BASE = 'https://api.elevenlabs.io/v1';
const ELEVENLABS_CONVAI_WS = 'wss://api.elevenlabs.io/v1/convai/conversation';

const ROUTING_LLM = 'gemini-2.5-flash-lite';  // Cheapest/fastest for routing
const PING_INTERVAL_MS = 15_000;              // WebSocket keepalive
const CLAUDE_CODE_TIMEOUT_MS = 120_000;       // 2 minutes for Claude Code
const MEMORY_TIMEOUT_MS = 10_000;             // 10 seconds for memory search
```

## Idle Disconnect (Cost Control)

```typescript
const IDLE_DISCONNECT_MS = 2_000;  // 2s after last audio finishes
let _idleDisconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _pendingToolCalls = 0;  // Don't disconnect while tools running
let _agentId: string | null = null;  // Cached for fast reconnect
let _wsUrl: string | null = null;    // Cached signed URL

function _startIdleTimer(): void {
  _resetIdleTimer();
  if (_pendingToolCalls > 0) return;  // Don't disconnect during tools

  _idleDisconnectTimer = setTimeout(() => {
    if (_pendingToolCalls > 0) return;
    log.info('idle timeout - disconnecting to save cost');
    _disconnectWebSocket();
  }, IDLE_DISCONNECT_MS);
}
```

**Purpose:** ElevenLabs bills per second of connection. Disconnect when idle to minimize cost.

**Reconnect time:** ~200ms (imperceptible during natural speech onset)

## Client Tool Definitions

```typescript
const CLIENT_TOOLS: ClientToolDefinition[] = [
  {
    type: 'client',
    name: 'claude_code',
    description: 'Run Claude Code for complex tasks - coding, file operations, system commands, deep analysis, research.',
    parameters: {
      type: 'object',
      properties: {
        prompt: { type: 'string', description: 'Full task description' },
        speak_while_working: { type: 'string', description: 'Message to say while working' },
      },
      required: ['prompt'],
    },
    expects_response: true,
    response_timeout_secs: 120,
  },
  {
    type: 'client',
    name: 'generate_artefact',
    description: 'Generate visual artefact - HTML visualization, interactive chart, diagram.',
    parameters: { /* ... */ },
    expects_response: true,
    response_timeout_secs: 120,
  },
  {
    type: 'client',
    name: 'recall_memory',
    description: 'Search agent memory database for past conversations, facts, observations.',
    parameters: {
      query: { type: 'string', description: 'Search query' },
    },
    expects_response: true,
    response_timeout_secs: 10,
  },
  {
    type: 'client',
    name: 'send_telegram',
    description: 'Send message to user via Telegram.',
    parameters: {
      message: { type: 'string', description: 'Message to send' },
    },
    expects_response: true,
    response_timeout_secs: 10,
  },
];
```

**Tool categories:**
1. **claude_code:** Complex tasks requiring reasoning or filesystem access
2. **generate_artefact:** Visual content generation
3. **recall_memory:** Memory database search
4. **send_telegram:** Telegram messaging

## Agent Provisioning

### buildAgentPayload

```typescript
function buildAgentPayload(agentName: string): AgentPayload {
  const config = getConfig();

  return {
    name: `atrophy-${agentName}`,
    conversation_config: {
      agent: {
        prompt: {
          prompt: buildRoutingPrompt(agentName),
          llm: ROUTING_LLM,
          temperature: 0.7,
          max_tokens: 512,  // Keep responses short for voice
          tools: CLIENT_TOOLS,
          ignore_default_personality: true,
        },
        first_message: config.OPENING_LINE || '',
        language: 'en',
      },
      tts: {
        voice_id: config.ELEVENLABS_VOICE_ID,
        stability: config.ELEVENLABS_STABILITY,
        similarity_boost: config.ELEVENLABS_SIMILARITY,
        style: config.ELEVENLABS_STYLE,
      },
    },
  };
}
```

### buildRoutingPrompt

```typescript
function buildRoutingPrompt(agentName: string): string {
  const config = getConfig();

  // Load soul/personality from Obsidian or bundle
  let soulContent = '';
  if (config.OBSIDIAN_AVAILABLE) {
    const obsidianSoul = path.join(config.OBSIDIAN_AGENT_DIR, 'skills', 'soul.md');
    try {
      if (fs.existsSync(obsidianSoul)) {
        soulContent = fs.readFileSync(obsidianSoul, 'utf-8').trim();
      }
    } catch { /* fall through */ }
  }
  if (!soulContent) {
    soulContent = loadPrompt('soul', '');
  }

  // Truncate to first 500 chars for cost efficiency
  const personalitySnippet = soulContent
    ? soulContent.slice(0, 500)
    : `a thoughtful, warm companion for ${config.USER_NAME}`;

  return [
    `You are ${config.AGENT_DISPLAY_NAME}. You have a warm, natural conversational style.`,
    '',
    `Your personality: ${personalitySnippet}`,
    '',
    'You can chat naturally about anything. For complex tasks, you have tools available.',
    'Use tools when the user asks you to:',
    '- Write, read, or modify code or files',
    '- Generate visualisations, artefacts, or interactive content',
    '- Run system commands or git operations',
    '- Search the web for current information',
    '- Do anything that requires thinking deeply or accessing the filesystem',
    '',
    'When using a tool, tell the user naturally what you\'re doing.',
    '',
    'For memory recall, ALWAYS use the recall_memory tool before answering questions.',
    '',
    'Keep responses concise and natural for voice. Don\'t use markdown formatting.',
  ].join('\n');
}
```

**Purpose:** Build concise routing prompt for gemini-2.5-flash-lite

**Cost optimization:** Truncate personality to 500 chars

## Agent ID Caching

```typescript
function agentIdCachePath(agentName: string): string {
  return path.join(USER_DATA, 'agents', agentName, 'data', '.voice_agent_id');
}

function getCachedAgentId(agentName: string): string | null {
  const cachePath = agentIdCachePath(agentName);
  try {
    if (fs.existsSync(cachePath)) {
      return fs.readFileSync(cachePath, 'utf-8').trim() || null;
    }
  } catch { /* no cache */ }
  return null;
}

function cacheAgentId(agentName: string, agentId: string): void {
  const cachePath = agentIdCachePath(agentName);
  try {
    fs.mkdirSync(path.dirname(cachePath), { recursive: true });
    fs.writeFileSync(cachePath, agentId, { mode: 0o600 });
  } catch (err) {
    log.warn(`failed to cache agent ID: ${err}`);
  }
}
```

**Purpose:** Cache ElevenLabs agent ID for fast reconnect

**Security:** File mode 0o600 (owner read/write only)

## Agent Creation/Update

### createAgent

```typescript
async function createAgent(agentName: string): Promise<string | null> {
  const config = getConfig();
  const payload = buildAgentPayload(agentName);

  log.info(`creating ElevenLabs agent: atrophy-${agentName}`);

  const resp = await fetch(`${ELEVENLABS_API_BASE}/convai/agents/create`, {
    method: 'POST',
    headers: {
      'xi-api-key': config.ELEVENLABS_API_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30_000),
  });

  if (!resp.ok) {
    const body = await resp.text();
    log.error(`agent creation failed (${resp.status}): ${body.slice(0, 300)}`);
    return null;
  }

  const data = await resp.json() as { agent_id?: string };
  if (data.agent_id) {
    log.info(`agent created: ${data.agent_id}`);
    return data.agent_id;
  }

  log.error('agent creation response missing agent_id');
  return null;
}
```

### updateAgent

```typescript
async function updateAgent(agentId: string, agentName: string): Promise<boolean> {
  const config = getConfig();
  const payload = buildAgentPayload(agentName);

  const resp = await fetch(`${ELEVENLABS_API_BASE}/convai/agents/${agentId}`, {
    method: 'PATCH',
    headers: {
      'xi-api-key': config.ELEVENLABS_API_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30_000),
  });

  return resp.ok;
}
```

### provisionAgent

```typescript
export async function provisionAgent(agentName: string): Promise<string | null> {
  const config = getConfig();

  if (!config.ELEVENLABS_API_KEY) {
    log.error('cannot provision agent - no ELEVENLABS_API_KEY');
    return null;
  }

  // Check for cached agent ID
  const cachedId = getCachedAgentId(agentName);

  if (cachedId) {
    // Validate it still exists
    const valid = await validateAgentId(cachedId);
    if (valid) {
      // Update existing agent with current config
      const updated = await updateAgent(cachedId, agentName);
      if (updated) return cachedId;
      log.warn('agent update failed, using existing agent');
      return cachedId;
    }
    log.info('cached agent ID is stale, creating new agent');
  }

  // Create new agent
  const newId = await createAgent(agentName);
  if (newId) {
    cacheAgentId(agentName, newId);
  }
  return newId;
}
```

**Flow:**
1. Check for cached agent ID
2. If cached, validate it still exists on ElevenLabs
3. If valid, update with current config
4. If invalid/missing, create new agent and cache

## WebSocket URL Resolution

```typescript
let _cachedSignedUrl: string | null = null;
let _cachedSignedUrlTime = 0;
const SIGNED_URL_TTL_MS = 50_000;  // URLs expire after 60s, cache for 50s

async function getWebSocketUrl(agentId: string): Promise<string | null> {
  const config = getConfig();

  // Return cached signed URL if still valid
  if (_cachedSignedUrl && (Date.now() - _cachedSignedUrlTime) < SIGNED_URL_TTL_MS) {
    log.debug('using cached signed URL');
    return _cachedSignedUrl;
  }

  // Try signed URL first (preferred - more secure)
  try {
    const resp = await fetch(
      `${ELEVENLABS_API_BASE}/convai/conversation/get-signed-url?agent_id=${encodeURIComponent(agentId)}`,
      {
        method: 'GET',
        headers: { 'xi-api-key': config.ELEVENLABS_API_KEY },
        signal: AbortSignal.timeout(10_000),
      },
    );

    if (resp.ok) {
      const data = await resp.json() as { signed_url?: string };
      if (data.signed_url) {
        log.debug('using signed URL');
        _cachedSignedUrl = data.signed_url;
        _cachedSignedUrlTime = Date.now();
        return data.signed_url;
      }
    }
    log.debug(`signed URL request failed (${resp.status}), falling back to direct`);
  } catch (err) {
    log.debug(`signed URL fetch error: ${err}`);
  }

  // Fallback: direct connection with agent_id in URL
  return `${ELEVENLABS_CONVAI_WS}?agent_id=${encodeURIComponent(agentId)}`;
}
```

**Why signed URLs:** Avoids exposing API key in WebSocket URL

**Cache TTL:** 50 seconds (URLs expire after 60s)

## startVoiceAgent

```typescript
export async function startVoiceAgent(agentName?: string): Promise<boolean> {
  if (_active) {
    log.warn('voice agent already active');
    return false;
  }

  const config = getConfig();
  const name = agentName || config.AGENT_NAME;

  if (!config.ELEVENLABS_API_KEY) {
    log.info('no ELEVENLABS_API_KEY - use regular text chat instead');
    return false;
  }

  if (_micMuted && !_audioOutputEnabled) {
    log.info('both mic and audio output disabled - use regular text chat');
    return false;
  }

  // Load system prompt and CLI session for tool calls
  _systemPrompt = loadSystemPrompt();
  _cliSessionId = memory.getLastCliSessionId();

  _active = true;
  _setStatus('connecting');

  try {
    // Step 1: Provision agent on ElevenLabs
    const agentId = await provisionAgent(name);
    if (!agentId) {
      log.error('failed to provision agent');
      _cleanup();
      return false;
    }
    _agentId = agentId;

    // Step 2: If mic is on, connect immediately
    // If mic is off, defer connection until first message
    if (!_micMuted) {
      const wsUrl = await getWebSocketUrl(agentId);
      if (!wsUrl) {
        log.error('failed to get WebSocket URL');
        _cleanup();
        return false;
      }
      _wsUrl = wsUrl;
      _connect(wsUrl);
    } else {
      // Ready but not connected - will connect on first sendText()
      _setStatus('disconnected');
      log.info('voice agent ready (will connect on first message)');
    }

    return true;
  } catch (err) {
    log.error(`failed to start voice agent: ${err}`);
    _cleanup();
    return false;
  }
}
```

**Connection gate:**
- Mic on: Connect immediately (continuous listening)
- Mic off: Defer connection until first message (save cost)

## Exported API

| Function | Purpose |
|----------|---------|
| `startVoiceAgent(agentName)` | Start voice agent session |
| `stopVoiceAgent()` | Stop voice agent |
| `isVoiceAgentActive()` | Check if active |
| `setMicMuted(muted)` | Mute/unmute mic |
| `setAudioOutputEnabled(enabled)` | Enable/disable audio output |
| `sendText(text)` | Inject text into call |
| `getVoiceAgentStatus()` | Get current status |
| `getConversationId()` | Get ElevenLabs conversation ID |
| `onVoiceAgentEvent(event, listener)` | Subscribe to events |
| `configureVoiceCall(opts)` | Configure callbacks |

## See Also

- `src/main/ipc/audio.ts` - IPC handlers for voice agent control
- `src/main/inference.ts` - Claude Code streaming for tool calls
- `src/main/memory.ts` - Memory search for recall_memory tool
- `src/main/channels/telegram.ts` - Telegram messaging
