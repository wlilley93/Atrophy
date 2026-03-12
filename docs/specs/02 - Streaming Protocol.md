# Streaming Protocol

This specification describes how the companion's streaming inference pipeline works, from subprocess invocation through sentence boundary detection to TTS dispatch. The pipeline is the core communication pathway between the Electron app and the Claude CLI, and understanding it is essential for debugging inference issues, tuning TTS latency, and extending the event handling system.

---

## 1. Subprocess Invocation

Inference is performed by spawning the Claude CLI as a subprocess via `child_process.spawn()` in `src/main/inference.ts`. The module supports two streaming modes and one blocking mode, each suited to different use cases. Streaming inference is used for interactive conversation, while oneshot inference handles background tasks like summaries and daemon processing.

### New Session

When no existing CLI session ID is available, a new session is created with the full set of configuration flags. The following command structure shows every flag and its role in the inference pipeline.

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

Each flag serves a specific purpose in the streaming pipeline:

- `--session-id` receives a `uuidv4()` generated ID for new sessions, establishing a persistent conversation that can be resumed later
- `--system-prompt` receives the system prompt concatenated with `\n\n---\n\n## Current Context\n\n` and the agency context, giving the agent both its core identity and situational awareness
- `--disallowedTools` receives the TOOL_BLACKLIST joined with config.DISABLED_TOOLS (comma-separated), preventing dangerous operations
- `--allowedTools` is always `mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*`, restricting tool access to declared MCP namespaces
- `-p` receives the raw user message without any wrapper

### Resumed Session

When a CLI session ID exists from a previous turn or a previous app session, the conversation is resumed rather than started fresh. The resumed mode differs from new session mode in several important ways.

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

The differences from new session mode reflect the fact that the Claude CLI persists session state internally:

- Uses `--resume` instead of `--session-id` to continue an existing conversation
- The tool blacklist is NOT re-applied because it persists from session creation
- The system prompt is NOT re-sent because the CLI already has it from the initial session
- The agency context is prepended to the user message wrapped in `[Current context: ...]` since there is no system prompt injection point on resume
- `--disallowedTools` is omitted entirely

### Oneshot Inference

For summaries, openings, and daemon tasks, `runInferenceOneshot()` uses a separate blocking mode that returns the complete response as a single string rather than streaming events. This mode is simpler and appropriate for tasks where the response does not need to be displayed incrementally.

```
claude --model <model> \
       --effort <level> \
       --no-session-persistence \
       --print \
       --system-prompt <system> \
       -p <prompt>
```

The oneshot mode has specific constraints and behaviors:

- `model`: defaults to `claude-sonnet-4-6`, validated against an `ALLOWED_MODELS` set containing `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-6`, and `claude-sonnet-4-5-20241022`
- `effort`: defaults to `low`, validated to `low`/`medium`/`high`
- No MCP tools are available, and no session state is persisted
- A 30-second timeout via `setTimeout` kills the process and rejects the Promise if the CLI hangs
- Returns plain text on stdout (no JSON streaming)
- Messages are formatted as `"<RoleLabel>: <content>"` joined by newlines, where the role label is either the user's name or the agent's display name

### Environment Isolation

Before spawning any subprocess, `cleanEnv()` strips all `CLAUDE`-prefixed environment variables from the inherited environment. This is necessary because when running inside Claude Code (which is itself a Claude CLI session), the environment contains variables like `CLAUDE_SESSION_ID` that would cause nested CLI processes to attach to the parent session and hang indefinitely.

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

Both `streamInference()` and `runInferenceOneshot()` use this sanitized environment for all subprocess spawns.

### Spawn Options

The subprocess is spawned with all three stdio streams piped and no detachment. The piped streams allow the main process to read stdout for JSON events, read stderr for error diagnostics, and write to stdin if needed (though stdin is not currently used).

```typescript
spawn(cmd[0], cmd.slice(1), {
  stdio: ['pipe', 'pipe', 'pipe'],
  env: cleanEnv(),
  detached: false,
});
```

The `detached: false` setting ensures the subprocess dies with the parent Electron process. A module-level `_activeProcess` reference is maintained for cancellation via `stopInference()`, which the user can trigger through the `inference:stop` IPC handler.

