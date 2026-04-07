# Persistent Inference Architecture

**Date**: 2026-04-07
**Status**: Draft
**Scope**: Replace spawn-per-message inference with persistent per-agent Claude CLI processes

---

## Problem

The current inference architecture spawns a new `claude` CLI subprocess for every single message. Each spawn:

- Boots the CLI runtime (seconds of overhead)
- Cold-starts all MCP servers (7-8 servers per agent)
- Reads session context from disk via `--resume`
- Uses a global config singleton that gets overwritten by concurrent agent dispatches, causing the wrong agent's config to be used (config race bug - the immediate trigger for this redesign)

With 4 primary agents, 54 cron jobs, and messages arriving from desktop, telegram, and HTTP simultaneously, this creates process churn, boot latency, and cross-agent config corruption.

## Solution

One persistent `claude` CLI process per primary agent. Messages from all interactive channels (desktop, telegram, server) queue into the agent's process. The process stays alive between messages with stdin pipe open, stdout continuously parsed for structured JSON events.

Cron jobs continue to spawn ephemeral one-shot processes since they need isolated sessions that don't pollute interactive conversation history.

## Architecture

### New module: `src/main/agent-process.ts`

Owns the lifecycle of one persistent Claude CLI process per agent.

```typescript
interface QueuedMessage {
  text: string;
  source: 'desktop' | 'telegram' | 'server' | 'other';
  senderName?: string;
  emitter: EventEmitter;  // caller listens for events on this
}

class AgentProcess {
  readonly agentName: string;
  private proc: ChildProcess | null = null;
  private sessionId: string | null = null;
  private queue: QueuedMessage[] = [];
  private busy = false;
  private lineBuffer = '';
  private config: AgentProcessConfig;

  // Lifecycle
  start(): void            // Spawn claude CLI with open stdin
  stop(): void             // Graceful SIGTERM, then SIGKILL after 10s
  restart(): Promise<void> // stop + start, requeue current message
  isAlive(): boolean

  // Messaging
  send(msg: QueuedMessage): void   // Queue message, process if idle
  private drain(): void            // Dequeue next message, write to stdin
  private onStdoutLine(line: string): void  // Parse JSON events, dispatch to emitter
}
```

### Process spawn

Each agent process spawns once at boot (during `wireAgent`):

```
claude --output-format stream-json --verbose --dangerously-skip-permissions
       --resume <sessionId>
       --mcp-config ~/.atrophy/mcp/<agent>.config.json
       --model <model>
       --system-prompt <system>
       --allowedTools '*'
       --disallowedTools <blacklist>
```

With `stdio: ['pipe', 'pipe', 'pipe']` - stdin stays open for writing messages.

The `--resume` flag loads prior conversation context on first spawn. Subsequent messages in the same process don't need it - they're part of the same running session.

### Agent-scoped config

Each `AgentProcess` captures its own config snapshot at construction time:

```typescript
interface AgentProcessConfig {
  agentName: string;
  claudeBin: string;
  model: string;
  effort: string;
  adaptiveEffort: boolean;
  disabledTools: string[];
  mcpConfigPath: string;
  systemPrompt: string;
  sessionId: string | null;
  cwd: string;
}
```

This eliminates the config singleton race entirely. Each agent owns its config. No shared mutable state.

### Message flow

```
Desktop/Telegram/Server
        |
        v
  AgentProcess.send(msg)
        |
        v
  Queue (FIFO) ──── busy? wait
        |                |
        v                |
  drain() <──────────────┘
        |
        v
  proc.stdin.write(text + '\n')
        |
        v
  stdout JSON events stream back
        |
        v
  Parse each line as JSON
  Dispatch to msg.emitter
        |
        v
  On 'result' event:
    - Mark busy = false
    - Update sessionId if changed
    - drain() next queued message
```

### Event routing

The existing `EventEmitter` pattern is preserved. Each `QueuedMessage` carries its own emitter. Callers (desktop IPC, telegram daemon, server) listen on their emitter exactly as they do today. The only change is that `streamInference()` delegates to `AgentProcess.send()` instead of spawning a subprocess.

This means the 18 call sites across 11 files don't need to change their event handling - they get the same `EventEmitter` back with the same event types (`TextDelta`, `SentenceReady`, `ToolUse`, `StreamDone`, `StreamError`, etc.).

### Process pool: `src/main/process-pool.ts`

