# Streaming Protocol

This specification describes how the companion's streaming inference pipeline works, from subprocess invocation through sentence boundary detection to TTS dispatch.

---

## 1. Subprocess Invocation

Inference is performed by spawning the Claude CLI as a subprocess. Two modes exist:

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
       --allowedTools "mcp__memory__*" \
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
       --allowedTools "mcp__memory__*" \
       -p "[Current context: <agency_context>]\n\n<user_message>"
```

On resume, the tool blacklist is not re-applied (it persists from session creation). The system prompt is not re-sent; instead, the agency context is prepended to the user message.

### Oneshot Inference

For summaries, openings, and daemon tasks, a separate mode is used:

```
claude --model claude-sonnet-4-6 \
       --effort low \
       --no-session-persistence \
       --print \
       --system-prompt <system> \
       -p <prompt>
```

This mode has no MCP tools, no session state, and a 30-second timeout. It returns plain text on stdout.

### Environment Isolation

Before spawning any subprocess, `_env()` strips all `CLAUDE`-prefixed environment variables from the inherited environment. This prevents nested Claude processes from inheriting session state that causes hangs.

---

## 2. MCP Configuration

The MCP config is generated once per process and cached. It defines a single server:

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
    }
  }
}
```

The MCP server runs as a subprocess of the Claude CLI, communicating via JSON-RPC 2.0 over stdio.

---

## 3. Event Stream Format

Events arrive on stdout as newline-delimited JSON objects. Each has a `type` field.

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

The stream generator (`stream_inference()`) processes the raw event stream and yields typed Python dataclass events:

### Internal Event Types

| Event | Fields | Purpose |
|---|---|---|
| `TextDelta` | `text` | Partial text chunk for display |
| `SentenceReady` | `sentence`, `index` | Complete sentence for TTS |
| `ToolUse` | `name`, `tool_id`, `input_json` | Tool invocation notification |
| `Compacting` | (none) | Context window compression detected |
| `StreamDone` | `full_text`, `session_id` | Stream complete |
| `StreamError` | `message` | Error during streaming |

### Text Accumulation

Text deltas are accumulated in two buffers:
- `full_text`: Complete response text (for storage).
- `sentence_buffer`: Working buffer for sentence boundary detection.

### Sentence Boundary Detection

Two-stage boundary detection splits the text stream into speakable chunks:

**Stage 1: Sentence boundaries** (applied on every text delta)

Regex: `(?<=[.!?])\s+|(?<=[.!?])$`

Matches period, question mark, or exclamation mark followed by whitespace or end of string. When the buffer contains multiple parts after splitting, all but the last are emitted as `SentenceReady` events.

**Stage 2: Clause boundaries** (applied when buffer exceeds threshold)

Regex: `(?<=[,;---])\s+`

When the sentence buffer reaches 120+ characters without a sentence boundary, the system splits on clause boundaries (comma, semicolon, em dash, en dash, hyphen followed by whitespace). All but the last clause are emitted as a single `SentenceReady` event.

The 120-character threshold (`_CLAUSE_SPLIT_THRESHOLD`) prevents the TTS queue from stalling on long sentences while avoiding tiny fragment chunks.

### Stream Completion

When the subprocess stdout is exhausted:
1. Wait for process exit (10-second timeout).
2. Read stderr for diagnostics.
3. Check return code; yield `StreamError` on non-zero exit.
4. Check for empty output; yield `StreamError` if no text received.
5. Flush remaining sentence buffer as a final `SentenceReady`.
6. Yield `StreamDone` with full text and session ID.

---

## 5. TTS Pipeline

### Architecture

TTS runs as a parallel async task consuming from a sentence queue:

```
Inference Stream --> SentenceReady events --> tts_queue --> TTS Worker --> Audio Playback
```

### Sentence Queue

An `asyncio.Queue` bridges the inference stream (running in a thread executor) and the TTS worker (running as an async task). Sentences are enqueued in order as `SentenceReady` events arrive.

### TTS Worker

The worker loops:
1. `await tts_queue.get()` -- blocks until a sentence is available.
2. `await synthesise(sentence)` -- sends text to ElevenLabs or Fal API, returns audio file path.
3. `await play(path)` -- plays the audio file.
4. Loop continues until `None` sentinel is received.

Synthesis and playback are sequential per sentence but concurrent with inference. While one sentence plays, the next may already be synthesising.

### Error Handling

TTS errors are silently caught. A synthesis or playback failure does not interrupt the conversation. The text stream continues regardless of audio state.

### Queue Shutdown

After inference completes and follow-up processing finishes, `None` is pushed to the TTS queue. The worker exits after playing any remaining queued sentences. The main loop awaits the worker task to ensure clean shutdown.

---

## 6. Error Handling

### Subprocess Failure

If the Claude CLI process exits with a non-zero return code, a `StreamError` is yielded with the first 300 characters of stderr. The main loop displays the error and continues to the next input prompt.

### No Output

If the process produces no stdout and no text was accumulated, a `StreamError` is yielded. This handles cases where the CLI hangs or crashes silently.

### Process Crash

If an exception occurs during stream processing, the subprocess is killed and a `StreamError` is yielded with the exception message.

### Oneshot Timeout

`run_inference_oneshot` has a 30-second timeout on `proc.communicate()`. On timeout, the process is killed and a `RuntimeError` is raised.

---

## 7. Adaptive Effort

When `ADAPTIVE_EFFORT` is enabled (default: true) and the base `CLAUDE_EFFORT` is `medium`, the system classifies each user message before inference:

- Simple messages (greetings, acknowledgements) get `low` effort.
- Complex messages (multi-part questions, emotional depth) get `high` effort.
- Everything else stays at `medium`.

The effort level is passed to the Claude CLI via the `--effort` flag. If the user has overridden the effort setting to something other than `medium`, adaptive classification is skipped.

---

## 8. Blocking Mode

`run_inference_turn()` wraps the streaming generator for synchronous use. It consumes all events silently and returns `(response_text, session_id)`. Only `StreamDone` and `StreamError` are acted upon. This is used in text-only mode and as a convenience wrapper.

---

## 9. Memory Flush Protocol

When a `Compacting` event is detected during streaming, the system performs a post-turn memory flush:

1. `run_memory_flush()` calls `stream_inference()` with a special flush prompt.
2. The flush prompt instructs the companion to silently use `observe()`, `track_thread()`, `bookmark()`, and `write_note()` to persist anything important.
3. All events are consumed silently except `ToolUse` (logged) and `StreamDone` (session ID tracked).
4. No text is displayed or spoken. The flush is invisible to the user.
5. If the session ID changes during flush, the new ID is persisted.