---

## 2. MCP Configuration

The MCP (Model Context Protocol) config defines which tool servers are available to the Claude CLI during inference. The config is generated once per process by `getMcpConfigPath()`, cached at the module-level `_mcpConfigPath` variable, and written to `mcp/config.json`. This file is passed to the CLI via `--mcp-config` on every inference call.

The config defines multiple servers, each running as a Python subprocess of the Claude CLI and communicating via JSON-RPC 2.0 over stdio.

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

The Google MCP server is conditionally included - it only appears in the config when `config.GOOGLE_CONFIGURED` is true (meaning OAuth tokens exist). Additionally, global MCP servers from `~/.claude/settings.json` are merged in without overriding local servers, allowing the user's Claude Code MCP configuration to extend the companion's tool set.

The config is reset via `resetMcpConfig()` on agent switch, forcing regeneration with the new agent's database path and Obsidian directories.

---

## 3. Tool Blacklist

The `TOOL_BLACKLIST` constant array in `src/main/inference.ts` contains 28 patterns that prevent the companion from invoking dangerous Bash commands through the Claude CLI's built-in Bash tool. These patterns are applied via `--disallowedTools` on session creation (new sessions only, since the blacklist persists across resumed sessions).

The blacklist is organized into three categories, each protecting against a different class of risk.

### Destructive System Commands

These 15 patterns block commands that could damage the system, compromise security, or cause data loss.

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

These 2 patterns prevent the companion from bypassing the MCP server's controlled interface to access SQLite databases directly. All database operations should go through the MCP memory server, which enforces access controls and audit logging.

| Pattern | What it blocks |
|---------|---------------|
| `Bash(sqlite3*memory.db:*)` | Direct SQLite access to memory DB |
| `Bash(sqlite3*companion.db:*)` | Direct SQLite access to companion DB |

### Credential File Access

These 11 patterns prevent the companion from reading sensitive configuration files that contain API keys, tokens, and credentials. Even if prompt injection attempts instruct the agent to read these files, the blacklist prevents execution.

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

Per-agent `DISABLED_TOOLS` from the agent manifest are appended to this list, allowing individual agents to have additional tool restrictions beyond the global blacklist.

---

## 4. Event Stream Format

Events arrive on stdout as newline-delimited JSON objects. Each JSON object has a `type` field that determines how it is processed. The main process reads stdout via a `data` event handler, using a `lineBuffer` to handle incomplete lines that may arrive across chunk boundaries (since TCP/pipe reads do not guarantee line-aligned chunks).

### Line Buffering

The line buffer accumulates partial data until a complete newline-terminated line is available for parsing. The last element of the split array (which may be an incomplete line) is kept in the buffer for the next chunk. This pattern is standard for processing newline-delimited streams from subprocesses.

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

The Claude CLI emits four top-level event types, each serving a different role in the streaming protocol. Events are processed in the order they arrive, and unknown event types are silently ignored to maintain forward compatibility.

| Type | Description |
|------|-------------|
| `system` | System-level events (init, compaction) |
| `stream_event` | Token-level streaming events (text deltas, content blocks) |
| `assistant` | Complete assistant message (backup; contains full content blocks) |
| `result` | Final event with complete response text and session ID |

### System Events

System events signal lifecycle changes in the CLI session. The `init` event fires at the start of every inference call and provides the session ID. This ID may differ from the one passed via `--session-id` if the CLI assigned a different one internally.

```json
{"type": "system", "subtype": "init", "session_id": "uuid-string"}
```

The session ID from the `init` event is captured and used for subsequent interactions. It is the first opportunity the main process has to learn the actual session ID assigned by the CLI.

Compaction events signal that the CLI is about to compress its conversation history because the context window is approaching its limit.

```json
{"type": "system", "subtype": "compact"}
```

Compaction events (subtype containing `compact` or `compress`) trigger the `Compacting` internal event, which the main process uses to schedule a memory flush before the compression discards conversation details.

### Stream Events - Text Delta

Text deltas are the most frequent event type, arriving with each token generated by the model. They have a nested structure where `event.event.type` contains the inner event type.

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

Each text delta is processed through a five-step pipeline that feeds both the display and TTS systems:

