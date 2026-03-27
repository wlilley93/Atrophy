# src/main/inference.ts - Claude CLI Streaming

**Dependencies:** Node.js built-ins, `uuid`, `./config`, `./thinking`, `./agency`, `./inner-life`, `./inner-life-needs`, `./inner-life-compress`, `./status`, `./memory`, `./mcp-registry`, `./logger`  
**Purpose:** Claude Code subprocess wrapper for streaming inference with context injection

## Overview

This module is the most complex in the codebase. It wraps the Claude CLI subprocess for streaming inference, handles context assembly, manages sentence-level streaming for TTS synchronization, parses tool calls, and integrates with the inner life emotional state system.

## Two Inference Modes

| Mode | Function | Use Case |
|------|----------|----------|
| **Streaming** | `streamInference()` | GUI conversation - emits events as they arrive |
| **One-shot** | `runInferenceOneshot()` | Summaries, background tasks - returns full response |

## Context Prefetch Cache

```typescript
interface ContextCache {
  recentTurns: string[];
  sessionMood: string | null;
  recentSummaries: memory.Summary[];
  lastSessionTime: string | null;
  activeThreads: memory.Thread[];
  crossAgentSummaries: { agent: string; display_name: string; summaries: { content: string; created_at: string; mood: string | null }[] }[];
  emotionalState: EmotionalState;
  timestamp: number;
}

let _contextCache: ContextCache | null = null;
const CACHE_TTL_MS = 30_000; // 30 seconds
```

**Purpose:** Cache context data during idle time to reduce send latency. The cache is rebuilt when any `getCached()` call misses.

### prefetchContext

```typescript
export function prefetchContext(): void {
  const t0 = Date.now();
  try {
    const recentTurns = memory.getRecentCompanionTurns();
    const sessionMood = memory.getCurrentSessionMood();
    const recentSummaries = memory.getRecentSummaries(10);
    const lastSessionTime = memory.getLastSessionTime();
    const activeThreads = memory.getActiveThreads();
    const crossAgentSummaries = memory.getOtherAgentsRecentSummaries(2, 5);
    const emotionalState = loadState();

    _contextCache = {
      recentTurns,
      sessionMood,
      recentSummaries,
      lastSessionTime,
      activeThreads,
      crossAgentSummaries,
      emotionalState,
      timestamp: Date.now(),
    };
    log.debug(`prefetchContext: ${Date.now() - t0}ms`);
  } catch (e) {
    log.debug(`prefetchContext failed: ${e}`);
  }
}
```

**When called:**
- After app initialization
- After each inference completes
- On agent switch

### getCached Helper

```typescript
function getCached<K extends keyof ContextCache>(key: K, fallback: () => ContextCache[K]): ContextCache[K] {
  if (_contextCache && (Date.now() - _contextCache.timestamp < CACHE_TTL_MS)) {
    return _contextCache[key];
  }
  // Cache miss - rebuild full cache inline
  prefetchContext();
  if (_contextCache) return _contextCache[key];
  return fallback();
}
```

**Why rebuild all on miss:** Subsequent `getCached()` calls in the same `buildAgencyContext()` invocation hit the cache instead of each running their own DB query.

## Model Whitelist

```typescript
export const ALLOWED_MODELS = new Set([
  'claude-haiku-4-5-20251001',
  'claude-sonnet-4-6',
  'claude-opus-4-6',
  'claude-sonnet-4-5-20241022',
]);

const DEFAULT_MODEL = 'claude-sonnet-4-6';
```

**Purpose:** Restrict models to those available via Max subscription (no API cost).

## Tool Blacklist

```typescript
const TOOL_BLACKLIST = [
  // Destructive system commands
  'Bash(rm -rf:*)',
  'Bash(sudo:*)',
  'Bash(shutdown:*)',
  'Bash(reboot:*)',
  // Database direct access
  'Bash(sqlite3*memory.db:*)',
  // Credential file access
  'Bash(cat*.env:*)',
  'Bash(cat*server_token:*)',
  // Google credential access
  'Bash(cat*token.json:*)',
  // ... more patterns
];
```

**Purpose:** Block dangerous commands at the inference level. Patterns use glob-style matching against tool call arguments.

