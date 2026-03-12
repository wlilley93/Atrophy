# Streaming Protocol

This specification describes how the companion's streaming inference pipeline works, from subprocess invocation through sentence boundary detection to TTS dispatch.

---

## 1. Subprocess Invocation

Inference is performed by spawning the Claude CLI as a subprocess via `child_process.spawn()` in `src/main/inference.ts`. Two streaming modes and one blocking mode exist.

### New Session

```
claude --model claude-haiku-4-5-20251001 \
       --effort <level> \
       --verbose \
       --output-format stream-json \
       --include-partial-messages \
       --session-id <uuid> \
       --system-prompt <system + context> \
       --mcp-config <config.json> \
       --allowedTools "mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*" \
       --disallowedTools <blacklist> \
       -p <user_message>
```

Key details:
- `--session-id` receives a `uuidv4()` generated ID for new sessions
- `--system-prompt` receives the system prompt concatenated with `\n\n---\n\n## Current Context\n\n` and the agency context
- `--disallowedTools` receives the TOOL_BLACKLIST joined with config.DISABLED_TOOLS (comma-separated)
- `--allowedTools` is always `mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*`
- `-p` receives the raw user message

### Resumed Session

```
claude --model claude-haiku-4-5-20251001 \
       --effort <level> \
       --verbose \
       --output-format stream-json \
       --include-partial-messages \
       --resume <session_id> \
       --mcp-config <config.json> \
       --allowedTools "mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*" \
       -p "[Current context: <agency_context>]\n\n<user_message>"
```

On resume:
- Uses `--resume` instead of `--session-id`
- The tool blacklist is NOT re-applied (it persists from session creation)
- The system prompt is NOT re-sent
- The agency context is prepended to the user message wrapped in `[Current context: ...]`
- `--disallowedTools` is omitted

### Oneshot Inference

For summaries, openings, and daemon tasks, `runInferenceOneshot()` uses a separate mode:

```
claude --model <model> \
       --effort <level> \
       --no-session-persistence \
       --print \
       --system-prompt <system> \
       -p <prompt>
```

Parameters:
- `model`: defaults to `claude-sonnet-4-6`, validated against `ALLOWED_MODELS` set: `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-sonnet-4-5-20241022`
- `effort`: defaults to `low`, validated to `low`/`medium`/`high`
- No MCP tools, no session state
- 30-second timeout via `setTimeout` - kills the process and rejects the Promise
- Returns plain text on stdout (no JSON streaming)
- Messages are formatted as `"<RoleLabel>: <content>"` joined by newlines

### Environment Isolation

Before spawning any subprocess, `cleanEnv()` strips all `CLAUDE`-prefixed environment variables from the inherited environment:

```typescript
function cleanEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (key.toUpperCase().includes('CLAUDE')) {
      delete env[key];
    }
  }
  return env;
}
```

This prevents nested Claude processes from inheriting session state that causes hangs. Both `streamInference()` and `runInferenceOneshot()` use this.

### Spawn Options

```typescript
spawn(cmd[0], cmd.slice(1), {
  stdio: ['pipe', 'pipe', 'pipe'],
  env: cleanEnv(),
  detached: false,
});
```

All three stdio streams are piped. The process is not detached (dies with the parent). A module-level `_activeProcess` reference is maintained for cancellation.

---

## 2. MCP Configuration

The MCP config is generated once per process by `getMcpConfigPath()` and cached at `_mcpConfigPath`. It is written to `mcp/config.json` and defines multiple servers:

```json
{
  "mcpServers": {
    "memory": {
      "command": "<python_executable>",
      "args": ["<path_to_memory_server.py>"],
      "env": {
        "COMPANION_DB": "<path_to_memory.db>",
        "OBSIDIAN_VAULT": "<vault_path>",
        "OBSIDIAN_AGENT_DIR": "<agent_dir>",
        "OBSIDIAN_AGENT_NOTES": "<notes_dir>",
        "AGENT": "<agent_name>"
      }
    },
    "puppeteer": {
      "command": "<python_executable>",
      "args": ["<path_to_puppeteer_proxy.py>"],
      "env": {
        "PUPPETEER_LAUNCH_OPTIONS": "{\"headless\": true}"
      }
    },
    "google": {
      "command": "<python_executable>",
      "args": ["<path_to_google_server.py>"]
    }
  }
}
```

The Google MCP server is only included when `config.GOOGLE_CONFIGURED` is true. Additionally, global MCP servers from `~/.claude/settings.json` are merged in (without overriding local servers). The config is reset via `resetMcpConfig()` on agent switch.

