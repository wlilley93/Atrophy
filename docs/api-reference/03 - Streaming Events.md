# Streaming Events Reference

The inference layer (`core/inference.py`) wraps the Claude CLI as a subprocess and exposes a streaming event protocol. Events flow from the Claude process through the inference generator, into TTS sentence splitting, and out to the display layer.

---

## Architecture

```
Claude CLI subprocess
  --output-format stream-json
  --include-partial-messages
        |
        v
  stream_inference() generator
    Parses JSON lines from stdout
    Splits text into sentences
    Yields typed event dataclasses
        |
        v
  Consumer (GUI main loop / blocking wrapper)
    TextDelta   -> display buffer
    SentenceReady -> TTS queue
    ToolUse     -> tool use indicator
    Compacting  -> compaction indicator
    StreamDone  -> finalize session
    StreamError -> error handling
```

---

## Inference Modes

### stream_inference()

Generator that yields streaming events. Used by the GUI.

```python
def stream_inference(
    user_message: str,
    system: str,
    cli_session_id: str | None = None,
) -> Generator[TextDelta | SentenceReady | ToolUse | StreamDone | StreamError | Compacting, None, None]
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_message` | str | The user's input message |
| `system` | str | System prompt text |
| `cli_session_id` | str or None | Existing CLI session ID for `--resume`. If None, a new UUID is generated and `--session-id` is used. |

**New session command:**
```
claude --model claude-haiku-4-5-20251001 --effort {effort}
       --verbose --output-format stream-json --include-partial-messages
       --session-id {uuid} --system-prompt {system + agency context}
       --mcp-config {config} --allowedTools mcp__memory__*
       --disallowedTools {blacklist} -p {message}
```

**Resume session command:**
```
claude --model claude-haiku-4-5-20251001 --effort {effort}
       --verbose --output-format stream-json --include-partial-messages
       --resume {session_id} --mcp-config {config}
       --allowedTools mcp__memory__* -p [{agency context}]\n\n{message}
```

### run_inference_turn()

Blocking convenience wrapper. Consumes all events from `stream_inference()` and returns the final result.

```python
def run_inference_turn(
    user_message: str,
    system: str,
    cli_session_id: str | None = None,
) -> tuple[str, str]  # (response_text, session_id)
```

Raises `RuntimeError` on `StreamError`.

### run_inference_oneshot()

One-shot inference for background tasks (summaries, classifications). Does not use MCP tools or session persistence.

```python
def run_inference_oneshot(
    messages: list[dict],
    system: str,
    model: str = "claude-sonnet-4-6",
    effort: str = "low",
) -> str
```

Messages are formatted as `"User: {content}"` / `"Companion: {content}"` lines. Times out after 30 seconds.

### run_memory_flush()

Fires a silent inference turn before context compaction, prompting the companion to use its memory tools (observe, track_thread, bookmark, write_note) to preserve important context. Consumes all events silently except `ToolUse` (logged) and `StreamError`.

```python
def run_memory_flush(
    cli_session_id: str,
    system: str,
) -> str | None  # new session_id if changed, else None
```

---

## Event Types

All events are Python dataclasses defined in `core/inference.py`.

### TextDelta

A partial text chunk from the stream. Emitted for every `content_block_delta` with `text_delta` type.

| Field | Type | Description |
|-------|------|-------------|
| `text` | str | The text fragment |

These arrive at token granularity. The full response is assembled by concatenating all `TextDelta.text` values.

### SentenceReady

A complete sentence (or clause) is ready for TTS. Emitted when the sentence splitter detects a boundary in the accumulated text buffer.

| Field | Type | Description |
|-------|------|-------------|
| `sentence` | str | The complete sentence text |
| `index` | int | Zero-based sentence index within the current response |

This is the primary event consumed by the TTS pipeline. Each `SentenceReady` is dispatched to voice synthesis independently, allowing speech to begin before the full response is complete.

### ToolUse

Claude is invoking an MCP tool. Emitted at two points:

1. **On `content_block_start`** -- when the tool invocation begins (input_json is empty at this point)
2. **On `assistant` message** -- backup emission with full input JSON

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Tool name (e.g. `mcp__memory__remember`) |
| `tool_id` | str | Unique tool call ID |
| `input_json` | str | JSON-serialized input arguments (empty string on block start) |

### StreamDone

Stream finished successfully. Contains the full assembled response and the session ID.

| Field | Type | Description |
|-------|------|-------------|
| `full_text` | str | Complete response text |
| `session_id` | str | CLI session ID (for `--resume` on next turn) |

### StreamError

An error occurred during streaming. The subprocess may have failed, timed out, or produced no output.

| Field | Type | Description |
|-------|------|-------------|
| `message` | str | Error description (stderr output truncated to 300 chars, or a diagnostic message) |

### Compacting

Context window is being compacted by Claude. Emitted when a `system` event with `compact` or `compress` in its subtype is received.

No fields. This is a signal event only.

---

## Inline Artifact Extraction

On `StreamDone`, the main process passes the full response through `parseArtifacts()` from `src/main/artifact-parser.ts`. This extracts any `<artifact>` XML blocks emitted by the agent and replaces them with `[[artifact:id]]` placeholders.

### Artifact Format