## Sentence Boundary Detection

```typescript
// Period/question/exclamation followed by space or end
const SENTENCE_RE = /(?<=[.!?])\s+|(?<=[.!?])$/;
// Clause boundary: comma/semicolon/dash followed by space
const CLAUSE_RE = /(?<=[,; \u2013\-])\s+/;
// Min chars before clause-level split
const CLAUSE_SPLIT_THRESHOLD = 120;
```

**Purpose:** Split streaming text into sentences for TTS synchronization.

## Environment Sanitization

```typescript
function cleanEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  // Strip ALL Claude Code env vars - nested processes hang otherwise
  for (const key of Object.keys(env)) {
    if (key.toUpperCase().includes('CLAUDE')) {
      delete env[key];
    }
  }
  // NOTE: We intentionally do NOT set CLAUDE_CONFIG_DIR here.
  // The default ~/.claude/ is needed for OAuth token refresh to work.
  // Ensure PATH includes common binary locations
  const extraPaths = [
    path.join(os.homedir(), '.local', 'bin'),
    '/opt/homebrew/bin',
    '/usr/local/bin',
  ];
  const currentPath = env.PATH || '/usr/bin:/bin:/usr/sbin:/sbin';
  const missing = extraPaths.filter(p => !currentPath.includes(p));
  if (missing.length > 0) {
    env.PATH = [...missing, currentPath].join(':');
  }
  return env;
}
```

**Why strip CLAUDE_* env vars:** Nested Claude CLI processes hang if they inherit env vars from parent Claude CLI process.

**Why keep CLAUDE_CONFIG_DIR unset:** OAuth token refresh needs access to `~/.claude/` config.

## MCP Config Generation

```typescript
import { mcpRegistry } from './mcp-registry';

let _mcpConfigPath: string | null = null;

export function resetMcpConfig(): void {
  _mcpConfigPath = null;
  mcpRegistry.clearCache();
}

function getMcpConfigPath(): string {
  const agentName = getConfig().AGENT_NAME;
  if (_mcpConfigPath && !mcpRegistry.needsRestart(agentName)) {
    return _mcpConfigPath;
  }
  const configPath = mcpRegistry.buildConfigForAgent(agentName);
  _mcpConfigPath = configPath;
  return configPath;
}
```

**Purpose:** Get per-agent MCP config path. Cached to avoid rebuilding on every inference call.

## Event Types

```typescript
export interface TextDeltaEvent {
  type: 'TextDelta';
  text: string;
}

export interface SentenceReadyEvent {
  type: 'SentenceReady';
  sentence: string;
  index: number;
}

export interface ToolUseEvent {
  type: 'ToolUse';
  name: string;
  toolId: string;
  inputJson: string;
}

export interface StreamDoneEvent {
  type: 'StreamDone';
  fullText: string;
  sessionId: string;
}

export interface StreamErrorEvent {
  type: 'StreamError';
  message: string;
}

export interface CompactingEvent {
  type: 'Compacting';
}

export interface ToolInputDeltaEvent {
  type: 'ToolInputDelta';
  toolId: string;
  delta: string;
}

export interface ToolResultEvent {
  type: 'ToolResult';
  toolId: string;
  toolName: string;
  output: string;
}

export interface ThinkingDeltaEvent {
  type: 'ThinkingDelta';
  text: string;
}

export type InferenceEvent =
  | TextDeltaEvent
  | SentenceReadyEvent
  | ToolUseEvent
  | ToolInputDeltaEvent
  | ToolResultEvent
  | ThinkingDeltaEvent
  | StreamDoneEvent
  | StreamErrorEvent
  | CompactingEvent;
```

## Agency Context Assembly

```typescript
const _agencyState = new Map<string, { turnCount: number; sessionStartInjected: boolean }>();

function getAgencyState(agent?: string): { turnCount: number; sessionStartInjected: boolean } {
  const key = agent || getConfig().AGENT_NAME;
  let state = _agencyState.get(key);
  if (!state) {
    state = { turnCount: 0, sessionStartInjected: false };
    _agencyState.set(key, state);
  }
  return state;
}

export function resetAgencyState(agent?: string): void {
  const key = agent || getConfig().AGENT_NAME;
  _agencyState.set(key, { turnCount: 0, sessionStartInjected: false });
}
```