The MCP servers run as subprocesses of the Claude CLI, communicating via JSON-RPC 2.0 over stdio.

---

## 3. Tool Blacklist

The `TOOL_BLACKLIST` constant array contains 23 patterns that prevent the companion from invoking dangerous Bash commands. Applied via `--disallowedTools` on session creation (new sessions only).

### Destructive System Commands

| Pattern | What it blocks |
|---------|---------------|
| `Bash(rm -rf:*)` | Recursive deletion |
| `Bash(sudo:*)` | Privilege escalation |
| `Bash(shutdown:*)` | System shutdown |
| `Bash(reboot:*)` | System reboot |
| `Bash(halt:*)` | System halt |
| `Bash(dd:*)` | Raw disk operations |
| `Bash(mkfs:*)` | Filesystem creation |
| `Bash(nmap:*)` | Network scanning |
| `Bash(masscan:*)` | Mass network scanning |
| `Bash(chmod 777:*)` | Insecure permissions |
| `Bash(curl*\|*sh:*)` | Pipe-to-shell via curl |
| `Bash(wget*\|*sh:*)` | Pipe-to-shell via wget |
| `Bash(git push --force:*)` | Force push |
| `Bash(kill -9:*)` | Forced process kill |
| `Bash(chflags:*)` | macOS file flag manipulation |

### Database Direct Access

| Pattern | What it blocks |
|---------|---------------|
| `Bash(sqlite3*memory.db:*)` | Direct SQLite access to memory DB |
| `Bash(sqlite3*companion.db:*)` | Direct SQLite access to companion DB |

### Credential File Access

| Pattern | What it blocks |
|---------|---------------|
| `Bash(cat*.env:*)` | Reading .env files |
| `Bash(head*.env:*)` | Reading .env files |
| `Bash(tail*.env:*)` | Reading .env files |
| `Bash(less*.env:*)` | Reading .env files |
| `Bash(more*.env:*)` | Reading .env files |
| `Bash(grep*.env:*)` | Searching .env files |
| `Bash(cat*config.json:*)` | Reading config |
| `Bash(cat*server_token:*)` | Reading API token |
| `Bash(cat*token.json:*)` | Reading OAuth tokens |
| `Bash(cat*credentials.json:*)` | Reading credentials |
| `Bash(cat*.google*:*)` | Reading Google auth files |

Per-agent `DISABLED_TOOLS` from the agent manifest are appended to this list.

---

## 4. Event Stream Format

Events arrive on stdout as newline-delimited JSON objects. Each has a `type` field. The main process reads stdout via a `data` event handler, using a `lineBuffer` to handle incomplete lines across chunks.

### Line Buffering

```typescript
let lineBuffer = '';
proc.stdout?.on('data', (chunk: Buffer) => {
  lineBuffer += chunk.toString();
  const lines = lineBuffer.split('\n');
  lineBuffer = lines.pop() || '';  // Keep incomplete line in buffer
  for (const rawLine of lines) { ... }
});
```

### Event Types

| Type | Description |
|------|-------------|
| `system` | System-level events (init, compaction) |
| `stream_event` | Token-level streaming events (text deltas, content blocks) |
| `assistant` | Complete assistant message (backup; contains full content blocks) |
| `result` | Final event with complete response text and session ID |

### System Events

```json
{"type": "system", "subtype": "init", "session_id": "uuid-string"}
```

The `init` event provides the session ID. The session ID is captured and used for subsequent interactions.

```json
{"type": "system", "subtype": "compact"}
```

Compaction events (subtype containing `compact` or `compress`) trigger the `Compacting` internal event.

### Stream Events - Text Delta

Nested structure: `event.event.type` contains the inner event type.

```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_delta",
    "delta": {
      "type": "text_delta",
      "text": "chunk of text"
    }
  }
}
```

Processing:
1. Extract `text` from `event.event.delta.text`
2. Append to `fullText` accumulator
3. Append to `sentenceBuffer`
4. Emit `TextDelta` event
5. Run sentence boundary detection on the buffer

### Stream Events - Tool Use Start

```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_start",
    "content_block": {
      "type": "tool_use",
      "name": "remember",
      "id": "toolu_abc123"
    }
  }
}
```

Processing:
1. Extract `name` and `id` from `event.event.content_block`
2. Append tool name to `toolCalls` array (for logging)
3. Emit `ToolUse` event with `name`, `toolId`, and empty `inputJson`

### Assistant Event (Backup)