```xml
<artifact id="unique-id" type="html|svg|code" title="Title" language="html">
CONTENT
</artifact>
```

### IPC: `inference:artifact`

Emitted once per extracted artifact before `inference:done`. The renderer stores these in the `artifacts` reactive store.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique artifact identifier |
| `type` | string | Content type: `html`, `svg`, or `code` |
| `title` | string | Human-readable title |
| `language` | string | Content language |
| `content` | string | The artifact content (trimmed) |

### Renderer Buffering

The renderer's `InputBar.svelte` buffers `TextDelta` events to detect and suppress partial `<artifact>` tags during streaming. When a `<artifact` opening is detected in the buffer, text is held until the closing `</artifact>` tag arrives (at which point the block is discarded since the main process handles extraction on `StreamDone`). This prevents raw XML from appearing in the transcript.

---

## Sentence Splitting Algorithm

The inference layer splits streaming text into sentence-sized chunks for TTS, using a two-tier strategy:

### Tier 1: Sentence Boundaries

**Pattern:** `(?<=[.!?])\s+|(?<=[.!?])$`

Splits on sentence-ending punctuation (`.`, `!`, `?`) followed by whitespace or end of string. As text arrives token by token, the buffer is checked against this pattern after every `TextDelta`. When the pattern produces multiple parts, all but the last are emitted as `SentenceReady` events. The last part remains in the buffer (it may be an incomplete sentence).

### Tier 2: Clause Boundaries (overflow protection)

**Pattern:** `(?<=[,;—–\-])\s+`

**Threshold:** 120 characters

If the sentence buffer exceeds 120 characters without hitting a sentence boundary, the system splits on clause-level punctuation (`,`, `;`, em dash, en dash, hyphen) followed by whitespace. All parts except the last are joined and emitted as a single `SentenceReady`. This prevents long run-on sentences from delaying TTS output.

### Flush

When the stream ends (after `proc.wait()`), any remaining text in the sentence buffer is emitted as a final `SentenceReady` event.

---

## Claude CLI JSON Line Format

Each line from the subprocess stdout is a JSON object. The inference layer handles these `type` values:

### `system`

System-level events from the CLI.

```json
{
  "type": "system",
  "subtype": "init",
  "session_id": "abc-123"
}
```

- `subtype: "init"` -- session initialized, captures `session_id`
- Subtypes containing `compact` or `compress` -- triggers `Compacting` event

### `stream_event`

Token-level streaming events, nested under an `event` key.

**Text delta:**
```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_delta",
    "delta": {
      "type": "text_delta",
      "text": "Hello"
    }
  }
}
```

**Tool use start:**
```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_start",
    "content_block": {
      "type": "tool_use",
      "name": "mcp__memory__remember",
      "id": "tool_abc123"
    }
  }
}
```

### `assistant`

Complete assistant message (backup). Contains full content blocks including any tool use calls with their complete input JSON.

```json
{
  "type": "assistant",
  "message": {
    "content": [
      {
        "type": "text",
        "text": "Full response text..."
      },
      {
        "type": "tool_use",
        "name": "mcp__memory__observe",
        "id": "tool_xyz",
        "input": {"content": "He seems lighter today"}
      }
    ]
  }
}
```

### `result`

Final event in the stream. Contains the session ID and optionally the complete result text.

```json
{
  "type": "result",
  "session_id": "abc-123",
  "result": "Complete response text..."
}
```

The `result` field is used as a fallback if no `TextDelta` events produced text (i.e., `full_text` is empty at stream end).

---

## Adaptive Effort

If `ADAPTIVE_EFFORT` is enabled in config and `CLAUDE_EFFORT` is set to `medium`, the system classifies the user's message complexity via `core.thinking.classify_effort()` before inference. The classified effort level (`low`, `medium`, `high`) is passed to the `--effort` CLI flag. If adaptive effort is disabled or effort is locked to a specific level, that level is used directly.

---

## Tool Blacklist

The following tool patterns are blocked via `--disallowedTools` on new sessions (not applied on resume):

| Pattern | Reason |
|---------|--------|
| `Bash(rm -rf:*)` | Destructive file deletion |
| `Bash(sudo:*)` | Privilege escalation |
| `Bash(shutdown:*)` | System shutdown |
| `Bash(reboot:*)` | System reboot |
| `Bash(halt:*)` | System halt |
| `Bash(dd:*)` | Raw disk operations |
| `Bash(mkfs:*)` | Filesystem creation |
| `Bash(nmap:*)` | Network scanning |
| `Bash(masscan:*)` | Network scanning |
| `Bash(chmod 777:*)` | Unsafe permissions |
| `Bash(curl*\|*sh:*)` | Remote code execution |
| `Bash(wget*\|*sh:*)` | Remote code execution |
| `Bash(git push --force:*)` | Destructive git operation |
| `Bash(kill -9:*)` | Force kill processes |
| `Bash(chflags:*)` | File flag modification |
| `Bash(sqlite3*memory.db:*)` | Direct database access |
| `Bash(sqlite3*companion.db:*)` | Direct database access |

---

## Environment Isolation

The subprocess environment is sanitized by stripping all environment variables containing `CLAUDE` in their name (case-insensitive). This prevents nested Claude CLI processes from hanging due to inherited Claude Code environment state. The sanitization happens in `_env()`.