1. Extract `text` from `event.event.delta.text`
2. Append to `fullText` accumulator (for the complete response)
3. Append to `sentenceBuffer` (for sentence boundary detection)
4. Emit `TextDelta` event (for live transcript display)
5. Run sentence boundary detection on the buffer (for TTS)

### Stream Events - Tool Use Start

Tool use events arrive when the model begins invoking an MCP tool. They appear as `content_block_start` events with a `tool_use` content block type.

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

Tool use events are processed in three steps:

1. Extract `name` and `id` from `event.event.content_block`
2. Append tool name to the `toolCalls` array for logging and usage tracking
3. Emit `ToolUse` event with `name`, `toolId`, and empty `inputJson` (the input arrives separately in delta events)

### Assistant Event (Backup)

The assistant event contains the complete assistant message with all content blocks. It serves as a backup for tool use detection in case streaming events are missed or arrive out of order.

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

Content blocks of type `tool_use` in the assistant event emit `ToolUse` events with the `input` serialized as JSON. This provides the full tool input that was not available in the streaming `content_block_start` event.

### Result Event

The result event is the final event emitted by the CLI for each inference call. It provides the complete response text and the definitive session ID.

```json
{
  "type": "result",
  "session_id": "uuid-string",
  "result": "full response text"
}
```

The result event serves two purposes. First, its `session_id` field is captured for future `--resume` calls - this is the authoritative session ID that may have changed during compaction. Second, its `result` field provides a fallback for the complete response text in case the streaming `fullText` accumulator is empty (which can happen if text delta events were malformed).

---

## 5. Internal Event Types

The `streamInference()` function processes the raw event stream and emits typed events via a Node.js `EventEmitter`. These internal events provide a clean, typed interface for consumers (the IPC handler in `index.ts`, the memory flush handler, etc.) without exposing the raw JSON structure of the CLI's output.

### TypeScript Definitions

Each event type carries exactly the data its consumers need. The union type `InferenceEvent` allows consumers to switch on the `type` field with full type narrowing.

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

All events are emitted on the `'event'` channel of the `EventEmitter` returned by `streamInference()`. Consumers attach a single listener for all event types and switch on the `type` field.

---

## 6. Sentence Boundary Detection

Sentence boundary detection splits the text stream into speakable chunks for TTS. The system uses a two-stage approach: first it looks for natural sentence endings (periods, question marks, exclamation marks), and if no sentence boundary is found within 120 characters, it falls back to clause boundaries (commas, semicolons, hyphens). This two-stage design balances TTS latency (the user hears speech sooner) against natural-sounding speech (sentences are not cut at awkward points).

### Stage 1: Sentence Boundaries

Stage 1 runs on every text delta, checking whether the sentence buffer contains a complete sentence.

The regex uses a lookbehind to match the position after a period, question mark, or exclamation mark, followed by whitespace or end of string. This ensures the punctuation stays with the sentence rather than being stripped.

```typescript
const SENTENCE_RE = /(?<=[.!?])\s+|(?<=[.!?])$/;
```

When the buffer contains multiple parts after splitting, all but the last are emitted as `SentenceReady` events with incrementing `index` values. The remaining fragment stays in the buffer for the next delta.

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

### Stage 2: Clause Boundaries (Overflow)

Stage 2 activates when the sentence buffer exceeds the threshold without encountering a sentence boundary. This handles cases like long parenthetical clauses, compound sentences joined by commas, or text that uses commas extensively without periods.

The clause regex splits on comma, semicolon, or hyphen followed by whitespace. The threshold of 120 characters was chosen to keep TTS latency reasonable (a 120-character sentence takes roughly 4-5 seconds to speak) while avoiding tiny fragment chunks that sound choppy.

```typescript
const CLAUSE_RE = /(?<=[,;\-])\s+/;
const CLAUSE_SPLIT_THRESHOLD = 120;
```

When the buffer reaches 120 or more characters, the clause split joins all but the last clause into a single `SentenceReady` event. The last clause stays in the buffer in case more text continues the sentence.

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

### Buffer Flush on Completion

