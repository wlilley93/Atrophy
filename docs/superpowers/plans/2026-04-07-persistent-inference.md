# Persistent Per-Agent Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace spawn-per-message inference with one persistent Claude CLI process per agent, eliminating boot overhead, MCP cold-starts, and the config singleton race.

**Architecture:** New `AgentProcess` class owns a persistent `claude` subprocess per agent with open stdin/stdout pipes. Messages queue and drain sequentially. A `ProcessPool` registry manages all agent processes. The existing `streamInference()` becomes a thin wrapper that delegates to the pool. `runInferenceOneshot()` stays unchanged.

**Tech Stack:** Node.js `child_process.spawn`, EventEmitter, existing inference event types

**Spec:** `docs/superpowers/specs/2026-04-07-persistent-inference-design.md`

---

### Task 1: Create AgentProcess class

**Files:**
- Create: `src/main/agent-process.ts`
- Test: `src/main/__tests__/agent-process.test.ts`

This is the core new module. It manages one persistent `claude` CLI subprocess per agent.

- [ ] **Step 1: Write the failing test for AgentProcess construction**

```typescript
// src/main/__tests__/agent-process.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock child_process before importing
vi.mock('child_process', () => ({
  spawn: vi.fn(),
}));

vi.mock('../config', () => ({
  getConfig: vi.fn(() => ({
    AGENT_NAME: 'xan',
    CLAUDE_BIN: '/usr/local/bin/claude',
    CLAUDE_MODEL: 'sonnet',
    CLAUDE_EFFORT: 'medium',
    ADAPTIVE_EFFORT: false,
    DISABLED_TOOLS: [],
  })),
  USER_DATA: '/tmp/test-atrophy',
}));

vi.mock('../logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }),
}));

import { AgentProcess, type AgentProcessConfig } from '../agent-process';

describe('AgentProcess', () => {
  const testConfig: AgentProcessConfig = {
    agentName: 'xan',
    claudeBin: '/usr/local/bin/claude',
    model: 'sonnet',
    effort: 'medium',
    disabledTools: [],
    mcpConfigPath: '/tmp/mcp/xan.config.json',
    systemPrompt: 'You are Xan.',
    sessionId: null,
    cwd: '/tmp/test-atrophy/agents/xan',
  };

  it('constructs with config', () => {
    const ap = new AgentProcess(testConfig);
    expect(ap.agentName).toBe('xan');
    expect(ap.isAlive()).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: FAIL - `AgentProcess` not found

- [ ] **Step 3: Write AgentProcess skeleton**

```typescript
// src/main/agent-process.ts
/**
 * Persistent Claude CLI process per agent.
 *
 * Owns one long-running `claude` subprocess with open stdin/stdout pipes.
 * Messages queue and drain sequentially. Structured JSON events stream
 * back on stdout and are dispatched to per-message EventEmitters.
 */

import { spawn, ChildProcess } from 'child_process';
import { EventEmitter } from 'events';
import * as path from 'path';
import * as os from 'os';
import { v4 as uuidv4 } from 'uuid';
import { createLogger } from './logger';

const log = createLogger('agent-process');

// Tool blacklist - duplicated from inference.ts to avoid circular deps.
// These protect sensitive files from agent access.
const TOOL_BLACKLIST = [
  'Bash(cat*.env:*)',
  'Bash(head*.env:*)',
  'Bash(tail*.env:*)',
  'Bash(less*.env:*)',
  'Bash(more*.env:*)',
  'Bash(grep*.env:*)',
  'Bash(cat*config.json:*)',
  'Bash(cat*server_token:*)',
  'Bash(cat*token.json:*)',
  'Bash(cat*credentials.json:*)',
  'Bash(cat*.google*:*)',
];

export interface AgentProcessConfig {
  agentName: string;
  claudeBin: string;
  model: string;
  effort: string;
  disabledTools: string[];
  mcpConfigPath: string;
  systemPrompt: string;
  sessionId: string | null;
  cwd: string;
}

export interface QueuedMessage {
  text: string;
  source: 'desktop' | 'telegram' | 'server' | 'cron' | 'other';
  senderName?: string;
  emitter: EventEmitter;
}

export class AgentProcess {
  readonly agentName: string;
  private proc: ChildProcess | null = null;
  private config: AgentProcessConfig;
  private queue: QueuedMessage[] = [];
  private busy = false;
  private sessionId: string | null;
  private lineBuffer = '';
  private currentEmitter: EventEmitter | null = null;

  // Crash recovery
  private restartCount = 0;
  private restartWindowStart = 0;
  private static MAX_RESTARTS = 5;
  private static RESTART_WINDOW_MS = 5 * 60 * 1000;
  private static RESTART_DELAY_MS = 2000;

  // Inactivity timeout
  private lastActivity = 0;
  private timeoutTimer: ReturnType<typeof setInterval> | null = null;
  private static TIMEOUT_MS = 20 * 60 * 1000;

  constructor(config: AgentProcessConfig) {
    this.config = config;
    this.agentName = config.agentName;
    this.sessionId = config.sessionId;
  }