Registry of all active `AgentProcess` instances.

```typescript
const pool = new Map<string, AgentProcess>();

function getOrCreate(agentName: string): AgentProcess
function get(agentName: string): AgentProcess | undefined
function stopAll(): void          // Shutdown hook
function restartAgent(name: string): Promise<void>
```

Initialized during boot in `wireAgent()`. Each agent gets one process. `stopAll()` called during app shutdown.

### Crash recovery

When a process exits unexpectedly:

1. Log the exit code/signal
2. Emit `StreamError` to the current message's emitter (if any)
3. Auto-restart the process after 2s delay
4. Requeue any pending messages (but NOT the failed message - it's already errored)
5. Cap restarts at 5 within 5 minutes to prevent crash loops

### Cron jobs: ephemeral one-shot

Cron job dispatches continue to use the existing spawn-per-message pattern via a dedicated function (renamed from `streamInference` to `streamInferenceOneshot` or similar). They need isolated sessions (`sessionId = null`) and must not interfere with the interactive conversation.

The cron runner dispatches output to the telegram daemon, which then uses `AgentProcess.send()` for delivery messages that need inference (e.g. formatting the cron output for telegram). But the cron script execution itself remains a Python subprocess managed by `channels/cron/runner.ts`.

### Agency context

The `buildAgencyContext()` function currently reads from the config singleton and memory. With per-agent processes, it needs the agent name passed explicitly. The agency context is built fresh for each message and prepended to the user message as `[Current context: ...]`.

### Session ID management

The persistent process tracks its session ID:

1. On first spawn, generate `atrophy-<agent>-<uuid>` and pass via `--session-id`
2. On subsequent spawns (restart), use `--resume <lastSessionId>`
3. When a `result` event includes a `session_id`, update the stored value
4. Persist session ID to the agent's DB so it survives app restarts

### System prompt updates

The system prompt is set once at process spawn. If the system prompt changes (e.g. soul.md updated by evolve job), the process must be restarted to pick up the change. This is acceptable since soul.md changes are rare (monthly).

## What changes

| Component | Change |
|-----------|--------|
| `src/main/agent-process.ts` | **New** - persistent process lifecycle |
| `src/main/process-pool.ts` | **New** - agent process registry |
| `src/main/inference.ts` | `streamInference` delegates to process pool for interactive channels; new `streamInferenceEphemeral` for cron/oneshot |
| `src/main/ipc/inference.ts` | Remove config reload guard (no longer needed) |
| `src/main/channels/telegram/daemon.ts` | Route through process pool instead of direct `streamInference` |
| `src/main/server.ts` | Route through process pool |
| `src/main/app.ts` | Initialize process pool during `wireAgent`, shutdown in cleanup |
| `src/main/config.ts` | No change to singleton, but `AgentProcessConfig` snapshots replace runtime reads |

## What doesn't change

- All 18 call sites keep their `EventEmitter` event handling code unchanged
- Event types (`TextDelta`, `SentenceReady`, `ToolUse`, `StreamDone`, etc.) are identical
- Cron runner, cron scheduler, job implementations - unchanged
- TTS pipeline, artifact parser, sentence detection - unchanged
- Telegram daemon message handling and streaming display - unchanged
- Federation poller - unchanged (already uses its own process key)
- MCP server configs - unchanged (already per-agent)
- Memory, session, context modules - unchanged

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| stdin pipe semantics unclear | Verified: `echo "msg" \| claude --output-format stream-json --verbose` produces full structured JSON |
| Process hangs with stdin open | Inactivity timeout (20 min) kills and restarts; same as current |
| Message interleaving | Sequential queue per agent; only one message in-flight at a time |
| Memory from idle processes | 4 Node processes is negligible; processes can be lazily started if needed later |
| System prompt staleness | Restart process when soul.md/system_prompt.md change (rare, detectable via file watcher) |
| Concurrent config reads eliminated | Each AgentProcess owns a frozen config snapshot; no shared mutable state |

## Success criteria

1. Desktop chat no longer shows "error 143" or "error 1" from config races
2. Second message to same agent responds noticeably faster (no boot overhead)
3. All existing tests pass without modification
4. MCP tools work on first message (servers already warm from process boot)
5. Agent switching still works (desktop switches which AgentProcess to route to)
6. Cron jobs run independently without affecting interactive sessions
