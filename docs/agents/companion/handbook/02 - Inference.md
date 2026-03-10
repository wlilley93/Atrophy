# Chapter 8: Inference and Streaming

## The Streaming Architecture

The Companion does not wait for complete responses. It streams token-by-token, synthesising speech as sentences arrive. This chapter examines how.

---

## Why Streaming?

### The Alternative

Batch inference waits for complete response:
1. Send prompt
2. Wait for complete response
3. Process response
4. Synthesise entire response to speech
5. Play audio

Latency: 5-10 seconds for inference + 5-10 seconds for TTS = 10-20 seconds to first word.

### Streaming

Streaming processes incrementally:
1. Send prompt
2. Receive tokens as they arrive (~50ms per token)
3. Detect sentence boundaries
4. Synthesise speech per sentence (~1-2 seconds)
5. Play audio in parallel with continued inference

Latency: 2-5 seconds to first token + 1-2 seconds for first TTS = 3-7 seconds to first word.

The difference: streaming feels like conversation. Batch feels like waiting.

---

## The Stream Pipeline

### Event Types

The streaming pipeline uses typed events:

```python
@dataclass
class TextDelta:
    """Partial text chunk from the stream."""
    text: str

@dataclass
class SentenceReady:
    """A complete sentence is ready for TTS."""
    sentence: str
    index: int

@dataclass
class ToolUse:
    """Claude is invoking a tool."""
    name: str
    tool_id: str
    input_json: str

@dataclass
class StreamDone:
    """Stream finished. Contains full response and session ID."""
    full_text: str
    session_id: str

@dataclass
class StreamError:
    """Error during streaming."""
    message: str

@dataclass
class Compacting:
    """Context window is being compacted."""
    pass
```

Each event type triggers different handling.

### The Stream Generator

```python
def stream_inference(user_message: str, system: str, cli_session_id: str | None = None):
    # Build command
    cmd = [...]
    
    # Start subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, ...)
    
    full_text = ""
    sentence_buffer = ""
    sentence_index = 0
    
    for line in proc.stdout:
        event = json.loads(line)
        evt_type = event.get("type", "")
        
        if evt_type == "stream_event":
            inner = event.get("event", {})
            inner_type = inner.get("type", "")
            
            if inner_type == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta":
                    chunk = delta.get("text", "")
                    full_text += chunk
                    sentence_buffer += chunk
                    yield TextDelta(text=chunk)
                    
                    # Check for sentence boundaries
                    parts = _SENTENCE_RE.split(sentence_buffer)
                    while len(parts) > 1:
                        sentence = parts.pop(0).strip()
                        if sentence:
                            yield SentenceReady(sentence=sentence, index=sentence_index)
                            sentence_index += 1
                        sentence_buffer = " ".join(parts)
    
    yield StreamDone(full_text=full_text, session_id=session_id)
```

The generator yields events as they arrive. The consumer handles them in real-time.

---

## Sentence Boundary Detection

### The Regex

```python
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')
```

This matches:
- `(?<=[.!?])\s+` — Period/question/exclamation followed by whitespace (positive lookbehind)
- `(?<=[.!?])$` — Period/question/exclamation at end of string

The lookbehind ensures the punctuation is included in the split but not consumed.

### The Algorithm

```python
sentence_buffer += chunk
parts = _SENTENCE_RE.split(sentence_buffer)

while len(parts) > 1:
    sentence = parts.pop(0).strip()
    if sentence:
        yield SentenceReady(sentence=sentence, index=sentence_index)
        sentence_index += 1
    sentence_buffer = " ".join(parts)
```

Example:
- Buffer: "Hello. How are"
- Split: ["Hello", " ", "How are"]
- Yield: "Hello"
- Buffer: "How are"

Next chunk:
- Buffer: "How are you?"
- Split: ["How are you", ""]
- Yield: "How are you?"
- Buffer: ""

### Clause Splitting

For long sentences, clause boundaries are used:

```python
if len(sentence_buffer) >= _CLAUSE_SPLIT_THRESHOLD:  # 120 chars
    cparts = _CLAUSE_RE.split(sentence_buffer)
    if len(cparts) > 1:
        to_emit = " ".join(cparts[:-1]).strip()
        if to_emit:
            yield SentenceReady(sentence=to_emit, index=sentence_index)
            sentence_index += 1
        sentence_buffer = cparts[-1]
```

This prevents long sentences from delaying TTS excessively.

---

## Parallel TTS

### The TTS Queue

