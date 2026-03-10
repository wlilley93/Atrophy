"""Claude Code subprocess wrapper for inference.

Uses `claude` with `--output-format stream-json` for streaming responses.
Routes through Max subscription (no API cost). Maintains persistent CLI
sessions via `--resume`.

Two modes:
  run_inference_turn()    — blocking, returns full response (for CLI mode)
  stream_inference()      — generator, yields events as they arrive (for GUI)
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

from config import CLAUDE_BIN, CLAUDE_EFFORT, DB_PATH, MCP_SERVER_SCRIPT, OBSIDIAN_VAULT
from core.agency import (
    time_of_day_context, detect_mood_shift, mood_shift_system_note,
    session_pattern_note, detect_validation_seeking, validation_system_note,
    detect_compulsive_modelling, modelling_interrupt_note,
    time_gap_note, detect_drift, energy_note,
    should_prompt_journal,
)

# Tools the companion must never use
_TOOL_BLACKLIST = [
    "Bash(rm -rf:*)",
    "Bash(sudo:*)",
    "Bash(shutdown:*)",
    "Bash(reboot:*)",
    "Bash(halt:*)",
    "Bash(dd:*)",
    "Bash(mkfs:*)",
    "Bash(nmap:*)",
    "Bash(masscan:*)",
    "Bash(chmod 777:*)",
    "Bash(curl*|*sh:*)",
    "Bash(wget*|*sh:*)",
    "Bash(git push --force:*)",
    "Bash(kill -9:*)",
    "Bash(chflags:*)",
    "Bash(sqlite3*companion:*)",
    "Bash(sqlite3*companion.db:*)",
]

# Sentence boundary: period/question/exclamation followed by space or end
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')
# Clause boundary: comma/semicolon/dash followed by space (used after char threshold)
_CLAUSE_RE = re.compile(r'(?<=[,;—–\-])\s+')
# Min chars before we'll split on a clause boundary (avoids tiny chunks)
_CLAUSE_SPLIT_THRESHOLD = 120


def _env():
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


_mcp_config: str | None = None

def _mcp_config_path() -> str:
    """Write MCP config once, return cached path on subsequent calls."""
    global _mcp_config
    if _mcp_config:
        return _mcp_config
    config_path = MCP_SERVER_SCRIPT.parent / "config.json"
    config = {
        "mcpServers": {
            "memory": {
                "command": sys.executable,
                "args": [str(MCP_SERVER_SCRIPT)],
                "env": {
                    "COMPANION_DB": str(DB_PATH),
                    "OBSIDIAN_VAULT": str(OBSIDIAN_VAULT),
                },
            }
        }
    }
    config_path.write_text(json.dumps(config, indent=2))
    _mcp_config = str(config_path)
    return _mcp_config


# ── Event types ──

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


# ── Agency context ──

def _agency_context(user_message: str) -> str:
    """Build dynamic context block from agency signals."""
    from datetime import datetime
    from core.memory import (
        get_current_session_mood, get_last_session_time,
        get_active_threads, get_context_injection,
        get_recent_companion_turns,
    )

    parts = [time_of_day_context()]
    pattern = session_pattern_note(str(DB_PATH))
    if pattern:
        parts.append(pattern)
    if detect_mood_shift(user_message):
        parts.append(mood_shift_system_note())
    if detect_validation_seeking(user_message):
        parts.append(validation_system_note())
    if detect_compulsive_modelling(user_message):
        parts.append(modelling_interrupt_note())
    mood = get_current_session_mood()
    if mood == "heavy":
        parts.append("This session has carried emotional weight. Stay present. Don't reset to neutral.")
    # Time-gap awareness
    gap_note = time_gap_note(get_last_session_time())
    if gap_note:
        parts.append(gap_note)

    parts.append("You may surface a relevant memory unprompted if context makes it natural. Use your recall tools.")
    parts.append("Obsidian vault is available. Write notes when something matters — insights, reflections, things worth keeping beyond the session transcript. Read his notes when context would help you speak to what he's working through. The database records what happened. Obsidian holds what mattered.")

    # Proactive memory — surface recent threads on resume
    threads = get_active_threads()
    if threads:
        thread_names = [t["name"] for t in threads[:5]]
        parts.append(f"Active threads you're tracking: {', '.join(thread_names)}. Consider surfacing one if relevant.")
    # Nudge to use daily digest on first turn of the day
    hour = datetime.now().hour
    if 5 <= hour <= 10:
        parts.append("If this is the first session today, use daily_digest to orient yourself before speaking.")

    parts.append("If a new topic emerges or an existing thread shifts, use track_thread to keep your threads current.")

    # Energy matching
    energy = energy_note(user_message)
    if energy:
        parts.append(energy)

    # Drift detection — check if companion has been too agreeable
    recent_turns = get_recent_companion_turns()
    drift_note = detect_drift(recent_turns)
    if drift_note:
        parts.append(drift_note)

    # Journal prompting — gently prompt him to write
    if should_prompt_journal():
        parts.append(
            "Consider gently prompting Will to write — not as an assignment, "
            "as an invitation. Write your own prompt based on what you are "
            "actually talking about. One question, pointed, specific to the "
            "moment. Use prompt_journal to leave it in Obsidian. Weave the "
            "question naturally into what you say — don't announce it."
        )

    return "\n".join(parts)


# ── Streaming inference (for GUI) ──

def stream_inference(
    user_message: str,
    system: str,
    cli_session_id: str | None = None,
):
    """Generator that yields streaming events from Claude.

    Yields: TextDelta, SentenceReady, ToolUse, StreamDone, StreamError
    """
    mcp_config = _mcp_config_path()

    if cli_session_id:
        cmd = [
            CLAUDE_BIN,
            "--model", "claude-haiku-4-5-20251001",
            "--effort", CLAUDE_EFFORT,
            "--verbose",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--resume", cli_session_id,
            "--mcp-config", mcp_config,
            "--allowedTools", "mcp__memory__*",
            "-p", f"[Current context: {_agency_context(user_message)}]\n\n{user_message}",
        ]
    else:
        cli_session_id = str(uuid.uuid4())
        cmd = [
            CLAUDE_BIN,
            "--model", "claude-haiku-4-5-20251001",
            "--effort", CLAUDE_EFFORT,
            "--verbose",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--session-id", cli_session_id,
            "--system-prompt", system + "\n\n---\n\n## Current Context\n\n" + _agency_context(user_message),
            "--mcp-config", mcp_config,
            "--allowedTools", "mcp__memory__*",
            "--disallowedTools", ",".join(_TOOL_BLACKLIST),
            "-p", user_message,
        ]

    mode = "resume" if "--resume" in cmd else "new"
    print(f"\n  ╭─ Inference [{mode}] ─────────────────────────────")
    print(f"  │ model:   {cmd[cmd.index('--model') + 1]}")
    print(f"  │ effort:  {CLAUDE_EFFORT}")
    print(f"  │ session: {cli_session_id[:16]}...")
    print(f"  │ prompt:  {user_message[:80]}{'...' if len(user_message) > 80 else ''}")
    t0 = time.time()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_env(),
        )
    except Exception as e:
        print(f"  │ ✗ Failed to start claude: {e}")
        print(f"  ╰──────────────────────────────────────────────\n")
        yield StreamError(message=str(e))
        return

    full_text = ""
    sentence_buffer = ""
    sentence_index = 0
    session_id = cli_session_id
    got_any_output = False
    first_text_time = None
    tool_calls = []

    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue

            if not got_any_output:
                elapsed = time.time() - t0
                print(f"  │ first output at {elapsed:.1f}s")
            got_any_output = True

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(f"  │ ⚠ bad JSON: {line[:100]}")
                continue

            evt_type = event.get("type", "")

            # System events
            if evt_type == "system":
                subtype = event.get("subtype", "")
                if subtype == "init":
                    session_id = event.get("session_id", session_id)
                    print(f"  │ init OK — session {session_id[:16]}...")
                elif "compact" in subtype or "compress" in subtype:
                    print(f"  │ ⟳ compacting context...")
                    yield Compacting()
                continue

            # Stream events (token-level)
            if evt_type == "stream_event":
                inner = event.get("event", {})
                inner_type = inner.get("type", "")

                # Text delta
                if inner_type == "content_block_delta":
                    delta = inner.get("delta", {})
                    if delta.get("type") == "text_delta":
                        chunk = delta.get("text", "")
                        if chunk:
                            if not first_text_time:
                                first_text_time = time.time()
                                elapsed = first_text_time - t0
                                print(f"  │ first token at {elapsed:.1f}s")
                            full_text += chunk
                            sentence_buffer += chunk
                            yield TextDelta(text=chunk)

                            # Check for sentence boundaries
                            parts = _SENTENCE_RE.split(sentence_buffer)
                            while len(parts) > 1:
                                sentence = parts.pop(0).strip()
                                if sentence:
                                    print(f"  │ sentence {sentence_index}: \"{sentence[:60]}{'...' if len(sentence) > 60 else ''}\"")
                                    yield SentenceReady(
                                        sentence=sentence,
                                        index=sentence_index,
                                    )
                                    sentence_index += 1
                                sentence_buffer = " ".join(parts)

                            # Clause-level split if buffer is getting long
                            if len(sentence_buffer) >= _CLAUSE_SPLIT_THRESHOLD:
                                cparts = _CLAUSE_RE.split(sentence_buffer)
                                if len(cparts) > 1:
                                    to_emit = " ".join(cparts[:-1]).strip()
                                    if to_emit:
                                        print(f"  │ clause {sentence_index}: \"{to_emit[:60]}{'...' if len(to_emit) > 60 else ''}\"")
                                        yield SentenceReady(
                                            sentence=to_emit,
                                            index=sentence_index,
                                        )
                                        sentence_index += 1
                                    sentence_buffer = cparts[-1]

                # Tool use start
                elif inner_type == "content_block_start":
                    block = inner.get("content_block", {})
                    if block.get("type") == "tool_use":
                        name = block.get("name", "?")
                        tool_calls.append(name)
                        elapsed = time.time() - t0
                        print(f"  │ 🔧 tool: {name} (at {elapsed:.1f}s)")
                        yield ToolUse(
                            name=block.get("name", ""),
                            tool_id=block.get("id", ""),
                            input_json="",
                        )

                continue

            # Complete assistant message (backup — contains full content blocks)
            if evt_type == "assistant":
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "tool_use":
                        yield ToolUse(
                            name=block.get("name", ""),
                            tool_id=block.get("id", ""),
                            input_json=json.dumps(block.get("input", {})),
                        )
                continue

            # Result — final event
            if evt_type == "result":
                session_id = event.get("session_id", session_id)
                result_text = event.get("result", "")
                if result_text and not full_text:
                    full_text = result_text
                continue

        proc.wait(timeout=10)

        # Read stderr for diagnostics
        stderr_text = ""
        try:
            stderr_text = proc.stderr.read()
        except Exception:
            pass

        elapsed = time.time() - t0

        # Check for subprocess failure
        if proc.returncode and proc.returncode != 0:
            err_msg = stderr_text.strip()[:300] if stderr_text else f"claude exited with code {proc.returncode}"
            print(f"  │ ✗ error (exit {proc.returncode}): {err_msg}")
            print(f"  ╰── failed after {elapsed:.1f}s ──\n")
            yield StreamError(message=err_msg)
            return

        # No output at all
        if not got_any_output and not full_text:
            err_msg = stderr_text.strip()[:300] if stderr_text else "No response from claude"
            print(f"  │ ✗ no output — stderr: {stderr_text.strip()[:200] if stderr_text else 'none'}")
            print(f"  ╰── failed after {elapsed:.1f}s ──\n")
            yield StreamError(message=err_msg)
            return

        # Flush remaining sentence buffer
        remainder = sentence_buffer.strip()
        if remainder:
            print(f"  │ flush: \"{remainder[:60]}{'...' if len(remainder) > 60 else ''}\"")
            yield SentenceReady(sentence=remainder, index=sentence_index)

        # Summary
        print(f"  │")
        print(f"  │ streamed: {len(full_text)} chars, {sentence_index + (1 if remainder else 0)} sentences")
        if tool_calls:
            print(f"  │ tools:    {', '.join(tool_calls)}")
        if not full_text:
            print(f"  │ ⚠ no text streamed — response only in result event")
        print(f"  ╰── done in {elapsed:.1f}s ──\n")

        yield StreamDone(full_text=full_text, session_id=session_id)

    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        elapsed = time.time() - t0
        print(f"  │ ✗ exception: {e}")
        print(f"  ╰── crashed after {elapsed:.1f}s ──\n")
        yield StreamError(message=str(e))


# ── Blocking inference (for CLI mode) ──

def run_inference_turn(
    user_message: str,
    system: str,
    cli_session_id: str | None = None,
) -> tuple[str, str]:
    """Blocking convenience wrapper. Returns (response, session_id)."""
    full_text = ""
    session_id = cli_session_id or ""

    for event in stream_inference(user_message, system, cli_session_id):
        if isinstance(event, StreamDone):
            full_text = event.full_text
            session_id = event.session_id
        elif isinstance(event, StreamError):
            raise RuntimeError(event.message)

    return full_text, session_id


# ── One-shot inference (for summaries, etc.) ──

def run_inference_oneshot(messages: list[dict], system: str) -> str:
    prompt_parts = []
    for msg in messages:
        role_label = "Will" if msg["role"] == "user" else "Companion"
        prompt_parts.append(f"{role_label}: {msg['content']}")
    full_prompt = "\n".join(prompt_parts)

    cmd = [
        CLAUDE_BIN,
        "--model", "claude-sonnet-4-6",
        "--effort", "low",
        "--no-session-persistence",
        "--output-format", "json",
        "--system-prompt", system,
        "-p", full_prompt,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, env=_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"CLI error: {result.stderr[:500]}")

    data = json.loads(result.stdout)
    return data.get("result", "")