```json
{
  "type": "assistant",
  "message": {
    "content": [
      {"type": "tool_use", "name": "observe", "id": "toolu_xyz", "input": {"content": "..."}}
    ]
  }
}
```

The assistant event serves as a backup for tool use detection. Content blocks of type `tool_use` emit `ToolUse` events with the `input` serialized as JSON.

### Result Event

```json
{
  "type": "result",
  "session_id": "uuid-string",
  "result": "full response text"
}
```

The result event is the final event. It provides:
- `session_id`: the CLI session ID (captured for future `--resume`)
- `result`: the complete response text (used as fallback if `fullText` is empty from streaming)

---

## 5. Internal Event Types

The `streamInference()` function processes the raw event stream and emits typed events via a Node.js `EventEmitter`:

### TypeScript Definitions

```typescript
interface TextDeltaEvent {
  type: 'TextDelta';
  text: string;                    // partial text chunk
}

interface SentenceReadyEvent {
  type: 'SentenceReady';
  sentence: string;                // complete sentence for TTS
  index: number;                   // sequential sentence index (0-based)
}

interface ToolUseEvent {
  type: 'ToolUse';
  name: string;                    // tool name (e.g. 'remember', 'observe')
  toolId: string;                  // unique tool invocation ID
  inputJson: string;               // JSON string of tool input (or empty)
}

interface StreamDoneEvent {
  type: 'StreamDone';
  fullText: string;                // complete response text
  sessionId: string;               // CLI session ID for resumption
}

interface StreamErrorEvent {
  type: 'StreamError';
  message: string;                 // error description (first 300 chars of stderr)
}

interface CompactingEvent {
  type: 'Compacting';              // no fields
}

type InferenceEvent =
  | TextDeltaEvent
  | SentenceReadyEvent
  | ToolUseEvent
  | StreamDoneEvent
  | StreamErrorEvent
  | CompactingEvent;
```

All events are emitted on the `'event'` channel of the `EventEmitter` returned by `streamInference()`.

---

## 6. Sentence Boundary Detection

Two-stage boundary detection splits the text stream into speakable chunks for TTS.

### Stage 1: Sentence Boundaries

Applied on every text delta.

**Regex**: `(?<=[.!?])\s+|(?<=[.!?])$`

```typescript
const SENTENCE_RE = /(?<=[.!?])\s+|(?<=[.!?])$/;
```

This uses a lookbehind to match the position after a period, question mark, or exclamation mark, followed by whitespace or end of string.

**Processing**:
```typescript
let parts = sentenceBuffer.split(SENTENCE_RE);
while (parts.length > 1) {
  const sentence = parts.shift()!.trim();
  if (sentence) {
    emitter.emit('event', {
      type: 'SentenceReady',
      sentence,
      index: sentenceIndex,
    });
    sentenceIndex++;
  }
  sentenceBuffer = parts.join(' ');
}
```

When the buffer contains multiple parts after splitting, all but the last are emitted as `SentenceReady` events with incrementing `index` values. The remaining fragment stays in the buffer.

### Stage 2: Clause Boundaries (Overflow)

Applied when the sentence buffer exceeds the threshold without a sentence boundary.

**Regex**: `(?<=[,;\-])\s+`

```typescript
const CLAUSE_RE = /(?<=[,;\-])\s+/;
const CLAUSE_SPLIT_THRESHOLD = 120;
```

**Processing**:
```typescript
if (sentenceBuffer.length >= CLAUSE_SPLIT_THRESHOLD) {
  const cparts = sentenceBuffer.split(CLAUSE_RE);
  if (cparts.length > 1) {
    const toEmit = cparts.slice(0, -1).join(' ').trim();
    if (toEmit) {
      emitter.emit('event', {
        type: 'SentenceReady',
        sentence: toEmit,
        index: sentenceIndex,
      });
      sentenceIndex++;
    }
    sentenceBuffer = cparts[cparts.length - 1];
  }
}
```

When the buffer reaches 120+ characters, splits on comma, semicolon, or hyphen followed by whitespace. All but the last clause are joined and emitted as a single `SentenceReady` event.

The 120-character threshold prevents the TTS queue from stalling on long sentences while avoiding tiny fragment chunks.

### Buffer Flush on Completion

When the subprocess closes, any remaining text in the sentence buffer is emitted as a final `SentenceReady`:

```typescript
const remainder = sentenceBuffer.trim();
if (remainder) {
  emitter.emit('event', {
    type: 'SentenceReady',
    sentence: remainder,
    index: sentenceIndex,
  });
}
```