  isAlive(): boolean {
    return this.proc !== null && this.proc.exitCode === null && !this.proc.killed;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/agent-process.ts src/main/__tests__/agent-process.test.ts
git commit -m "feat(inference): add AgentProcess skeleton with config and lifecycle"
```

---

### Task 2: Implement process spawning and stdin/stdout piping

**Files:**
- Modify: `src/main/agent-process.ts`
- Modify: `src/main/__tests__/agent-process.test.ts`

- [ ] **Step 1: Write the failing test for start()**

Add to the test file:

```typescript
import { spawn } from 'child_process';
import { EventEmitter } from 'events';
import { Readable, Writable } from 'stream';

function mockProc(): ChildProcess {
  const proc = new EventEmitter() as ChildProcess;
  (proc as any).stdin = new Writable({ write(_c, _e, cb) { cb(); } });
  (proc as any).stdout = new Readable({ read() {} });
  (proc as any).stderr = new Readable({ read() {} });
  (proc as any).pid = 12345;
  (proc as any).exitCode = null;
  (proc as any).killed = false;
  (proc as any).kill = vi.fn();
  return proc;
}

describe('AgentProcess.start()', () => {
  beforeEach(() => {
    vi.mocked(spawn).mockReturnValue(mockProc());
  });

  it('spawns claude with correct args', () => {
    const ap = new AgentProcess(testConfig);
    ap.start();
    expect(spawn).toHaveBeenCalledTimes(1);
    const args = vi.mocked(spawn).mock.calls[0][1] as string[];
    expect(args).toContain('--output-format');
    expect(args).toContain('stream-json');
    expect(args).toContain('--verbose');
    expect(args).toContain('--dangerously-skip-permissions');
    expect(ap.isAlive()).toBe(true);
  });

  it('includes --session-id for new sessions', () => {
    const ap = new AgentProcess(testConfig);
    ap.start();
    const args = vi.mocked(spawn).mock.calls[0][1] as string[];
    expect(args).toContain('--session-id');
  });

  it('includes --resume for existing sessions', () => {
    const config = { ...testConfig, sessionId: 'abc-123-def' };
    const ap = new AgentProcess(config);
    ap.start();
    const args = vi.mocked(spawn).mock.calls[0][1] as string[];
    expect(args).toContain('--resume');
    expect(args).toContain('abc-123-def');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: FAIL - `start` method not implemented

- [ ] **Step 3: Implement start()**

Add to `AgentProcess` class in `agent-process.ts`:

```typescript
  /** Clean env - strip CLAUDE_ vars, extend PATH */
  private cleanEnv(): NodeJS.ProcessEnv {
    const env = { ...process.env };
    for (const key of Object.keys(env)) {
      if (key.toUpperCase().includes('CLAUDE')) delete env[key];
    }
    const extraPaths = [
      path.join(os.homedir(), '.local', 'bin'),
      '/opt/homebrew/bin',
      '/usr/local/bin',
    ];
    const currentPath = env.PATH || '/usr/bin:/bin:/usr/sbin:/sbin';
    const missing = extraPaths.filter(p => !currentPath.includes(p));
    if (missing.length > 0) env.PATH = [...missing, currentPath].join(':');
    return env;
  }

  /** Build CLI args for spawning */
  private buildArgs(): string[] {
    const args = [
      '--output-format', 'stream-json',
      '--verbose',
      '--dangerously-skip-permissions',
      '--model', this.config.model,
      '--effort', this.config.effort,
      '--mcp-config', this.config.mcpConfigPath,
      '--allowedTools', '*',
      '--disallowedTools', [...TOOL_BLACKLIST, ...this.config.disabledTools].join(','),
    ];

    if (this.sessionId) {
      args.push('--resume', this.sessionId);
    } else {
      const newId = `atrophy-${this.agentName}-${uuidv4()}`;
      this.sessionId = newId;
      args.push('--session-id', newId);
      args.push('--system-prompt', this.config.systemPrompt);
    }

    return args;
  }

  /** Spawn the persistent CLI process */
  start(): void {
    if (this.isAlive()) return;

    const args = this.buildArgs();
    log.info(`[${this.agentName}] starting persistent process`);

    this.proc = spawn(this.config.claudeBin, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: this.cleanEnv(),
      cwd: this.config.cwd,
      detached: false,
    });

    log.info(`[${this.agentName}] pid=${this.proc.pid}`);
    this.lastActivity = Date.now();
    this.lineBuffer = '';

    // Parse stdout line by line
    this.proc.stdout?.on('data', (chunk: Buffer) => {
      this.lastActivity = Date.now();
      this.lineBuffer += chunk.toString();
      const lines = this.lineBuffer.split('\n');
      this.lineBuffer = lines.pop() || '';
      for (const line of lines) {
        if (line.trim()) this.onStdoutLine(line.trim());
      }
    });

    // Accumulate stderr for error reporting
    let stderrChunks = '';
    this.proc.stderr?.on('data', (chunk: Buffer) => {
      if (stderrChunks.length < 8192) stderrChunks += chunk.toString();
    });

    // Handle unexpected exit
    this.proc.on('close', (code, signal) => {
      const elapsed = this.lastActivity ? ((Date.now() - this.lastActivity) / 1000).toFixed(1) : '?';
      log.warn(`[${this.agentName}] process exited: code=${code} signal=${signal} idle=${elapsed}s`);
      this.proc = null;

      // Error the current message if one was in-flight
      if (this.currentEmitter) {
        const errMsg = stderrChunks.trim().slice(0, 300) || `claude exited (code=${code}, signal=${signal})`;
        this.currentEmitter.emit('event', { type: 'StreamError', message: errMsg });
        this.currentEmitter = null;
        this.busy = false;
      }

      // Auto-restart if within limits
      this.maybeRestart();
    });

    this.proc.on('error', (err) => {
      log.error(`[${this.agentName}] process error: ${err}`);
      this.proc = null;
      if (this.currentEmitter) {
        this.currentEmitter.emit('event', { type: 'StreamError', message: String(err) });
        this.currentEmitter = null;
        this.busy = false;
      }
    });

    // Inactivity timeout
    if (this.timeoutTimer) clearInterval(this.timeoutTimer);
    this.timeoutTimer = setInterval(() => {
      if (this.busy) return; // Don't timeout during active inference
      if (Date.now() - this.lastActivity > AgentProcess.TIMEOUT_MS) {
        log.info(`[${this.agentName}] idle timeout - stopping process`);
        this.stop();
      }
    }, 60_000);
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/agent-process.ts src/main/__tests__/agent-process.test.ts
git commit -m "feat(inference): implement AgentProcess.start() with stdin/stdout piping"
```

---

### Task 3: Implement message queue and drain

**Files:**
- Modify: `src/main/agent-process.ts`
- Modify: `src/main/__tests__/agent-process.test.ts`

- [ ] **Step 1: Write the failing test for send() and drain()**

```typescript
describe('AgentProcess.send()', () => {
  it('writes message to stdin when idle', () => {
    const proc = mockProc();
    vi.mocked(spawn).mockReturnValue(proc);
    const ap = new AgentProcess(testConfig);
    ap.start();

    const emitter = new EventEmitter();
    const stdinWrite = vi.spyOn(proc.stdin!, 'write');

    ap.send({ text: 'hello', source: 'desktop', emitter });

    expect(stdinWrite).toHaveBeenCalledTimes(1);
    const written = stdinWrite.mock.calls[0][0] as string;
    expect(written).toContain('hello');
    expect(written).toEndWith('\n');
  });

  it('queues messages when busy', () => {
    const proc = mockProc();
    vi.mocked(spawn).mockReturnValue(proc);
    const ap = new AgentProcess(testConfig);
    ap.start();

    const em1 = new EventEmitter();
    const em2 = new EventEmitter();
    const stdinWrite = vi.spyOn(proc.stdin!, 'write');

    ap.send({ text: 'first', source: 'desktop', emitter: em1 });
    ap.send({ text: 'second', source: 'telegram', emitter: em2 });

    // Only one message sent to stdin
    expect(stdinWrite).toHaveBeenCalledTimes(1);
    expect((stdinWrite.mock.calls[0][0] as string)).toContain('first');
  });

  it('auto-starts process if not alive', () => {
    const proc = mockProc();
    vi.mocked(spawn).mockReturnValue(proc);
    const ap = new AgentProcess(testConfig);
    // Don't call start() - send() should auto-start
    const emitter = new EventEmitter();
    ap.send({ text: 'hello', source: 'desktop', emitter });

    expect(spawn).toHaveBeenCalledTimes(1);
    expect(ap.isAlive()).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: FAIL - `send` method not implemented

- [ ] **Step 3: Implement send() and drain()**

Add to `AgentProcess` class:

```typescript
  /** Queue a message and process if idle */
  send(msg: QueuedMessage): void {
    this.queue.push(msg);
    if (!this.isAlive()) this.start();
    if (!this.busy) this.drain();
  }

  /** Dequeue and write next message to stdin */
  private drain(): void {
    if (this.busy) return;
    const msg = this.queue.shift();
    if (!msg) return;
    if (!this.isAlive()) {
      msg.emitter.emit('event', { type: 'StreamError', message: 'Process not alive' });
      this.drain(); // Try next message
      return;
    }

    this.busy = true;
    this.currentEmitter = msg.emitter;
    this.lastActivity = Date.now();

    // Build the message with context prefix
    const text = msg.senderName
      ? `[From: ${msg.senderName}]\n\n${msg.text}`
      : msg.text;

    log.info(`[${this.agentName}] sending message (${msg.source}, ${text.length} chars, queue=${this.queue.length})`);

    this.proc!.stdin!.write(text + '\n');
  }

  /** Cancel current inference and clear queue */
  cancel(): void {
    if (this.currentEmitter) {
      this.currentEmitter.emit('event', { type: 'StreamError', message: 'Inference cancelled' });
      this.currentEmitter = null;
    }
    this.queue.length = 0;
    this.busy = false;
  }

  /** Get number of queued messages */
  get queueLength(): number {
    return this.queue.length;
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/agent-process.ts src/main/__tests__/agent-process.test.ts
git commit -m "feat(inference): implement AgentProcess message queue and drain"
```

---

### Task 4: Implement stdout JSON parsing and event dispatch

**Files:**
- Modify: `src/main/agent-process.ts`
- Modify: `src/main/__tests__/agent-process.test.ts`

- [ ] **Step 1: Write the failing test for onStdoutLine()**

```typescript
describe('AgentProcess JSON event dispatch', () => {
  it('dispatches TextDelta events to current emitter', () => {
    const proc = mockProc();
    vi.mocked(spawn).mockReturnValue(proc);
    const ap = new AgentProcess(testConfig);
    ap.start();

    const emitter = new EventEmitter();
    const events: any[] = [];
    emitter.on('event', (e) => events.push(e));

    ap.send({ text: 'hello', source: 'desktop', emitter });

    // Simulate stdout JSON line
    const jsonLine = JSON.stringify({
      type: 'assistant',
      message: {
        content: [{ type: 'text', text: 'Hi there' }],
        stop_reason: null,
      },
    });
    proc.stdout!.emit('data', Buffer.from(jsonLine + '\n'));

    expect(events.length).toBeGreaterThan(0);
    expect(events[0].type).toBe('TextDelta');
  });

  it('emits StreamDone and drains queue on result event', () => {
    const proc = mockProc();
    vi.mocked(spawn).mockReturnValue(proc);
    const ap = new AgentProcess(testConfig);
    ap.start();

    const em1 = new EventEmitter();
    const em2 = new EventEmitter();
    const events1: any[] = [];
    const events2: any[] = [];
    em1.on('event', (e) => events1.push(e));
    em2.on('event', (e) => events2.push(e));

    ap.send({ text: 'first', source: 'desktop', emitter: em1 });
    ap.send({ text: 'second', source: 'telegram', emitter: em2 });

    // Simulate result event for first message
    const resultLine = JSON.stringify({
      type: 'result',
      result: 'Hi there',
      session_id: 'test-session-123',
    });
    proc.stdout!.emit('data', Buffer.from(resultLine + '\n'));

    // First emitter should get StreamDone
    const done = events1.find(e => e.type === 'StreamDone');
    expect(done).toBeDefined();
    expect(done.sessionId).toBe('test-session-123');

    // Second message should have been written to stdin
    const stdinWrite = vi.spyOn(proc.stdin!, 'write');
    // drain() was called internally - check it happened
    expect(ap.queueLength).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: FAIL - `onStdoutLine` not dispatching events

- [ ] **Step 3: Implement onStdoutLine() with full event parsing**

Add to `AgentProcess` class. This is the largest method - it mirrors the stdout parsing logic from the current `streamInference()` in `inference.ts`:

```typescript
  // Sentence boundary detection (from inference.ts)
  private static SENTENCE_RE = /(?<=[.!?])\s+|(?<=[.!?])$/;
  private static CLAUSE_RE = /(?<=[,; \u2013\-])\s+/;
  private static CLAUSE_SPLIT_THRESHOLD = 120;

  private fullText = '';
  private sentenceBuffer = '';
  private sentenceIndex = 0;
  private toolCalls: string[] = [];

  /** Reset per-message state before processing a new message */
  private resetMessageState(): void {
    this.fullText = '';
    this.sentenceBuffer = '';
    this.sentenceIndex = 0;
    this.toolCalls = [];
  }

  /** Emit a sentence from the buffer */
  private flushSentence(text: string): void {
    if (!text.trim() || !this.currentEmitter) return;
    this.currentEmitter.emit('event', {
      type: 'SentenceReady',
      sentence: text.trim(),
      index: this.sentenceIndex++,
    });
  }

  /** Process a single line of JSON from stdout */
  private onStdoutLine(line: string): void {
    let event: Record<string, unknown>;
    try {
      event = JSON.parse(line);
    } catch {
      return; // Not valid JSON - skip
    }

    const evtType = event.type as string;
    if (!this.currentEmitter) return;

    // System events (init, compaction)
    if (evtType === 'system') {
      const subtype = (event.subtype as string) || '';
      if (subtype === 'init' && event.session_id) {
        this.sessionId = event.session_id as string;
      } else if (subtype.includes('compact') || subtype.includes('compress')) {
        if (event.session_id) this.sessionId = event.session_id as string;
        this.currentEmitter.emit('event', { type: 'Compacting' });
      }
      return;
    }

    // Assistant message (streaming text + tool use)
    if (evtType === 'assistant') {
      const msg = event.message as Record<string, unknown> | undefined;
      if (!msg) return;

      const content = msg.content as Array<Record<string, unknown>> | undefined;
      if (!content) return;

      for (const block of content) {
        if (block.type === 'text') {
          const text = (block.text as string) || '';
          if (!text) continue;

          // Compute delta from what we've already seen
          const prevLen = this.fullText.length;
          if (text.length <= prevLen) continue;
          const delta = text.slice(prevLen);
          this.fullText = text;

          this.currentEmitter.emit('event', { type: 'TextDelta', text: delta });

          // Sentence detection
          this.sentenceBuffer += delta;
          const parts = this.sentenceBuffer.split(AgentProcess.SENTENCE_RE);
          if (parts.length > 1) {
            for (let i = 0; i < parts.length - 1; i++) {
              this.flushSentence(parts[i]);
            }
            this.sentenceBuffer = parts[parts.length - 1];
          } else if (this.sentenceBuffer.length > AgentProcess.CLAUSE_SPLIT_THRESHOLD) {
            const clauseParts = this.sentenceBuffer.split(AgentProcess.CLAUSE_RE);
            if (clauseParts.length > 1) {
              for (let i = 0; i < clauseParts.length - 1; i++) {
                this.flushSentence(clauseParts[i]);
              }
              this.sentenceBuffer = clauseParts[clauseParts.length - 1];
            }
          }
        }

        if (block.type === 'tool_use') {
          const toolName = (block.name as string) || 'unknown';
          const toolId = (block.id as string) || '';
          this.toolCalls.push(toolName);
          this.currentEmitter.emit('event', {
            type: 'ToolUse',
            name: toolName,
            toolId,
            inputJson: JSON.stringify(block.input || {}),
          });
        }
      }
      return;
    }

    // Tool result
    if (evtType === 'tool_result' || evtType === 'tool_output') {
      const toolId = (event.tool_use_id as string) || (event.tool_id as string) || '';
      const toolName = (event.name as string) || '';
      const output = typeof event.output === 'string' ? event.output : JSON.stringify(event.output || '');
      this.currentEmitter.emit('event', { type: 'ToolResult', toolId, toolName, output });
      return;
    }

    // Thinking
    if (evtType === 'thinking') {
      const thinking = (event.thinking as string) || '';
      if (thinking) {
        this.currentEmitter.emit('event', { type: 'ThinkingDelta', text: thinking });
      }
      return;
    }

    // Result - message complete
    if (evtType === 'result') {
      if (event.session_id) this.sessionId = event.session_id as string;

      const resultText = (event.result as string) || '';
      if (resultText && !this.fullText) this.fullText = resultText;

      // Flush remaining sentence buffer
      const remainder = this.sentenceBuffer.trim();
      if (remainder) this.flushSentence(remainder);

      // Log
      const toolsStr = this.toolCalls.length > 0 ? ` | tools: ${this.toolCalls.join(', ')}` : '';
      log.info(`[${this.agentName}] done | ${this.fullText.length} chars, ${this.sentenceIndex + (remainder ? 1 : 0)} sentences${toolsStr}`);

      this.currentEmitter.emit('event', {
        type: 'StreamDone',
        fullText: this.fullText,
        sessionId: this.sessionId || '',
      });

      // Complete - ready for next message
      this.currentEmitter = null;
      this.busy = false;
      this.resetMessageState();
      this.drain();
      return;
    }
  }
```

Also update `drain()` to call `resetMessageState()`:

```typescript
  private drain(): void {
    if (this.busy) return;
    const msg = this.queue.shift();
    if (!msg) return;
    if (!this.isAlive()) {
      msg.emitter.emit('event', { type: 'StreamError', message: 'Process not alive' });
      this.drain();
      return;
    }

    this.busy = true;
    this.currentEmitter = msg.emitter;
    this.lastActivity = Date.now();
    this.resetMessageState();

    const text = msg.senderName
      ? `[From: ${msg.senderName}]\n\n${msg.text}`
      : msg.text;

    log.info(`[${this.agentName}] sending message (${msg.source}, ${text.length} chars, queue=${this.queue.length})`);

    this.proc!.stdin!.write(text + '\n');
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/agent-process.ts src/main/__tests__/agent-process.test.ts
git commit -m "feat(inference): implement stdout JSON parsing and event dispatch"
```

---

### Task 5: Implement stop, restart, and crash recovery

**Files:**
- Modify: `src/main/agent-process.ts`
- Modify: `src/main/__tests__/agent-process.test.ts`

- [ ] **Step 1: Write the failing test for stop() and restart()**

```typescript
describe('AgentProcess lifecycle', () => {
  it('stop() kills process and clears state', () => {
    const proc = mockProc();
    vi.mocked(spawn).mockReturnValue(proc);
    const ap = new AgentProcess(testConfig);
    ap.start();
    expect(ap.isAlive()).toBe(true);

    ap.stop();
    expect(proc.kill).toHaveBeenCalled();
  });

  it('maybeRestart() respawns after unexpected exit', async () => {
    const proc = mockProc();
    vi.mocked(spawn).mockReturnValue(proc);
    const ap = new AgentProcess(testConfig);
    ap.start();

    // Simulate unexpected exit
    vi.mocked(spawn).mockReturnValue(mockProc());
    (proc as EventEmitter).emit('close', 1, null);

    // Wait for restart delay
    await new Promise(r => setTimeout(r, 2100));
    expect(spawn).toHaveBeenCalledTimes(2);
  });

  it('does not restart past MAX_RESTARTS within window', async () => {
    const proc = mockProc();
    vi.mocked(spawn).mockReturnValue(proc);
    const ap = new AgentProcess(testConfig);
    ap.start();

    // Simulate 6 rapid crashes (exceeds MAX_RESTARTS=5)
    for (let i = 0; i < 6; i++) {
      const newProc = mockProc();
      vi.mocked(spawn).mockReturnValue(newProc);
      (proc as EventEmitter).emit('close', 1, null);
      await new Promise(r => setTimeout(r, 100));
    }

    // Should have stopped trying after 5
    expect(spawn).toHaveBeenCalledTimes(6); // initial + 5 restarts
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: FAIL - `stop()` and `maybeRestart()` not implemented

- [ ] **Step 3: Implement stop(), restart(), maybeRestart()**

Add to `AgentProcess` class:

```typescript
  /** Gracefully stop the process */
  stop(): void {
    if (this.timeoutTimer) {
      clearInterval(this.timeoutTimer);
      this.timeoutTimer = null;
    }

    if (!this.proc) return;

    log.info(`[${this.agentName}] stopping process (pid=${this.proc.pid})`);

    // Remove close handler to prevent auto-restart
    this.proc.removeAllListeners('close');
    this.proc.removeAllListeners('error');

    try { this.proc.kill('SIGTERM'); } catch { /* already dead */ }

    // Escalate to SIGKILL after 10s
    const pid = this.proc.pid;
    const killTimer = setTimeout(() => {
      try {
        process.kill(pid!, 0); // check if alive
        process.kill(pid!, 'SIGKILL');
      } catch { /* already dead */ }
    }, 10_000);

    this.proc.on('close', () => clearTimeout(killTimer));
    this.proc = null;
    this.busy = false;
    this.currentEmitter = null;
  }

  /** Stop and restart the process */
  async restart(): Promise<void> {
    this.stop();
    await new Promise(r => setTimeout(r, 500));
    this.start();
    // Re-drain any queued messages
    if (this.queue.length > 0 && !this.busy) this.drain();
  }

  /** Auto-restart if within crash limits */
  private maybeRestart(): void {
    const now = Date.now();

    // Reset window if enough time has passed
    if (now - this.restartWindowStart > AgentProcess.RESTART_WINDOW_MS) {
      this.restartCount = 0;
      this.restartWindowStart = now;
    }

    this.restartCount++;

    if (this.restartCount > AgentProcess.MAX_RESTARTS) {
      log.error(`[${this.agentName}] too many restarts (${this.restartCount}) within window - giving up`);
      // Error any remaining queued messages
      for (const msg of this.queue) {
        msg.emitter.emit('event', { type: 'StreamError', message: 'Process crash loop - giving up' });
      }
      this.queue.length = 0;
      return;
    }

    log.info(`[${this.agentName}] auto-restart ${this.restartCount}/${AgentProcess.MAX_RESTARTS} in ${AgentProcess.RESTART_DELAY_MS}ms`);
    setTimeout(() => {
      this.start();
      if (this.queue.length > 0 && !this.busy) this.drain();
    }, AgentProcess.RESTART_DELAY_MS);
  }

  /** Get current session ID (for persistence) */
  getSessionId(): string | null {
    return this.sessionId;
  }

  /** Update system prompt (requires restart) */
  updateSystemPrompt(prompt: string): void {
    this.config.systemPrompt = prompt;
    if (this.isAlive() && !this.busy) {
      this.restart();
    }
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test -- --run src/main/__tests__/agent-process.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/agent-process.ts src/main/__tests__/agent-process.test.ts
git commit -m "feat(inference): implement stop, restart, and crash recovery"
```

---

### Task 6: Create ProcessPool registry

**Files:**
- Create: `src/main/process-pool.ts`
- Test: `src/main/__tests__/process-pool.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// src/main/__tests__/process-pool.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('child_process', () => ({ spawn: vi.fn() }));
vi.mock('../config', () => ({
  getConfig: vi.fn(() => ({
    AGENT_NAME: 'xan',
    CLAUDE_BIN: '/usr/local/bin/claude',
    CLAUDE_MODEL: 'sonnet',
    CLAUDE_EFFORT: 'medium',
    ADAPTIVE_EFFORT: false,
    DISABLED_TOOLS: [],
    DB_PATH: '/tmp/test.db',
  })),
  USER_DATA: '/tmp/test-atrophy',
}));
vi.mock('../logger', () => ({
  createLogger: () => ({
    info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn(),
  }),
}));
vi.mock('../memory', () => ({
  getLastCliSessionId: vi.fn(() => null),
}));
vi.mock('../mcp-registry', () => ({
  mcpRegistry: {
    buildConfigForAgent: vi.fn(() => '/tmp/mcp.json'),
  },
}));
vi.mock('../context', () => ({
  loadSystemPrompt: vi.fn(() => 'system prompt'),
}));

import { processPool } from '../process-pool';

describe('ProcessPool', () => {
  beforeEach(() => {
    processPool.stopAll();
  });

  it('getOrCreate returns an AgentProcess', () => {
    const ap = processPool.getOrCreate('xan');
    expect(ap).toBeDefined();
    expect(ap.agentName).toBe('xan');
  });

  it('getOrCreate returns same instance for same agent', () => {
    const ap1 = processPool.getOrCreate('xan');
    const ap2 = processPool.getOrCreate('xan');
    expect(ap1).toBe(ap2);
  });

  it('get returns undefined for unknown agent', () => {
    expect(processPool.get('nonexistent')).toBeUndefined();
  });

  it('stopAll stops all processes', () => {
    processPool.getOrCreate('xan');
    processPool.getOrCreate('companion');
    processPool.stopAll();
    expect(processPool.get('xan')).toBeUndefined();
    expect(processPool.get('companion')).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test -- --run src/main/__tests__/process-pool.test.ts`
Expected: FAIL - `process-pool` module not found

- [ ] **Step 3: Implement ProcessPool**

```typescript
// src/main/process-pool.ts
/**
 * Registry of persistent AgentProcess instances.
 *
 * One entry per agent. Initialized during boot, cleaned up on shutdown.
 */

import { AgentProcess, type AgentProcessConfig } from './agent-process';
import { getConfig, USER_DATA } from './config';
import { mcpRegistry } from './mcp-registry';
import { loadSystemPrompt } from './context';
import * as memory from './memory';
import * as path from 'path';
import { createLogger } from './logger';

const log = createLogger('process-pool');

class ProcessPool {
  private pool = new Map<string, AgentProcess>();

  /** Get or create a persistent process for an agent */
  getOrCreate(agentName: string): AgentProcess {
    let ap = this.pool.get(agentName);
    if (ap) return ap;

    const config = this.buildConfig(agentName);
    ap = new AgentProcess(config);
    this.pool.set(agentName, ap);
    log.info(`[${agentName}] created agent process`);
    return ap;
  }

  /** Get an existing process (or undefined) */
  get(agentName: string): AgentProcess | undefined {
    return this.pool.get(agentName);
  }

  /** Stop all processes (shutdown hook) */
  stopAll(): void {
    for (const [name, ap] of this.pool) {
      log.info(`[${name}] stopping`);
      ap.stop();
    }
    this.pool.clear();
  }

  /** Restart a specific agent's process */
  async restart(agentName: string): Promise<void> {
    const ap = this.pool.get(agentName);
    if (ap) {
      await ap.restart();
    }
  }

  /** List all active agent names */
  agents(): string[] {
    return Array.from(this.pool.keys());
  }

  /** Build config snapshot for an agent */
  private buildConfig(agentName: string): AgentProcessConfig {
    // Temporarily reload config for this agent to capture its settings
    const cfg = getConfig();
    const prevAgent = cfg.AGENT_NAME;

    if (cfg.AGENT_NAME !== agentName) {
      cfg.reloadForAgent(agentName);
    }

    const config: AgentProcessConfig = {
      agentName,
      claudeBin: cfg.CLAUDE_BIN,
      model: cfg.CLAUDE_MODEL,
      effort: cfg.CLAUDE_EFFORT,
      disabledTools: [...cfg.DISABLED_TOOLS],
      mcpConfigPath: mcpRegistry.buildConfigForAgent(agentName),
      systemPrompt: loadSystemPrompt(),
      sessionId: memory.getLastCliSessionId(),
      cwd: path.join(USER_DATA, 'agents', agentName),
    };

    // Restore previous agent config
    if (cfg.AGENT_NAME !== prevAgent && prevAgent) {
      cfg.reloadForAgent(prevAgent);
    }

    return config;
  }
}

export const processPool = new ProcessPool();
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test -- --run src/main/__tests__/process-pool.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/process-pool.ts src/main/__tests__/process-pool.test.ts
git commit -m "feat(inference): create ProcessPool registry"
```

---

### Task 7: Wire streamInference() to use ProcessPool

**Files:**
- Modify: `src/main/inference.ts`

This is the integration point. The existing `streamInference()` function becomes a thin wrapper that routes interactive channels through the process pool and keeps the spawn-per-message path for ephemeral/cron use.

- [ ] **Step 1: Add ProcessPool import to inference.ts**

At the top of `src/main/inference.ts`, add:

```typescript
import { processPool } from './process-pool';
```

- [ ] **Step 2: Modify streamInference() to delegate to pool for interactive channels**

Replace the spawn logic in `streamInference()` (lines ~595-1007). The function signature stays identical. The key change: if `source` is `desktop`, `telegram`, or `server`, delegate to the agent's persistent process. Otherwise (cron, federation, etc.), use the existing spawn-per-message code.

At the top of the `streamInference` function body (after the existing `const emitter = new EventEmitter();` line), add this routing logic:

```typescript
  // Route interactive channels through persistent process pool.
  // Cron, federation, and other ephemeral sources continue to use one-shot spawn.
  const source = options?.source || 'desktop';
  const isInteractive = source === 'desktop' || source === 'telegram' || source === 'server';

  if (isInteractive) {
    const agentName = options?.processKey?.split(':')[1] || config.AGENT_NAME;
    const ap = processPool.getOrCreate(agentName);

    // Build agency context (still needed for context injection)
    const agencyContext = buildAgencyContext(userMessage, options?.senderName, source);
    const contextPrefix = `[Current context: ${agencyContext}]\n\n`;

    ap.send({
      text: contextPrefix + userMessage,
      source,
      senderName: options?.senderName,
      emitter,
    });

    return emitter;
  }

  // --- Ephemeral spawn path (cron, federation, oneshot) ---
  // Existing code continues below unchanged...
```

- [ ] **Step 3: Update stopInference() to cancel via pool**

Replace the existing `stopInference()` function:

```typescript
/** Stop inference for a specific agent */
export function stopInference(agentName?: string): void {
  const name = agentName || getConfig().AGENT_NAME;

  // Cancel via process pool (interactive channels)
  const ap = processPool.get(name);
  if (ap) {
    ap.cancel();
    return;
  }

  // Fallback: kill by process key (ephemeral processes)
  const desktopKey = `desktop:${name}`;
  const proc = _activeProcesses.get(desktopKey) || _activeProcesses.get(name);
  if (proc) {
    try { proc.kill(); } catch { /* already dead */ }
    _activeProcesses.delete(desktopKey);
    _activeProcesses.delete(name);
    _allProcesses.delete(proc);
  }
}
```

- [ ] **Step 4: Update stopAllInference() to include pool**

```typescript
/** Kill all tracked inference processes (for shutdown). */
export function stopAllInference(): void {
  // Stop persistent processes
  processPool.stopAll();

  // Stop ephemeral processes
  for (const proc of _allProcesses) {
    try { proc.kill(); } catch { /* already dead */ }
  }
  _allProcesses.clear();
  _activeProcesses.clear();
}
```

- [ ] **Step 5: Run all tests**

Run: `pnpm test -- --run`
Expected: All existing tests pass. The change is backwards-compatible because the `EventEmitter` interface is identical.

- [ ] **Step 6: Commit**

```bash
git add src/main/inference.ts
git commit -m "feat(inference): wire streamInference to persistent process pool"
```

---

### Task 8: Initialize pool at boot and wire shutdown

**Files:**
- Modify: `src/main/app.ts`

- [ ] **Step 1: Import processPool in app.ts**

Add to the imports in `src/main/app.ts`:

```typescript
import { processPool } from './process-pool';
```

- [ ] **Step 2: Pre-warm agent processes after wireAgent loop**

In `src/main/app.ts`, after the `wireAgent` loop (around line 806, after `markBootComplete()`), add:

```typescript
    // 2b. Pre-warm persistent inference processes for primary agents.
    // Agents start their CLI process lazily on first message, but we can
    // pre-create the pool entries so config snapshots are captured at boot
    // (before any concurrent dispatch can mutate the config singleton).
    for (const agent of agents) {
      try {
        processPool.getOrCreate(agent.name);
      } catch (e) {
        log.warn(`Failed to create process for "${agent.name}": ${e}`);
      }
    }
    log.info(`Process pool: ${processPool.agents().length} agent(s) ready`);
```

- [ ] **Step 3: Add processPool.stopAll() to shutdown**

In the shutdown function (around line 1262), add before `stopAllInference()`:

```typescript
  processPool.stopAll();
```

Note: `stopAllInference()` also calls `processPool.stopAll()`, so this is belt-and-suspenders. The explicit call in shutdown ensures pool cleanup even if `stopAllInference` is changed later.

- [ ] **Step 4: Run full test suite**

Run: `pnpm test -- --run`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/app.ts
git commit -m "feat(inference): initialize process pool at boot, wire shutdown"
```

---

### Task 9: Remove config reload guard from desktop IPC

**Files:**
- Modify: `src/main/ipc/inference.ts`

The config reload guard we added earlier in this session is no longer needed - the process pool owns per-agent config snapshots.

- [ ] **Step 1: Remove the config reload block**

In `src/main/ipc/inference.ts`, remove this block (added earlier today):

```typescript
      // Ensure the global config singleton is loaded for the desktop agent.
      // Concurrent telegram/cron dispatches reload config for their own agents,
      // which can leave the singleton pointing at the wrong agent by the time
      // the desktop inference fires.
      if (getConfig().AGENT_NAME !== agentName) {
        getConfig().reloadForAgent(agentName);
      }
```

- [ ] **Step 2: Run tests**

Run: `pnpm test -- --run`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/main/ipc/inference.ts
git commit -m "refactor: remove config reload guard (process pool handles isolation)"
```

---

### Task 10: Integration test - build, install, verify

**Files:**
- No file changes - manual verification

- [ ] **Step 1: Build**

```bash
pnpm run pack
```

Expected: Build succeeds with no errors.

- [ ] **Step 2: Install and launch**

```bash
kill $(pgrep -f "Atrophy.app/Contents/MacOS/Atrophy") 2>/dev/null
sleep 2
rm -rf ~/Applications/Atrophy.app
cp -R dist/mac-arm64/Atrophy.app ~/Applications/Atrophy.app
echo "[]" > ~/.atrophy/crash-log.json
open ~/Applications/Atrophy.app
```

- [ ] **Step 3: Verify boot logs**

```bash
tail -30 ~/.atrophy/logs/app.log
```

Expected: See `Process pool: N agent(s) ready` in the boot log. No crash loop.

- [ ] **Step 4: Send a desktop message and verify no error 143/1**

Open the app, send a message to any agent. Verify response streams back normally. Check logs for `[agent-process]` entries showing the persistent process handling the message.

- [ ] **Step 5: Switch agents and verify isolation**

Switch from Xan to Montgomery. Send a message. Verify it uses Montgomery's process (separate from Xan's). Check logs - should see different PIDs for each agent.

- [ ] **Step 6: Verify cron jobs don't interfere**

Wait for a cron job to fire (check_reminders runs every minute). Verify the desktop conversation is unaffected. No error 143.

- [ ] **Step 7: Commit any fixes from integration testing**

```bash
git add -A
git commit -m "fix: integration test fixes for persistent inference"
```

---

## Summary

| Task | Description | New/Modify |
|------|-------------|------------|
| 1 | AgentProcess skeleton | Create |
| 2 | Process spawning + stdin/stdout | Modify |
| 3 | Message queue and drain | Modify |
| 4 | Stdout JSON parsing + event dispatch | Modify |
| 5 | Stop, restart, crash recovery | Modify |
| 6 | ProcessPool registry | Create |
| 7 | Wire streamInference to pool | Modify inference.ts |
| 8 | Boot init + shutdown | Modify app.ts |
| 9 | Remove config reload guard | Modify ipc/inference.ts |
| 10 | Integration test | Manual verification |