**Purpose:** Track what's been injected per agent-session to avoid repeating static content. Keyed by agent name so background agents don't share state with desktop session.

### buildAgencyContext

```typescript
function buildAgencyContext(userMessage: string, senderName?: string): string {
  // Auto-detect emotional signals and apply them
  const signals = detectEmotionalSignals(userMessage);
  if (Object.keys(signals).length > 0) {
    // Apply signals to emotional state (single-chat or group mode)
    // ...
  }

  const parts: string[] = [timeOfDayContext().context];

  // Inner life - emotional state (compressed for token efficiency)
  if (senderName && senderName !== getConfig().USER_NAME) {
    // Group mode: per-user state
    const userId = sanitizeUserId(senderName);
    parts.push(formatUserStateForContext(userId, loadState()));
  } else {
    // Single-chat mode: agent-global state
    const emotionalState = getCached('emotionalState', () => loadState());
    parts.push(compressForContext(emotionalState, { sessionStart: !getAgencyState().sessionStartInjected }));
  }

  // Detected patterns - only the ones that trigger
  if (detectMoodShift(userMessage)) {
    parts.push(moodShiftSystemNote());
  }
  if (detectValidationSeeking(userMessage)) {
    parts.push(validationSystemNote());
  }
  if (detectCompulsiveModelling(userMessage)) {
    parts.push(modellingInterruptNote());
  }

  // Energy matching
  const energy = energyNote(userMessage);
  if (energy) parts.push(energy);

  // Drift detection
  const recentTurns = getCached('recentTurns', () => memory.getRecentCompanionTurns());
  const driftNote = detectDrift(recentTurns);
  if (driftNote) parts.push(driftNote);

  // Session mood
  const sessionMood = getCached('sessionMood', () => memory.getCurrentSessionMood());
  if (sessionMood === 'heavy') {
    parts.push('The session mood is heavy. Be present before being useful.');
  }

  // First turn only (static content)
  if (!getAgencyState().sessionStartInjected) {
    // Status awareness
    const status = getStatus();
    if (status.returned_from) {
      parts.push(`${config.USER_NAME} just came back (was: ${status.returned_from}).`);
    }

    // Session patterns
    const recentSessions = getCached('recentSummaries', () => memory.getRecentSummaries(10));
    const pattern = sessionPatternNote(recentSessions.length, times);
    if (pattern) parts.push(pattern);

    // Time-gap awareness
    const lastTime = getCached('lastSessionTime', () => memory.getLastSessionTime());
    const gapNote = timeGapNote(lastTime);
    if (gapNote) parts.push(gapNote);

    // Memory tool nudge
    parts.push('You may surface a relevant memory unprompted if context makes it natural.');

    // Obsidian instructions
    if (config.OBSIDIAN_AVAILABLE) {
      parts.push('Obsidian vault is available. Write notes when something matters...');
    }

    // Active threads
    const threads = getCached('activeThreads', () => memory.getActiveThreads());
    if (threads.length > 0) {
      parts.push(`Active threads: ${threads.map(t => t.name).join(', ')}`);
    }

    // Cross-agent awareness
    const otherAgents = getCached('crossAgentSummaries', () => memory.getOtherAgentsRecentSummaries(2, 5));
    if (otherAgents.length > 0) {
      // Build cross-agent summary section
    }

    getAgencyState().sessionStartInjected = true;
  }

  getAgencyState().turnCount++;
  return parts.join('\n\n');
}
```

**Context injection strategy:**
- **Every turn:** Time context, emotional state, detected patterns, energy matching, drift detection, session mood
- **First turn only:** Status awareness, session patterns, time-gap, memory nudge, Obsidian instructions, active threads, cross-agent awareness

**Compression:** `compressForContext()` produces ~50-80 tokens vs ~150-200 for full `formatForContext()`.

## streamInference Function