When the subprocess closes, any remaining text in the sentence buffer is emitted as a final `SentenceReady` event. This ensures that the last fragment of text (which may not end with punctuation) still reaches the TTS pipeline and the transcript display.

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

Session IDs enable conversation continuity across turns and across app restarts. The ID management involves multiple stages because the CLI may assign or change the session ID at various points during the inference lifecycle.

1. **Initial**: `streamInference()` generates a `uuidv4()` if no `cliSessionId` is provided, establishing a new session identity
2. **Init event**: the `system.init` event may update the session ID from the CLI if it assigned a different one
3. **Result event**: the `result` event provides the final authoritative session ID, which may differ from earlier values if compaction occurred
4. **Persistence**: on `StreamDone`, the main process stores the session ID via `currentSession.setCliSessionId()` for use in the next turn
5. **New sessions**: the session ID is passed via `--session-id` flag
6. **Resumed sessions**: the stored ID is passed via `--resume` flag
7. **ID changes**: if the result event's session ID differs from the current one (e.g. after compaction), the new ID is persisted to maintain continuity

The most important transition is between steps 3 and 4: after compaction, the CLI assigns a new session ID, and if the main process does not capture this change, the next `--resume` call would reference a stale session and fail.

---

## 8. Agency Context Assembly

`buildAgencyContext()` runs on every inference turn and assembles a context block that gives the agent situational awareness. This context is injected into the system prompt for new sessions or prepended to the user message for resumed sessions. The function integrates signals from multiple subsystems to create a holistic picture of the current conversational situation.

### Components (in order)

The context is assembled from 18 components, each contributing a different aspect of situational awareness. Components that return null or empty strings are silently omitted. The ordering is deliberate - foundational context (time, emotional state) comes first, followed by behavioral signals, then standing instructions.

1. **Time of day** - `timeOfDayContext()` from agency.ts, providing register guidance
2. **Inner life** - `formatForContext()` emotional state description with labels and values
3. **Status awareness** - if the user just returned from away, notes what they were doing
4. **Session patterns** - recent session count and timing patterns from the current week
5. **Mood shift** - if detected via `detectMoodShift()`, adds the empathy-first guidance from `moodShiftSystemNote()`
6. **Validation seeking** - if detected, adds the "have a perspective" note from `validationSystemNote()`
7. **Compulsive modelling** - if detected, adds the "one concrete action" note from `modellingInterruptNote()`
8. **Time gap** - `timeGapNote()` based on days since last session
9. **Memory nudge** - standing instruction to surface relevant memories naturally
10. **Obsidian note instructions** - different text depending on `OBSIDIAN_AVAILABLE`, guiding note-taking behavior
11. **Active threads** - up to 5 thread names from `getActiveThreads()`, suggesting relevant topics
12. **Morning digest nudge** - between 5-10 AM, suggests using `daily_digest` tool for orientation
13. **Thread tracking** - standing instruction to use `track_thread` for topic management
14. **Security prompt** - comprehensive prompt injection defense instructions covering all external data sources
15. **Cross-agent awareness** - recent summaries from other agents' databases, enabling contextual references
16. **Energy matching** - `energyNote()` based on user message length
17. **Drift detection** - `detectDrift()` checks recent companion turns for agreeableness patterns
18. **Journal prompting** - if `shouldPromptJournal()` returns true, suggests a writing prompt

### Emotional Signal Detection

Before building context, `detectEmotionalSignals()` scans the user message for patterns that indicate emotional shifts. Detected signals are applied immediately to the emotional model so the current turn's context reflects the detected state change. Trust signals (keys starting with `_trust_`) update specific trust domains via `updateTrust()`, while emotion signals update the emotion dimensions via `updateEmotions()`. This ensures the agent's emotional awareness is current before it generates a response.

---

## 9. Stream Completion and Error Handling

The streaming pipeline handles four completion scenarios: normal completion, subprocess failure, empty output, and spawn errors. Each scenario produces appropriate feedback so the main process and renderer can respond correctly.

### Normal Completion (`close` event, code 0)

When the subprocess exits cleanly, the completion handler performs logging, usage tracking, and event emission in sequence.

