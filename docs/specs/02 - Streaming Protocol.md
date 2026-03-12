# Streaming Protocol

This specification describes how the companion's streaming inference pipeline works, from subprocess invocation through sentence boundary detection to TTS dispatch.

---

## 1. Subprocess Invocation

Inference is performed by spawning the Claude CLI as a subprocess via `child_process.spawn()` in `src/main/inference.ts`. Two modes exist:

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

On resume, the tool blacklist is not re-applied (it persists from session creation). The system prompt is not re-sent; instead, the agency context is prepended to the user message.

### Oneshot Inference

For summaries, openings, and daemon tasks, `runInferenceOneshot()` uses a separate mode:

```
claude --model claude-sonnet-4-6 \
       --effort low \
       --no-session-persistence \
       --print \
       --system-prompt <system> \
       -p <prompt>
```

This mode has no MCP tools, no session state, and a 30-second timeout. It returns plain text on stdout. The function wraps the subprocess in a `Promise<string>` that resolves with the trimmed stdout or rejects on error/timeout.

### Environment Isolation

Before spawning any subprocess, `cleanEnv()` strips all `CLAUDE`-prefixed environment variables from the inherited environment. This prevents nested Claude processes from inheriting session state that causes hangs:

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

## 3. Event Stream Format

Events arrive on stdout as newline-delimited JSON objects. Each has a `type` field. The main process reads stdout via a `data` event handler, buffering incomplete lines.

### Event Types

| Type | Description |
|---|---|
| `system` | System-level events (init, compaction) |
| `stream_event` | Token-level streaming events (text deltas, content blocks) |
| `assistant` | Complete assistant message (backup; contains full content blocks) |
| `result` | Final event with complete response text and session ID |

### System Events

```json
{"type": "system", "subtype": "init", "session_id": "..."}
{"type": "system", "subtype": "compact"}
```

The `init` event provides the session ID. Compaction events (subtype containing `compact` or `compress`) trigger the `Compacting` internal event.

### Stream Events

Nested structure: `event.event.type` contains the inner event type.

**Text delta**:
```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_delta",
    "delta": {
      "type": "text_delta",
      "text": "chunk"
    }
  }
}
```

**Tool use start**:
```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_start",
    "content_block": {
      "type": "tool_use",
      "name": "remember",
      "id": "tool_id"
    }
  }
}
```

### Result Event

```json
{
  "type": "result",
  "session_id": "...",
  "result": "full response text"
}
```

---

## 4. Event Processing Pipeline

The `streamInference()` function processes the raw event stream and emits typed events via a Node.js `EventEmitter`:

### Internal Event Types

| Event | Fields | Purpose |
|---|---|---|
| `TextDelta` | `text: string` | Partial text chunk for display |
| `SentenceReady` | `sentence: string`, `index: number` | Complete sentence for TTS |
| `ToolUse` | `name: string`, `toolId: string`, `inputJson: string` | Tool invocation notification |
| `Compacting` | (none) | Context window compression detected |
| `StreamDone` | `fullText: string`, `sessionId: string` | Stream complete |
| `StreamError` | `message: string` | Error during streaming |

These are defined as TypeScript interfaces with a discriminated union type:

```typescript
export type InferenceEvent =
  | TextDeltaEvent
  | SentenceReadyEvent
  | ToolUseEvent
  | StreamDoneEvent
  | StreamErrorEvent
  | CompactingEvent;
```

All events are emitted on the `'event'` channel of the `EventEmitter` returned by `streamInference()`.

### Text Accumulation

Text deltas are accumulated in two buffers:
- `fullText`: Complete response text (for storage and final emit).
- `sentenceBuffer`: Working buffer for sentence boundary detection.

### Sentence Boundary Detection

Two-stage boundary detection splits the text stream into speakable chunks:

**Stage 1: Sentence boundaries** (applied on every text delta)

Regex: `(?<=[.!?])\s+|(?<=[.!?])$`

Matches period, question mark, or exclamation mark followed by whitespace or end of string. When the buffer contains multiple parts after splitting, all but the last are emitted as `SentenceReady` events with incrementing `index` values.

**Stage 2: Clause boundaries** (applied when buffer exceeds threshold)

Regex: `(?<=[,;\-])\s+`

When the sentence buffer reaches 120+ characters (`CLAUSE_SPLIT_THRESHOLD`) without a sentence boundary, the system splits on clause boundaries (comma, semicolon, hyphen followed by whitespace). All but the last clause are joined and emitted as a single `SentenceReady` event.

The 120-character threshold prevents the TTS queue from stalling on long sentences while avoiding tiny fragment chunks.

### Stream Completion

When the subprocess closes (via the `close` event on `ChildProcess`):
1. Check return code; emit `StreamError` on non-zero exit with the first 300 characters of stderr.
2. Check for empty output; emit `StreamError` if no text received and no stdout was seen.
3. Flush remaining sentence buffer as a final `SentenceReady`.
4. Log inference statistics (char count, sentence count, tools used, elapsed time).
5. Log estimated token usage to the database.
6. Emit `StreamDone` with full text and session ID.

---

## 5. TTS Pipeline

### Architecture

TTS runs as a parallel async operation in the main process, concurrent with inference:

```
Inference Stream --> SentenceReady events --> synthesise() --> enqueueAudio() --> Audio Playback
```

### Sentence Processing