```typescript
export function streamInference(
  userMessage: string,
  systemPrompt: string,
  cliSessionId: string | null,
  effort?: EffortLevel,
): EventEmitter {
  const emitter = new EventEmitter();
  const config = getConfig();

  // Build agency context
  const agencyContext = buildAgencyContext(userMessage);
  
  // Determine model
  const model = eff === 'high' || eff === 'max' 
    ? 'claude-opus-4-6' 
    : config.CLAUDE_MODEL || DEFAULT_MODEL;

  // Build Claude CLI command
  const args = [
    '--output-format', 'stream-json',
    '--model', model,
    '--mcp-config', getMcpConfigPath(),
  ];

  // Add resume flag if we have a CLI session ID
  if (cliSessionId) {
    args.push('--resume', cliSessionId);
  }

  // Add effort level
  if (effort) {
    args.push('--effort', effort);
  }

  // Add allowed tools
  args.push('--allowedTools', 'mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*,mcp__elevenlabs__*');

  // Add disallowed tools (blacklist + agent-specific)
  const disallowed = [...TOOL_BLACKLIST];
  const disabledTools = config.DISABLED_TOOLS || [];
  for (const tool of disabledTools) {
    disallowed.push(`Bash(${tool}:*)`);
  }
  if (disallowed.length > 0) {
    args.push('--disallowedTools', disallowed.join(','));
  }

  // Build full message with context
  const fullMessage = `${agencyContext}\n\n## User Message\n\n${userMessage}`;

  // Spawn Claude CLI
  const proc = spawn(config.CLAUDE_BIN, args, {
    cwd: agentCwd(),
    env: cleanEnv(),
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  // Send message to stdin
  proc.stdin?.write(`${fullMessage}\n`);
  proc.stdin?.end();

  // Parse streaming JSON output
  let buffer = '';
  let fullText = '';
  let sentenceIndex = 0;
  let sentenceBuffer = '';
  let activeToolCalls = new Map<string, { name: string; inputJson: string }>();

  proc.stdout?.on('data', (chunk: Buffer) => {
    buffer += chunk.toString();
    
    // Process complete JSON lines
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';  // Keep incomplete line in buffer

    for (const line of lines) {
      if (!line.trim()) continue;
      
      try {
        const event = JSON.parse(line);
        
        // Handle different event types from Claude CLI
        switch (event.type) {
          case 'content_block_start':
            // Handle tool use start
            if (event.content_block?.type === 'tool_use') {
              activeToolCalls.set(event.content_block.id, {
                name: event.content_block.name,
                inputJson: '',
              });
              emitter.emit('event', {
                type: 'ToolUse',
                name: event.content_block.name,
                toolId: event.content_block.id,
                inputJson: '',
              } as ToolUseEvent);
            }
            break;

          case 'content_block_delta':
            if (event.delta?.type === 'text_delta') {
              const text = event.delta.text;
              fullText += text;
              sentenceBuffer += text;

              // Emit text delta
              emitter.emit('event', {
                type: 'TextDelta',
                text,
              } as TextDeltaEvent);

              // Check for sentence boundaries
              const sentences = sentenceBuffer.split(SENTENCE_RE);
              if (sentences.length > 1) {
                for (let i = 0; i < sentences.length - 1; i++) {
                  const sentence = sentences[i].trim();
                  if (sentence.length > 0) {
                    emitter.emit('event', {
                      type: 'SentenceReady',
                      sentence,
                      index: sentenceIndex++,
                    } as SentenceReadyEvent);
                  }
                }
                sentenceBuffer = sentences[sentences.length - 1];
              }

              // Clause-level split for long buffers
              if (sentenceBuffer.length > CLAUSE_SPLIT_THRESHOLD) {
                const clauses = sentenceBuffer.split(CLAUSE_RE);
                if (clauses.length > 1) {
                  const clause = clauses.slice(0, -1).join('').trim();
                  if (clause.length > 0) {
                    emitter.emit('event', {
                      type: 'SentenceReady',
                      sentence: clause,
                      index: sentenceIndex++,
                    } as SentenceReadyEvent);
                  }
                  sentenceBuffer = clauses[clauses.length - 1];
                }
              }
            } else if (event.delta?.type === 'input_json_delta') {
              // Tool input JSON streaming
              const toolId = event.content_block_index;
              const delta = event.delta.partial_json;
              if (activeToolCalls.has(toolId)) {
                const toolCall = activeToolCalls.get(toolId)!;
                toolCall.inputJson += delta;
                emitter.emit('event', {
                  type: 'ToolInputDelta',
                  toolId,
                  delta,
                } as ToolInputDeltaEvent);
              }
            }
            break;

          case 'content_block_stop':
            // Tool call complete
            const toolId = event.content_block_index;
            if (activeToolCalls.has(toolId)) {
              const toolCall = activeToolCalls.get(toolId)!;
              emitter.emit('event', {
                type: 'ToolResultEvent',
                toolId,
                toolName: toolCall.name,
                output: toolCall.inputJson,
              } as ToolResultEvent);
              activeToolCalls.delete(toolId);
            }
            break;

          case 'message_delta':
            // Check for context compaction
            if (event.delta?.stop_reason === 'context_compaction') {
              emitter.emit('event', { type: 'Compacting' } as CompactingEvent);
            }
            break;

          case 'message_stop':
            // Stream complete
            // Flush remaining sentence buffer
            if (sentenceBuffer.trim()) {
              emitter.emit('event', {
                type: 'SentenceReady',
                sentence: sentenceBuffer.trim(),
                index: sentenceIndex,
              } as SentenceReadyEvent);
            }

            // Get CLI session ID from response
            const sessionId = event.session_id || null;

            emitter.emit('event', {
              type: 'StreamDone',
              fullText,
              sessionId,
            } as StreamDoneEvent);
            break;
        }
      } catch (e) {
        // JSON parse error - likely incomplete line, wait for more data
      }
    }
  });

  proc.stderr?.on('data', (chunk: Buffer) => {
    const text = chunk.toString();
    // Check for thinking output (starts with "Thinking:")
    if (text.includes('Thinking:')) {
      emitter.emit('event', {
        type: 'ThinkingDelta',
        text: text.replace('Thinking:', '').trim(),
      } as ThinkingDeltaEvent);
    }
  });

  proc.on('close', (code) => {
    if (code !== 0 && code !== null) {
      emitter.emit('event', {
        type: 'StreamError',
        message: `Claude CLI exited with code ${code}`,
      } as StreamErrorEvent);
    }
  });

  proc.on('error', (err) => {
    emitter.emit('event', {
      type: 'StreamError',
      message: err.message,
    } as StreamErrorEvent);
  });

  return emitter;
}
```

**Streaming flow:**
1. Spawn Claude CLI subprocess with `--output-format stream-json`
2. Send user message (with agency context) to stdin
3. Parse streaming JSON events from stdout
4. Emit `TextDelta` for each text chunk
5. Accumulate text and emit `SentenceReady` at sentence boundaries
6. Track tool calls via `ToolUse`, `ToolInputDelta`, `ToolResult`
7. Emit `Compacting` when context window is compacted
8. Emit `StreamDone` with full text and new CLI session ID

## runInferenceOneshot Function

```typescript
export async function runInferenceOneshot(
  messages: { role: string; content: string }[],
  systemPrompt?: string,
  timeoutMs = 60000,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const config = getConfig();
    const args = [
      '--output-format', 'json',
      '--model', config.CLAUDE_MODEL || DEFAULT_MODEL,
      '--mcp-config', getMcpConfigPath(),
    ];

    const proc = spawn(config.CLAUDE_BIN, args, {
      cwd: agentCwd(),
      env: cleanEnv(),
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    // Build message
    const fullMessage = messages.map(m => `${m.role}: ${m.content}`).join('\n\n');
    if (systemPrompt) {
      proc.stdin?.write(`${systemPrompt}\n\n${fullMessage}\n`);
    } else {
      proc.stdin?.write(`${fullMessage}\n`);
    }
    proc.stdin?.end();

    let output = '';
    const timeout = setTimeout(() => {
      try { proc.kill(); } catch { /* noop */ }
      reject(new Error('Inference timed out'));
    }, timeoutMs);

    proc.stdout?.on('data', (chunk: Buffer) => {
      output += chunk.toString();
    });

    proc.on('close', (code) => {
      clearTimeout(timeout);
      if (code !== 0 && code !== null) {
        reject(new Error(`Claude CLI exited with code ${code}`));
      } else {
        try {
          const result = JSON.parse(output);
          resolve(result.content || output);
        } catch {
          resolve(output);
        }
      }
    });

    proc.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });
  });
}
```

**Use cases:**
- Session summary generation
- Background inference tasks
- Non-streaming contexts

## stopInference Function

```typescript
let _activeProcesses = new Map<string, ChildProcess>();