1. Clear `_activeProcess` reference so `stopInference()` knows there is nothing to kill
2. Check for non-zero exit code - emit `StreamError` with the first 300 chars of stderr
3. Check for empty output - emit `StreamError` if no text was received from the CLI
4. Flush remaining sentence buffer as a final `SentenceReady` event
5. Log inference statistics: mode (new/resume), character count, sentence count, tools used, elapsed time
6. Log estimated token usage to database: `tokensOut = Math.floor(fullText.length / 4)`, `tokensIn = Math.floor(userMessage.length / 4)` (rough approximation of 4 characters per token)
7. Emit `StreamDone` with full text and session ID

### Subprocess Failure (non-zero exit)

When the CLI exits with a non-zero code, the stderr output provides diagnostic information. The error message is truncated to 300 characters to prevent excessively long error strings from flooding the renderer.

```typescript
if (code && code !== 0) {
  const errMsg = stderrChunks.trim().slice(0, 300) || `claude exited with code ${code}`;
  emitter.emit('event', { type: 'StreamError', message: errMsg });
  return;
}
```

### No Output

If the subprocess exits with code 0 but produced no stdout output, something went wrong with the CLI's processing. This can happen when the CLI encounters an internal error that it does not report via exit code.

```typescript
if (!gotAnyOutput && !fullText) {
  const errMsg = stderrChunks.trim().slice(0, 300) || 'No response from claude';
  emitter.emit('event', { type: 'StreamError', message: errMsg });
  return;
}
```

### Spawn Error

If the subprocess cannot be started at all (e.g. the `claude` binary is not found, resulting in ENOENT), the error is caught and emitted via `setImmediate()`. The `setImmediate` wrapper ensures the error fires after the caller has attached its event listeners, avoiding a race condition where the error would be emitted before anyone is listening.

```typescript
proc.on('error', (err) => {
  _activeProcess = null;
  emitter.emit('event', { type: 'StreamError', message: String(err) });
});
```

### Oneshot Timeout

`runInferenceOneshot()` enforces a 30-second timeout to prevent hung CLI processes from blocking background operations indefinitely. The timeout kills the process and rejects the Promise with a descriptive error.

```typescript
const timeout = setTimeout(() => {
  try { proc.kill(); } catch { /* noop */ }
  reject(new Error('Oneshot inference timed out (30s)'));
}, 30000);
```

### Inference Cancellation

The user can cancel an in-progress inference via the `inference:stop` IPC handler, which calls `stopInference()`. This function kills the active process if one exists. The `try/catch` around `kill()` handles the case where the process has already exited between the check and the kill.

```typescript
export function stopInference(): void {
  if (_activeProcess) {
    try { _activeProcess.kill(); } catch { /* already dead */ }
    _activeProcess = null;
  }
}
```

---

## 10. Adaptive Effort

The adaptive effort system classifies each user message to determine the appropriate inference effort level, allowing simple messages to be processed quickly while complex messages get more thorough treatment. When `ADAPTIVE_EFFORT` is enabled (default: true) and the base `CLAUDE_EFFORT` is `medium`, the system classifies each user message before inference.

```typescript
let effort: EffortLevel = config.CLAUDE_EFFORT as EffortLevel;
if (config.ADAPTIVE_EFFORT && config.CLAUDE_EFFORT === 'medium') {
  const recentTurns = memory.getRecentCompanionTurns();
  effort = classifyEffort(userMessage, recentTurns);
}
```

The classification considers both the current message and recent conversation history to make informed effort decisions:

- Simple messages (greetings, acknowledgements, short affirmations) get `low` effort for fast responses
- Complex messages (multi-part questions, emotional depth, technical analysis requests) get `high` effort for thorough responses
- Everything else stays at `medium` as the default balance

The effort level is passed to the Claude CLI via the `--effort` flag, which controls the model's internal reasoning depth. If the user has overridden the effort setting to something other than `medium` in their config, adaptive classification is skipped entirely and the user's choice is respected. Invalid effort values are clamped to `medium` as a safe default.

---

## 11. TTS Pipeline Integration

The TTS pipeline runs as a parallel async operation in the main process, concurrent with inference. Sentences are synthesized as they become available rather than waiting for the complete response, creating a natural speech experience where the agent begins talking while still generating text.

### Architecture

