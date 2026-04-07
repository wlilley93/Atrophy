# Tmux-Based Persistent Inference Architecture

**Date**: 2026-04-07
**Status**: Draft

## Problem

The current inference architecture spawns a new `claude` CLI subprocess for every message. Each spawn boots the CLI runtime, cold-starts MCP servers, and loads session context from disk. This adds seconds of latency per message.

The previous attempt (persistent stdin pipe) failed because `claude` with `--output-format stream-json` reads all stdin and exits after one response - it's one-shot by design.

## Solution

Run `claude --resume <id>` in interactive mode inside hidden tmux windows - one per agent. Send messages via `tmux send-keys`. Read responses from Claude Code's JSONL session files (the same mechanism ccbot uses). Detect completion by polling the JSONL for finalized entries and checking the terminal for spinner absence.

This eliminates boot overhead, keeps MCP servers warm, and provides structured response data from the JSONL files - no terminal output parsing needed.

## How ccbot does it (proven pattern)

ccbot at `/Users/williamlilley/Projects/Claude/ccbot/` uses this exact approach:

- **Spawn**: `pane.send_keys("claude --resume <id>")` in a tmux window
- **Send**: `pane.send_keys(text)`, wait 500ms, then `send_keys("Enter")` separately (prevents TUI misinterpretation)
- **Read**: `SessionMonitor` polls `~/.claude/projects/<hash>/claude_sessions_<id>.jsonl` with byte-offset tracking
- **Complete**: JSONL entries are finalized (appear only when committed). Spinner detection via `tmux capture-pane` as a fallback.

## Architecture

### New module: `src/main/tmux-inference.ts`

Manages one tmux window per primary agent within a single `atrophy` tmux session.

```typescript
interface TmuxAgent {
  agentName: string;
  windowId: string;           // tmux window identifier
  sessionId: string;          // claude CLI session UUID
  jsonlPath: string | null;   // path to JSONL session file (discovered after boot)
  byteOffset: number;         // read position in JSONL
  busy: boolean;
  queue: QueuedMessage[];
}
```

### Tmux session management

All agent windows live under one tmux session named `atrophy`. The session is created at app boot if it doesn't exist. Each agent gets its own window.

```
tmux session: "atrophy"
  window 0: xan           (claude --resume <id> --mcp-config xan.config.json)
  window 1: companion     (claude --resume <id> --mcp-config companion.config.json)
  window 2: general_montgomery (claude --resume <id> --mcp-config ...)
  window 3: mirror        (claude --resume <id> --mcp-config ...)
```

Windows are hidden - no terminal UI shown to the user. The Electron app manages them programmatically via `child_process.execFileSync('tmux', [...args])`.

### Launching an agent

```
tmux new-window -t atrophy -n <agentName>
tmux send-keys -t atrophy:<agentName> \
  "claude --resume <sessionId> --dangerously-skip-permissions --mcp-config <mcpConfigPath>" \
  Enter
```

Wait for claude to boot (poll terminal for the input prompt or absence of spinner). Then the agent is ready for messages.

### Sending a message

```typescript
send(text: string, source: string, senderName?: string): EventEmitter {
  // Queue if busy
  if (this.busy) { this.queue.push({text, source, senderName, emitter}); return emitter; }
  this.busy = true;

  // Record current JSONL byte offset (to read only new entries)
  this.byteOffset = getFileSize(this.jsonlPath);

  // Send via tmux (with 500ms gap before Enter, matching ccbot pattern)
  // Uses execFileSync to avoid shell injection
  execFileSync('tmux', ['send-keys', '-t', `atrophy:${this.agentName}`, text, '']);
  setTimeout(() => {
    execFileSync('tmux', ['send-keys', '-t', `atrophy:${this.agentName}`, 'Enter']);
  }, 500);

  // Start polling JSONL for response
  this.pollForResponse(emitter);
  return emitter;
}
```

### Reading responses from JSONL

Claude Code writes session data to `~/.claude/projects/<hash>/claude_sessions_<sessionId>.jsonl`. Each line is a JSON object representing a conversation event.

The polling loop:
1. Read new bytes from JSONL file (from `byteOffset` to end)
2. Parse each new line as JSON
3. Map JSONL entry types to Atrophy event types:
   - `assistant` message with text content -> `TextDelta` events + sentence detection
   - `tool_use` content blocks -> `ToolUse` events
   - `tool_result` entries -> `ToolResult` events
   - Final `assistant` message (when spinner disappears) -> `StreamDone`