export function stopInference(agentName?: string): void {
  const name = agentName || getConfig().AGENT_NAME;
  const proc = _activeProcesses.get(name);
  if (proc) {
    try {
      proc.kill('SIGTERM');
    } catch { /* already dead */ }
    _activeProcesses.delete(name);
  }
}

export function stopAllInference(): void {
  for (const [name, proc] of _activeProcesses) {
    try {
      proc.kill('SIGTERM');
    } catch { /* noop */ }
  }
  _activeProcesses.clear();
}
```

**Purpose:** Kill active Claude CLI subprocess (e.g., on agent switch or user stop).

## MCP Config Integration

```typescript
let _mcpConfigPath: string | null = null;

export function resetMcpConfig(): void {
  _mcpConfigPath = null;
  mcpRegistry.clearCache();
}

function getMcpConfigPath(): string {
  const agentName = getConfig().AGENT_NAME;
  if (_mcpConfigPath && !mcpRegistry.needsRestart(agentName)) {
    return _mcpConfigPath;
  }
  const configPath = mcpRegistry.buildConfigForAgent(agentName);
  _mcpConfigPath = configPath;
  return configPath;
}
```

**Purpose:** Get per-agent MCP config path. The MCP registry builds config based on agent's manifest `mcp.include` and `mcp.exclude` lists.

## Effort Classification

```typescript
import { classifyEffort, EffortLevel } from './thinking';