---

## 7. Session ID Management

Session IDs are managed through multiple stages:

1. **Initial**: `streamInference()` generates a `uuidv4()` if no `cliSessionId` is provided
2. **Init event**: the `system.init` event updates the session ID from the CLI
3. **Result event**: the `result` event provides the final session ID
4. **Persistence**: on `StreamDone`, the main process stores the session ID via `currentSession.setCliSessionId()`
5. **New sessions**: the session ID is passed via `--session-id` flag
6. **Resumed sessions**: the stored ID is passed via `--resume` flag
7. **ID changes**: if the result event's session ID differs from the current one (e.g. after compaction), the new ID is persisted

---

## 8. Agency Context Assembly

`buildAgencyContext()` runs on every inference turn and assembles a context block injected into the system prompt (new sessions) or user message (resumed sessions).

### Components (in order)

1. **Time of day** - `timeOfDayContext()` from agency.ts
2. **Inner life** - `formatForContext()` emotional state description
3. **Status awareness** - if the user just returned from away, notes what they were doing
4. **Session patterns** - recent session count and timing patterns from the current week
5. **Mood shift** - if detected via `detectMoodShift()`, adds `moodShiftSystemNote()`
6. **Validation seeking** - if detected, adds `validationSystemNote()`
7. **Compulsive modelling** - if detected, adds `modellingInterruptNote()`
8. **Time gap** - `timeGapNote()` based on time since last session
9. **Memory nudge** - standing instruction to surface relevant memories
10. **Obsidian note instructions** - different text depending on `OBSIDIAN_AVAILABLE`
11. **Active threads** - up to 5 thread names from `getActiveThreads()`
12. **Morning digest nudge** - between 5-10 AM, suggests using `daily_digest`
13. **Thread tracking** - standing instruction to use `track_thread`
14. **Security prompt** - comprehensive prompt injection defence instructions
15. **Cross-agent awareness** - recent summaries from other agents' databases
16. **Energy matching** - `energyNote()` based on user message energy
17. **Drift detection** - `detectDrift()` checks recent companion turns for patterns
18. **Journal prompting** - if `shouldPromptJournal()` returns true, suggests prompting

### Emotional Signal Detection

Before building context, `detectEmotionalSignals()` scans the user message. Detected signals are applied:
- Trust signals (keys starting with `_trust_`) update the trust model via `updateTrust()`
- Emotion signals update the emotional state via `updateEmotions()`

---

## 9. Stream Completion and Error Handling

### Normal Completion (`close` event, code 0)

1. Clear `_activeProcess` reference
2. Check for non-zero exit code - emit `StreamError` with first 300 chars of stderr
3. Check for empty output - emit `StreamError` if no text received
4. Flush remaining sentence buffer as final `SentenceReady`
5. Log inference statistics: mode (new/resume), char count, sentence count, tools used, elapsed time
6. Log estimated token usage to database: `tokensOut = Math.floor(fullText.length / 4)`, `tokensIn = Math.floor(userMessage.length / 4)`
7. Emit `StreamDone` with full text and session ID

### Subprocess Failure (non-zero exit)

```typescript
if (code && code !== 0) {
  const errMsg = stderrChunks.trim().slice(0, 300) || `claude exited with code ${code}`;
  emitter.emit('event', { type: 'StreamError', message: errMsg });
  return;
}
```

### No Output

```typescript
if (!gotAnyOutput && !fullText) {
  const errMsg = stderrChunks.trim().slice(0, 300) || 'No response from claude';
  emitter.emit('event', { type: 'StreamError', message: errMsg });
  return;
}
```

### Spawn Error

```typescript
proc.on('error', (err) => {
  _activeProcess = null;
  emitter.emit('event', { type: 'StreamError', message: String(err) });
});
```

If the spawn itself fails (e.g. ENOENT - binary not found), the error is caught and a `StreamError` is emitted via `setImmediate()` to ensure it fires after the caller has attached listeners.

### Oneshot Timeout

`runInferenceOneshot()` has a 30-second timeout:
```typescript
const timeout = setTimeout(() => {
  try { proc.kill(); } catch { /* noop */ }
  reject(new Error('Oneshot inference timed out (30s)'));
}, 30000);
```

### Inference Cancellation

```typescript
export function stopInference(): void {
  if (_activeProcess) {
    try { _activeProcess.kill(); } catch { /* already dead */ }
    _activeProcess = null;
  }
}
```

Called via the `inference:stop` IPC handler when the user cancels.

---

## 10. Adaptive Effort