When a `SentenceReady` event arrives in the `inference:send` IPC handler:
1. The sentence text is immediately forwarded to the renderer via `inference:sentenceReady` IPC for display.
2. If TTS is enabled (`config.TTS_BACKEND !== 'off'`), `synthesise(sentence)` is called asynchronously.
3. The returned audio file path is passed to `enqueueAudio(path, index)` for sequential playback.

### TTS Playback Callbacks

Three callbacks wire TTS events to IPC and wake word management:
- `onStarted(index)`: Sends `tts:started` to renderer, pauses wake word detection.
- `onDone(index)`: Sends `tts:done` to renderer.
- `onQueueEmpty()`: Sends `tts:queueEmpty` to renderer, resumes wake word detection.

### Error Handling

TTS errors are silently caught (`.catch(() => { /* TTS non-critical */ })`). A synthesis or playback failure does not interrupt the conversation. The text stream continues regardless of audio state.

### Queue Management

The audio queue is cleared on agent switch via `clearAudioQueue()`. This prevents stale audio from a previous agent playing after a switch.

### TTS Queue Shutdown

The Electron TTS queue does not use a sentinel-based shutdown like the Python version (which pushes `None` to an `asyncio.Queue` to signal the worker to exit). Instead, the playback queue drains naturally:

1. `SentenceReady` events call `synthesise()` asynchronously and pass resulting audio paths to `enqueueAudio()`.
2. `processQueue()` loops while items remain, playing each sequentially via `afplay`.
3. When the queue empties, `_onQueueEmpty()` fires, which sends `tts:queueEmpty` to the renderer and resumes wake word detection.
4. If new sentences arrive while the queue is draining, they are appended and played in order.
5. On inference cancellation (`stopInference()`), the subprocess is killed but the TTS queue is not explicitly flushed - any already-synthesised audio will finish playing. On agent switch, `clearAudioQueue()` discards all pending items.
6. Temp audio files are cleaned up after each playback via `fs.unlinkSync()` in the `playAudio()` close handler.

There is no explicit "inference complete, stop TTS" signal. The queue simply runs dry after the last `SentenceReady` event has been synthesised and played.

---

## 6. IPC Event Flow

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

## 7. Error Handling

### Subprocess Failure

If the Claude CLI process exits with a non-zero return code, a `StreamError` is emitted with the first 300 characters of stderr. The renderer displays the error and the user can send another message.

### No Output

If the process produces no stdout and no text was accumulated, a `StreamError` is emitted. This handles cases where the CLI hangs or crashes silently.

### Process Crash

If the `error` event fires on the `ChildProcess` (spawn failure, ENOENT, etc.), a `StreamError` is emitted with the error message. The `_activeProcess` reference is cleared.

### Oneshot Timeout

`runInferenceOneshot()` has a 30-second timeout via `setTimeout`. On timeout, the process is killed and the Promise rejects with `Error('Oneshot inference timed out (30s)')`.

### Inference Cancellation

`stopInference()` kills the active subprocess if one exists. Called via the `inference:stop` IPC handler when the user cancels a request.

---

## 8. Adaptive Effort

When `ADAPTIVE_EFFORT` is enabled (default: true) and the base `CLAUDE_EFFORT` is `medium`, the system classifies each user message before inference:

- Simple messages (greetings, acknowledgements) get `low` effort.
- Complex messages (multi-part questions, emotional depth) get `high` effort.
- Everything else stays at `medium`.

The effort level is passed to the Claude CLI via the `--effort` flag. If the user has overridden the effort setting to something other than `medium`, adaptive classification is skipped. Invalid effort values are clamped to `medium`.

---

## 9. Blocking Mode

The Python version has `run_inference_turn()`, which wraps the streaming generator for synchronous use - it consumes all events silently and returns `(response_text, session_id)`. This is used in text-only mode and as a convenience wrapper.

The Electron version does not have a direct equivalent, because there is no text-only mode. Instead, `runInferenceOneshot()` serves the blocking use case. It spawns the Claude CLI with `--no-session-persistence --print`, collects stdout into a string, and returns a `Promise<string>` that resolves with the trimmed output. It has no MCP tools, no session state, and a 30-second timeout. This is used for summaries, background jobs (observer, heartbeat, sleep-cycle, etc.), and the setup wizard.

For cases where background jobs need streaming inference with tool access (e.g. heartbeat.ts evaluating whether to reach out), they use `streamInference()` directly and consume events via the `EventEmitter`, similar to how the GUI does it but without forwarding events to the renderer.

---

## 10. Memory Flush Protocol

When a `Compacting` event is detected during streaming, the system performs a post-turn memory flush via `runMemoryFlush()` in `src/main/inference.ts`:

1. `runMemoryFlush()` calls `streamInference()` with the existing CLI session ID and a special flush prompt.
2. The flush prompt instructs the companion to silently use `observe()`, `track_thread()`, `bookmark()`, and `write_note()` to persist anything important before context is compressed.
3. All events are consumed via the `EventEmitter`. Only `ToolUse` events are logged to console. `TextDelta`, `SentenceReady`, and `Compacting` are silently ignored.
4. No text is displayed or spoken. The flush is invisible to the user.
5. On `StreamDone`, if the session ID changed during flush, the new ID is returned to the caller for persistence.
6. On `StreamError`, the flush fails silently and returns `null`.