4. Update `byteOffset` to current file position
5. Repeat every 200ms until completion detected

### Completion detection

Two signals, checked in combination:
1. **JSONL**: a finalized assistant message appears (entries in JSONL are committed, not streaming)
2. **Terminal**: no spinner character in the status line (capture-pane checked for spinner chars: `*`, `+`, etc.)

When both signals agree (JSONL has final response AND terminal shows idle), the message is complete.

### JSONL file discovery

The JSONL path depends on the project hash and session ID. On first boot:
1. Start claude in the tmux window
2. Read `~/.claude/projects/` to find the project directory (based on cwd hash)
3. Find `claude_sessions_<sessionId>.jsonl` in that directory
4. Cache the path for subsequent messages

Alternatively, use the existing SessionStart hook that writes session ID mappings.

### Event mapping

| JSONL entry | Atrophy event |
|-------------|---------------|
| `assistant` message with text content | `TextDelta` (diff from previous) + `SentenceReady` |
| `assistant` message with `tool_use` blocks | `ToolUse` |
| `tool_result` entries | `ToolResult` |
| Final assistant text when idle detected | `StreamDone` |
| Process exit / error | `StreamError` |

### Sentence detection

Same regex logic as current inference.ts:
- `SENTENCE_RE = /(?<=[.!?])\s+|(?<=[.!?])$/`
- `CLAUSE_RE = /(?<=[,; -])\s+/` with 120-char threshold
- Applied to each new text delta extracted from JSONL diffs

### Message queue

Sequential per agent - only one message in-flight at a time. Subsequent messages queue and drain when the current one completes.

### Streaming granularity

JSONL entries are finalized (not streaming). This means we get the full assistant response once, not token-by-token deltas. For TTS:

Start with full-response mode: wait for complete response, split into sentences, play sequentially. The speed gain from eliminating boot overhead far outweighs the loss of token-level streaming.

Future optimization: poll terminal content (`tmux capture-pane`) for partial text while waiting for JSONL finalization to enable streaming TTS.

### Crash recovery

If a tmux window dies:
1. Detect via `tmux list-windows` (window disappears)
2. Error the current message's emitter
3. Recreate the window with `--resume <sessionId>`
4. Drain queued messages

### Integration with existing code

The existing `streamInference()` function routes interactive channels (desktop, telegram, server) through the tmux pool instead of spawning. Ephemeral channels (cron, federation) continue to use one-shot spawn.

```typescript
// In streamInference():
if (isInteractive) {
  const agent = tmuxPool.getOrCreate(agentName);
  return agent.send(contextPrefix + userMessage, source, senderName);
}
// ... existing spawn code for ephemeral channels
```

### What changes

| File | Change |
|------|--------|
| `src/main/tmux-inference.ts` | **New** - TmuxAgent class, tmux session management, JSONL polling |
| `src/main/inference.ts` | Route interactive channels through tmux pool |
| `src/main/app.ts` | Initialize tmux session at boot, cleanup on shutdown |

### What doesn't change

- All 18 call sites keep their EventEmitter event handling
- Event types (TextDelta, SentenceReady, ToolUse, StreamDone, etc.) identical
- Cron runner, scheduler, job implementations
- TTS pipeline, artifact parser
- Telegram daemon message handling
- MCP server configs (passed via --mcp-config flag)

### Only primary agents get tmux windows

Only agents with `desktop.enabled: true` or `telegram.enabled: true` in their manifest get tmux windows. Background-only agents (ambassadors, research fellows) don't need persistent sessions - their work is cron-driven (ephemeral).

### Risks and mitigations

| Risk | Mitigation |
|------|------------|
| tmux not installed | Check at boot, fall back to spawn-per-message |
| JSONL path discovery fails | Fall back to spawn-per-message |
| JSONL entries not granular enough for TTS | Start with full-response TTS, optimize later with capture-pane polling |
| Terminal send-keys timing | Use ccbot's proven 500ms gap pattern |
| Multiple agents sending simultaneously | Each agent has its own tmux window - fully isolated |
| Config singleton race | Each agent's config is baked into the tmux launch command (--mcp-config), not read from singleton at inference time |

### Success criteria

1. Second message to same agent responds with no boot overhead (< 1s to first text vs current 3-5s)
2. MCP tools work immediately (servers stayed warm from boot)
3. Desktop chat, telegram, and server all route through the same persistent session per agent
4. Cron jobs remain isolated (ephemeral spawn)
5. All existing tests pass
6. Agent switching works (routes to different tmux window)