// In streamInference:
const effort = config.ADAPTIVE_EFFORT 
  ? classifyEffort(userMessage) 
  : (config.CLAUDE_EFFORT as EffortLevel);

const model = effort === 'high' || effort === 'max' 
  ? 'claude-opus-4-6' 
  : config.CLAUDE_MODEL || DEFAULT_MODEL;
```

**Purpose:** Adaptively select model and effort based on task complexity.

## Exported API Summary

| Function | Purpose |
|----------|---------|
| `streamInference(userMessage, systemPrompt, cliSessionId, effort)` | Start streaming inference, returns EventEmitter |
| `runInferenceOneshot(messages, systemPrompt, timeoutMs)` | Blocking inference, returns full response |
| `stopInference(agentName)` | Stop inference for specific agent |
| `stopAllInference()` | Stop all active inference |
| `resetMcpConfig()` | Reset MCP config cache |
| `prefetchContext()` | Prefetch context data into cache |
| `invalidateContextCache()` | Invalidate context cache |
| `resetAgencyState(agent)` | Reset agency injection state |

## Event Types

| Event | Payload | When Emitted |
|-------|---------|--------------|
| `TextDelta` | `{ text: string }` | Each text chunk from Claude |
| `SentenceReady` | `{ sentence: string, index: number }` | Complete sentence detected |
| `ToolUse` | `{ name: string, toolId: string, inputJson: string }` | Tool call started |
| `ToolInputDelta` | `{ toolId: string, delta: string }` | Tool input JSON chunk |
| `ToolResult` | `{ toolId: string, toolName: string, output: string }` | Tool call complete |
| `ThinkingDelta` | `{ text: string }` | Thinking output (stderr) |
| `Compacting` | `{}` | Context window compacted |
| `StreamDone` | `{ fullText: string, sessionId: string }` | Stream complete |
| `StreamError` | `{ message: string }` | Error occurred |

## See Also

- `src/main/context.ts` - Context assembly helpers
- `src/main/prompts.ts` - Prompt loading
- `src/main/thinking.ts` - Effort classification
- `src/main/agency.ts` - Pattern detection for context
- `src/main/inner-life.ts` - Emotional state management
- `src/main/mcp-registry.ts` - MCP server configuration