The pipeline flows from inference through sentence detection to audio synthesis and playback. Each stage operates independently so that slow synthesis does not block inference and slow playback does not block synthesis.

```
Inference Stream --> SentenceReady events --> synthesise() --> enqueueAudio() --> Audio Playback
```

### Sentence Processing (in index.ts)

When a `SentenceReady` event arrives in the `inference:send` IPC handler, it triggers both display and audio processing. The two paths are independent - the display update happens immediately while audio synthesis runs asynchronously.

1. The sentence text is immediately forwarded to the renderer via `inference:sentenceReady` IPC for transcript display
2. If TTS is enabled (`config.TTS_BACKEND !== 'off'`), `synthesise(sentence)` is called asynchronously to generate an audio file
3. The returned audio file path is passed to `enqueueAudio(path, index)` for sequential playback in the order sentences were generated
4. TTS errors are silently caught (`.catch(() => { /* TTS non-critical */ })`) because a TTS failure should not interrupt the conversation

### TTS Playback Callbacks

Three callbacks connect the audio playback system to the renderer's UI state and the wake word detection system. These callbacks ensure the UI stays synchronized with what the user hears and that the wake word detector does not trigger on the agent's own speech.

- `onStarted(index)`: Sends `tts:started` to renderer for playback indicators, pauses wake word detection
- `onDone(index)`: Sends `tts:done` to renderer to update playback state
- `onQueueEmpty()`: Sends `tts:queueEmpty` to renderer, resumes wake word detection since the agent has finished speaking

### Queue Management

The audio queue is cleared on agent switch via `clearAudioQueue()` to prevent the previous agent's speech from playing after the switch. There is no explicit "inference complete, stop TTS" signal - the queue simply runs dry after the last `SentenceReady` event has been synthesized and played. This design avoids race conditions between the inference completion event and the TTS pipeline's processing.

---

## 12. IPC Event Flow

The streaming pipeline bridges the main and renderer processes through a set of typed IPC channels. Each internal event type maps to a specific IPC channel, and each channel targets the Svelte component responsible for displaying that type of information.

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

The renderer subscribes to these events via the preload API's `createListener()` helper, which wraps `ipcRenderer.on()` and returns an unsubscribe function. Components call the unsubscribe function during cleanup to prevent memory leaks from accumulated listeners.

---

## 13. Memory Flush Protocol

When context compaction is detected during inference, `runMemoryFlush()` performs a pre-compaction memory flush. This flush instructs the agent to save important observations, thread updates, and notes before the CLI compresses its conversation history and potentially loses details. The flush is invisible to the user - no text is displayed or spoken.

The function signature accepts the current CLI session ID (so the flush runs within the same conversation context) and the system prompt.

```typescript
export function runMemoryFlush(
  cliSessionId: string,
  system: string,
): Promise<string | null>
```

### Flush Prompt

The flush prompt is a structured instruction that tells the agent to use its memory tools silently. Each numbered step corresponds to a specific MCP tool that preserves different types of information.

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

The flush uses the streaming inference pipeline but handles events differently than a normal conversation turn. Only tool use events are logged, while text and sentence events are silently discarded.

1. Calls `streamInference()` with the existing CLI session ID and flush prompt
2. Only `ToolUse` events are logged to console (with tool name) for debugging visibility
3. `TextDelta`, `SentenceReady`, and `Compacting` are silently ignored since the flush should not produce visible output
4. No text is displayed or spoken - the flush is invisible to the user
5. On `StreamDone`, if the session ID changed (which is likely since compaction triggered the flush), the new ID is returned
6. On `StreamError`, the flush fails silently and returns `null` since a failed flush is non-critical

### Usage Logging

Both `streamInference()` and `runInferenceOneshot()` log estimated token usage to the database after each call. The estimates use a rough approximation of 4 characters per token for both input and output. While not precise, this provides useful tracking of inference costs over time.

- Input tokens: `Math.floor(inputText.length / 4)`
- Output tokens: `Math.floor(outputText.length / 4)`
- Elapsed time in milliseconds
- Tool call count

The usage category is `'conversation'` for streaming inference and `'oneshot'` for blocking calls, allowing the usage tracking UI to distinguish between interactive and background inference costs.