```python
tts_queue: asyncio.Queue = asyncio.Queue()

async def _tts_worker():
    while True:
        sentence = await tts_queue.get()
        if sentence is None:
            break
        try:
            path = await synthesise(sentence)
            await play(path)
        except Exception as e:
            pass  # TTS errors don't interrupt conversation

tts_task = asyncio.create_task(_tts_worker())
```

The TTS worker runs in parallel. It processes sentences as they arrive.

### The Main Loop

```python
while True:
    event = await queue.get()
    if event is None:
        break
    
    if isinstance(event, TextDelta):
        print(event.text, end="", flush=True)
    
    elif isinstance(event, SentenceReady):
        await tts_queue.put(event.sentence)
    
    elif isinstance(event, ToolUse):
        loop.run_in_executor(None, memory.log_tool_call, ...)
    
    elif isinstance(event, StreamDone):
        full_text = event.full_text
        session_id = event.session_id

# Signal TTS to finish
await tts_queue.put(None)
await tts_task
```

The main loop handles events. TTS runs in parallel. The result: speech begins before inference completes.

---

## Session Persistence

### The Resume Mechanism

Claude Code supports session persistence via `--resume`:

```python
if cli_session_id:
    cmd = [
        CLAUDE_BIN,
        "--resume", cli_session_id,
        ...
    ]
else:
    cli_session_id = str(uuid.uuid4())
    cmd = [
        CLAUDE_BIN,
        "--session-id", cli_session_id,
        ...
    ]
```

This maintains conversation continuity across Companion restarts.

### Session ID Tracking

```python
def set_cli_session_id(self, cli_id: str):
    self.cli_session_id = cli_id
    memory.save_cli_session_id(self.session_id, cli_id)
```

The CLI session ID is tracked in the database. It survives restarts.

### Context Continuity

When resuming:
1. Last CLI session ID retrieved from database
2. Claude Code invoked with `--resume`
3. Conversation continues from where it left off
4. Memory context injected for additional continuity

The result: seamless continuation across sessions.

---

## Error Handling

### Subprocess Errors

```python
try:
    proc = subprocess.Popen(cmd, ...)
except Exception as e:
    yield StreamError(message=str(e))
    return
```

Subprocess failures are caught and reported.

### Parse Errors

```python
try:
    event = json.loads(line)
except json.JSONDecodeError:
    continue
```

Invalid JSON is skipped. This handles malformed output.

### Exit Code Checks

```python
proc.wait(timeout=10)

if proc.returncode and proc.returncode != 0:
    err_msg = stderr_text.strip()[:300] if stderr_text else f"claude exited with code {proc.returncode}"
    yield StreamError(message=err_msg)
    return
```

Non-zero exit codes are reported as errors.

### Timeout Handling

```python
try:
    stdout, stderr = proc.communicate(timeout=30)
except subprocess.TimeoutExpired:
    proc.kill()
    raise RuntimeError("Oneshot inference timed out (30s)")
```

One-shot inference has a 30-second timeout. This prevents hangs.

---

## Performance Optimization

### Thread Workers

The stream generator runs in a thread:

```python
def _stream_worker():
    for event in stream_inference(...):
        loop.call_soon_threadsafe(queue.put_nowait, event)
    loop.call_soon_threadsafe(queue.put_nowait, None)

loop.run_in_executor(None, _stream_worker)
```

This prevents blocking the async event loop.

### Threadsafe Callbacks

```python
loop.call_soon_threadsafe(queue.put_nowait, event)
```

Events from threads are queued threadsafely.

### Non-blocking Memory

```python
loop.run_in_executor(
    None, memory.log_tool_call,
    session.session_id, event.name, event.input_json,
)
```

Memory writes are non-blocking. They do not delay the conversation.

---

## Reading This Chapter

The streaming architecture is what makes the Companion feel alive. It does not wait. It speaks as it thinks.

Understanding this helps you understand the Companion's rhythm. It is not batch processing. It is conversation.

---

## Questions for Reflection

1. Streaming vs. batch — what are the trade-offs? When might batch be preferable?

2. Sentence boundary detection — how robust is it? What edge cases might fail?

3. Parallel TTS — what are the synchronization challenges? How are they handled?

4. Session persistence — why is this important? What does it enable?

5. Error handling — what failure modes are covered? What might be missing?

---

## Further Reading

- [[02_Core|Chapter 7: The Core Module]] — Core module overview
- [[04_Voice|Chapter 16: Voice Architecture]] — Voice pipeline details
- [[02_Session|Chapter 9: Session Lifecycle]] — Session management
- [[08_Performance|Chapter 40: Performance Considerations]] — Performance optimization

---

*Streaming feels like conversation. Batch feels like waiting.*