When `ADAPTIVE_EFFORT` is enabled (default: true) and the base `CLAUDE_EFFORT` is `medium`, the system classifies each user message before inference:

```typescript
let effort: EffortLevel = config.CLAUDE_EFFORT as EffortLevel;
if (config.ADAPTIVE_EFFORT && config.CLAUDE_EFFORT === 'medium') {
  const recentTurns = memory.getRecentCompanionTurns();
  effort = classifyEffort(userMessage, recentTurns);
}
```

- Simple messages (greetings, acknowledgements) get `low` effort
- Complex messages (multi-part questions, emotional depth) get `high` effort
- Everything else stays at `medium`

The effort level is passed to the Claude CLI via the `--effort` flag. If the user has overridden the effort setting to something other than `medium`, adaptive classification is skipped. Invalid effort values are clamped to `medium`.

---

## 11. TTS Pipeline Integration

### Architecture

TTS runs as a parallel async operation in the main process, concurrent with inference:

```
Inference Stream --> SentenceReady events --> synthesise() --> enqueueAudio() --> Audio Playback
```

### Sentence Processing (in index.ts)

When a `SentenceReady` event arrives in the `inference:send` IPC handler:
1. The sentence text is immediately forwarded to the renderer via `inference:sentenceReady` IPC for display
2. If TTS is enabled (`config.TTS_BACKEND !== 'off'`), `synthesise(sentence)` is called asynchronously
3. The returned audio file path is passed to `enqueueAudio(path, index)` for sequential playback
4. TTS errors are silently caught (`.catch(() => { /* TTS non-critical */ })`)

### TTS Playback Callbacks

Three callbacks wire TTS events to IPC and wake word management:
- `onStarted(index)`: Sends `tts:started` to renderer, pauses wake word detection
- `onDone(index)`: Sends `tts:done` to renderer
- `onQueueEmpty()`: Sends `tts:queueEmpty` to renderer, resumes wake word detection

### Queue Management

The audio queue is cleared on agent switch via `clearAudioQueue()`. There is no explicit "inference complete, stop TTS" signal - the queue simply runs dry after the last `SentenceReady` event has been synthesised and played.

---

## 12. IPC Event Flow

The streaming pipeline bridges the main and renderer processes:

```
Main Process                          Renderer Process
-----------                          ----------------
streamInference() EventEmitter
  |
  +-- TextDelta -----------> ipcMain -----> inference:textDelta -----> Transcript.svelte
  +-- SentenceReady -------> ipcMain -----> inference:sentenceReady -> Transcript.svelte
  +-- ToolUse -------------> ipcMain -----> inference:toolUse -------> ThinkingIndicator.svelte
  +-- Compacting ----------> ipcMain -----> inference:compacting ----> Window.svelte
  +-- StreamDone ----------> ipcMain -----> inference:done ----------> Window.svelte
  +-- StreamError ----------> ipcMain -----> inference:error ---------> Window.svelte
```

The renderer subscribes to these events via the preload API's `createListener()` helper, which wraps `ipcRenderer.on()` and returns an unsubscribe function.

---

## 13. Memory Flush Protocol

When context compaction is anticipated, `runMemoryFlush()` performs a pre-compaction memory flush:

```typescript
export function runMemoryFlush(
  cliSessionId: string,
  system: string,
): Promise<string | null>
```

### Flush Prompt

```
[MEMORY FLUSH - context is being compacted. Before details are lost,
silently use your memory tools:
1. observe() - any patterns or insights from recent conversation you haven't recorded
2. track_thread() - update any active threads with latest context
3. bookmark() - mark any significant moments
4. write_note() - anything worth preserving in Obsidian
Work silently. Do not produce spoken output. Just use your tools.]
```

### Behavior

1. Calls `streamInference()` with the existing CLI session ID and flush prompt
2. Only `ToolUse` events are logged to console (with tool name)
3. `TextDelta`, `SentenceReady`, and `Compacting` are silently ignored
4. No text is displayed or spoken - the flush is invisible to the user
5. On `StreamDone`, if the session ID changed, the new ID is returned
6. On `StreamError`, the flush fails silently and returns `null`

### Usage Logging

Both `streamInference()` and `runInferenceOneshot()` log estimated token usage to the database:
- Input tokens: `Math.floor(inputText.length / 4)`
- Output tokens: `Math.floor(outputText.length / 4)`
- Elapsed time in milliseconds
- Tool call count

The usage category is `'conversation'` for streaming inference and `'oneshot'` for blocking calls.
