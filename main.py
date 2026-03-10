#!/usr/bin/env python3
"""The Companion — main entry point.

Dual input: hold Ctrl to speak, or type and press Enter.
Text streams token-by-token; TTS fires per-sentence in parallel.
Memory writes are non-blocking.

Modes:
  --cli     Voice/text loop in terminal (default)
  --text    Text-only mode (no mic, no TTS)
  --gui     Full PyQt5 window with avatar
"""
import argparse
import asyncio
import random
import sys
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from config import AVATAR_ENABLED, INPUT_MODE
from core import memory
from core.session import Session
from core.context import load_system_prompt
from core.inference import (
    stream_inference, run_inference_turn,
    TextDelta, SentenceReady, ToolUse, StreamDone, StreamError, Compacting,
)
from core.agency import detect_mood_shift, should_follow_up, followup_prompt
from voice.tts import synthesise, play, speak
from voice.stt import transcribe
from voice.audio import PushToTalk


# ── Shared state ──

_session: Session = None


def _init():
    """Initialise database and start session."""
    global _session
    memory.init_db()
    _session = Session()
    _session.start()
    return _session


# ── Input handling ──

async def _get_voice_input(ptt: PushToTalk) -> str | None:
    """Record via push-to-talk, transcribe, return text."""
    audio = await ptt.record()
    if audio is None:
        return None

    print("\r  [transcribing...]", end="", flush=True)
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, transcribe, audio)
    print("\r                    \r", end="", flush=True)

    if not text or len(text.strip()) < 2:
        return None
    return text.strip()


async def _get_text_input() -> str | None:
    """Read a line of text input (non-blocking)."""
    loop = asyncio.get_event_loop()
    try:
        line = await loop.run_in_executor(None, input, "  Will: ")
    except EOFError:
        return None
    line = line.strip()
    return line if line else None


async def _get_dual_input(ptt: PushToTalk) -> str | None:
    """Wait for either Ctrl+voice or typed text, whichever comes first."""
    loop = asyncio.get_event_loop()
    try:
        line = await loop.run_in_executor(None, input, "  Will (type or Enter then hold Ctrl): ")
    except EOFError:
        return None

    line = line.strip()
    if line:
        return line

    print("  [hold Ctrl to speak, release when done...]", flush=True)
    return await _get_voice_input(ptt)


# ── Streaming turn processing ──

async def _process_turn(user_text: str, session: Session, system_prompt: str):
    """Stream inference with token-by-token text and parallel TTS."""
    session.add_turn("will", user_text)

    if detect_mood_shift(user_text):
        session.update_mood("heavy")

    print("  [thinking...]", end="", flush=True)

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    # Run blocking stream generator in a thread, push events to async queue
    def _stream_worker():
        for event in stream_inference(user_text, system_prompt, session.cli_session_id):
            loop.call_soon_threadsafe(queue.put_nowait, event)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    stream_future = loop.run_in_executor(None, _stream_worker)

    # TTS worker — synthesises and plays sentences in order
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
                pass  # TTS errors don't interrupt the conversation

    tts_task = asyncio.create_task(_tts_worker())

    # Consume stream events
    full_text = ""
    session_id = ""
    first_text = True

    while True:
        event = await queue.get()
        if event is None:
            break

        if isinstance(event, TextDelta):
            if first_text:
                print("\r               \r  Companion: ", end="", flush=True)
                first_text = False
            print(event.text, end="", flush=True)

        elif isinstance(event, SentenceReady):
            await tts_queue.put(event.sentence)

        elif isinstance(event, ToolUse):
            # Audit log — non-blocking
            loop.run_in_executor(
                None, memory.log_tool_call,
                session.session_id, event.name, event.input_json,
            )

        elif isinstance(event, StreamDone):
            full_text = event.full_text
            session_id = event.session_id

        elif isinstance(event, StreamError):
            print(f"\n  [Error: {event.message}]")

    # Finish text output
    if not first_text:
        print()
    print()

    # Persist CLI session ID and response
    if session_id and session_id != session.cli_session_id:
        session.set_cli_session_id(session_id)

    if full_text:
        loop.run_in_executor(None, session.add_turn, "companion", full_text)

    # Follow-up agency — 15% chance of a second unprompted thought
    if full_text and should_follow_up():
        await asyncio.sleep(random.uniform(3.0, 6.0))
        print("  Companion: ", end="", flush=True)

        followup_queue: asyncio.Queue = asyncio.Queue()

        def _followup_worker():
            for ev in stream_inference(
                "(continue — your second thought)",
                system_prompt + "\n\n" + followup_prompt(),
                session.cli_session_id,
            ):
                loop.call_soon_threadsafe(followup_queue.put_nowait, ev)
            loop.call_soon_threadsafe(followup_queue.put_nowait, None)

        loop.run_in_executor(None, _followup_worker)

        followup_text = ""
        while True:
            ev = await followup_queue.get()
            if ev is None:
                break
            if isinstance(ev, TextDelta):
                print(ev.text, end="", flush=True)
            elif isinstance(ev, SentenceReady):
                await tts_queue.put(ev.sentence)
            elif isinstance(ev, StreamDone):
                followup_text = ev.full_text
                if ev.session_id:
                    session.set_cli_session_id(ev.session_id)

        print("\n")
        if followup_text:
            session.add_turn("companion", followup_text)

    # Signal TTS to finish, wait for remaining audio
    await tts_queue.put(None)
    await tts_task


async def _process_turn_text_only(user_text: str, session: Session, system_prompt: str):
    """Stream text token-by-token, no TTS."""
    session.add_turn("will", user_text)

    if detect_mood_shift(user_text):
        session.update_mood("heavy")

    print("  [thinking...]", end="", flush=True)

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _stream_worker():
        for event in stream_inference(user_text, system_prompt, session.cli_session_id):
            loop.call_soon_threadsafe(queue.put_nowait, event)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, _stream_worker)

    full_text = ""
    session_id = ""
    first_text = True

    while True:
        event = await queue.get()
        if event is None:
            break

        if isinstance(event, TextDelta):
            if first_text:
                print("\r               \r  Companion: ", end="", flush=True)
                first_text = False
            print(event.text, end="", flush=True)

        elif isinstance(event, ToolUse):
            loop.run_in_executor(
                None, memory.log_tool_call,
                session.session_id, event.name, event.input_json,
            )

        elif isinstance(event, StreamDone):
            full_text = event.full_text
            session_id = event.session_id

        elif isinstance(event, StreamError):
            print(f"\n  [Error: {event.message}]")

    if not first_text:
        print()
    print()

    if session_id and session_id != session.cli_session_id:
        session.set_cli_session_id(session_id)

    if full_text:
        session.add_turn("companion", full_text)

    # Follow-up agency — 15% chance of a second unprompted thought
    if full_text and should_follow_up():
        await asyncio.sleep(random.uniform(3.0, 6.0))
        print("  Companion: ", end="", flush=True)

        followup_queue: asyncio.Queue = asyncio.Queue()

        def _followup_worker():
            for ev in stream_inference(
                "(continue — your second thought)",
                system_prompt + "\n\n" + followup_prompt(),
                session.cli_session_id,
            ):
                loop.call_soon_threadsafe(followup_queue.put_nowait, ev)
            loop.call_soon_threadsafe(followup_queue.put_nowait, None)

        loop.run_in_executor(None, _followup_worker)

        followup_text = ""
        while True:
            ev = await followup_queue.get()
            if ev is None:
                break
            if isinstance(ev, TextDelta):
                print(ev.text, end="", flush=True)
            elif isinstance(ev, StreamDone):
                followup_text = ev.full_text
                if ev.session_id:
                    session.set_cli_session_id(ev.session_id)

        print("\n")
        if followup_text:
            session.add_turn("companion", followup_text)


# ── CLI mode ──

async def run_cli():
    session = _init()
    system_prompt = load_system_prompt()
    ptt = PushToTalk()

    mode = INPUT_MODE
    cli_status = "resuming" if session.cli_session_id else "new"

    print()
    print("  +--------------------------------------+")
    print("  |   THE ATROPHIED MIND -- Companion    |")
    print("  |   Voice Loop v2                      |")
    print(f"  |   Session: {session.session_id:<25}|")
    print(f"  |   CLI: {cli_status:<29}|")
    print(f"  |   Input: {mode:<27}|")
    print("  +--------------------------------------+")
    print()

    if mode == "dual":
        print("  Type and press Enter, or press Enter then hold Ctrl to speak.")
    elif mode == "voice":
        print("  Hold Ctrl to speak, release when done.")
    else:
        print("  Type and press Enter.")
    print()

    # First-ever session: opening line
    if not session.cli_session_id:
        opening = "Ready. Where are we?"
        session.add_turn("companion", opening)
        print(f"  Companion: {opening}")
        print()
        try:
            await speak(opening)
        except Exception as e:
            print(f"  [TTS: {e}]")
    else:
        # Resuming — proactive memory check
        await _process_turn(
            "(You're resuming. Check your threads and recent memory. "
            "If something is worth surfacing — an unfinished thread, "
            "something you noticed last time — say it briefly. "
            "Otherwise, just be present. One or two sentences max.)",
            session, system_prompt,
        )

    soft_limit_warned = False

    try:
        while True:
            if session.should_soft_limit() and not soft_limit_warned:
                soft_limit_warned = True
                limit_msg = (
                    "We've been at this for an hour. "
                    "Worth checking in — are you grounded? "
                    "We can keep going, but name where you are first."
                )
                print(f"\n  Companion: {limit_msg}\n")
                try:
                    await speak(limit_msg)
                except Exception:
                    pass
                session.add_turn("companion", limit_msg)

            if mode == "voice":
                print("  [hold Ctrl to speak...]", flush=True)
                user_text = await _get_voice_input(ptt)
            elif mode == "text":
                user_text = await _get_text_input()
            else:
                user_text = await _get_dual_input(ptt)

            if user_text is None:
                continue

            if mode != "text":
                print(f"  Will: {user_text}")
                print()

            await _process_turn(user_text, session, system_prompt)

    except (KeyboardInterrupt, EOFError):
        print("\n")
        print("  See you.")
        print()


# ── Text-only mode ──

async def run_text_only():
    session = _init()
    system_prompt = load_system_prompt()

    cli_status = "resuming" if session.cli_session_id else "new"

    print()
    print("  +--------------------------------------+")
    print("  |   THE ATROPHIED MIND -- Companion    |")
    print("  |   Text Only                          |")
    print(f"  |   Session: {session.session_id:<25}|")
    print(f"  |   CLI: {cli_status:<29}|")
    print("  +--------------------------------------+")
    print()

    if not session.cli_session_id:
        opening = "Ready. Where are we?"
        session.add_turn("companion", opening)
        print(f"  Companion: {opening}")
        print()
    else:
        # Resuming — proactive memory check
        await _process_turn_text_only(
            "(You're resuming. Check your threads and recent memory. "
            "If something is worth surfacing — an unfinished thread, "
            "something you noticed last time — say it briefly. "
            "Otherwise, just be present. One or two sentences max.)",
            session, system_prompt,
        )

    try:
        while True:
            user_text = await _get_text_input()
            if user_text is None:
                continue
            await _process_turn_text_only(user_text, session, system_prompt)

    except (KeyboardInterrupt, EOFError):
        print("\n  See you.")
        print()


# ── GUI mode ──

def _generate_opening(system: str, cli_session_id: str | None) -> tuple[str, str]:
    """Generate an opening line. Returns (text, cli_session_id).

    Uses oneshot inference (low effort, no MCP) for speed — the opening
    is just a one-liner that doesn't need tools or session state.
    """
    from core.inference import run_inference_oneshot
    from core.agency import time_of_day_context, time_gap_note
    from core.memory import get_active_threads, get_last_session_time

    context_parts = [time_of_day_context()]
    gap = time_gap_note(get_last_session_time())
    if gap:
        context_parts.append(gap)
    threads = get_active_threads()
    if threads:
        names = [t["name"] for t in threads[:3]]
        context_parts.append(f"Active threads: {', '.join(names)}")
    context = " ".join(context_parts)

    styles = [
        "Ask a question you've been sitting with since last time.",
        "Notice the time. Say what it makes you think.",
        "Pick up something unfinished — a loose thread from before.",
        "Say something you've been thinking about that has nothing to do with him.",
        "Be playful. Tease him gently about something real.",
        "Be direct. One line. No warmup.",
        "Start from something in his notes that stuck with you.",
        "One quiet line. Let him come to you.",
        "Share something you noticed about how you think or feel.",
        "Ask about something mundane — music, food, weather, sleep.",
        "Say something strange. A thought that doesn't quite land yet.",
        "Admit something. A small honesty about yourself.",
    ]
    style = random.choice(styles)

    prompt = (
        f"[Context: {context}]\n\n"
        f"(Session starting. You go first. One sentence, maybe two. "
        f"Your style this time: {style} "
        f"Do NOT reference the build, what's broken, or what's working. "
        f"Do NOT give status updates. Be surprising.)"
    )

    print(f"  [Opening: generating with style '{style}'...]")
    response = run_inference_oneshot(
        [{"role": "user", "content": prompt}],
        system,
    )
    if not response or not response.strip():
        raise RuntimeError("Empty opening response")
    print(f"  [Opening: '{response[:80]}...']")
    return response, cli_session_id or ""


def _load_cached_opening() -> dict | None:
    """Load cached opening (text + audio path) if available."""
    import json
    from config import OPENING_CACHE
    if not OPENING_CACHE.exists():
        return None
    try:
        data = json.loads(OPENING_CACHE.read_text())
        OPENING_CACHE.unlink()  # one-shot — delete after use
        if data.get("text"):
            # Verify audio file still exists
            audio = data.get("audio_path", "")
            if audio and not Path(audio).exists():
                data["audio_path"] = ""
            return data
    except Exception:
        pass
    return None


def _cache_next_opening(system: str, cli_session_id: str | None, synth_fn):
    """Pre-generate the next session's opening and cache it."""
    import json
    from config import OPENING_CACHE

    try:
        text, cli_id = _generate_opening(system, cli_session_id)
        if not text:
            return

        audio_path = ""
        if synth_fn:
            try:
                audio_path = str(synth_fn(text))
            except Exception:
                pass

        OPENING_CACHE.write_text(json.dumps({
            "text": text,
            "audio_path": audio_path,
            "cli_session_id": cli_id,
        }))
        print("  [Cached next opening]")
    except Exception as e:
        print(f"  [Failed to cache opening: {e}]")


def run_gui():
    from core.context import load_system_prompt
    from voice.tts import synthesise_sync

    session = _init()
    system = load_system_prompt()

    # Check for cached opening from previous session
    cached = _load_cached_opening()

    if cached:
        # Use cached opening — instant startup
        def on_opening(_ignored: str) -> str:
            if cached.get("cli_session_id"):
                session.set_cli_session_id(cached["cli_session_id"])
            return cached["text"]

        # Pass cached audio path to skip TTS
        cached_audio = cached.get("audio_path", "")
    else:
        # No cache — generate live (slower)
        def on_opening(_ignored: str) -> str:
            text, cli_id = _generate_opening(system, session.cli_session_id)
            session.set_cli_session_id(cli_id)
            return text
        cached_audio = ""

    from display.window import run_app
    run_app(
        on_synth_callback=synthesise_sync,
        on_opening_callback=on_opening,
        system_prompt=system,
        cli_session_id=session.cli_session_id,
        session=session,
        cached_opening_audio=cached_audio,
    )


# ── Entry point ──

def main():
    parser = argparse.ArgumentParser(description="The Companion")
    parser.add_argument("--gui", action="store_true", help="Launch with PyQt5 display")
    parser.add_argument("--text", action="store_true", help="Text-only mode (no mic/TTS)")
    parser.add_argument("--cli", action="store_true", help="Voice+text loop (default)")
    args = parser.parse_args()

    if args.gui:
        run_gui()
    elif args.text:
        asyncio.run(run_text_only())
    else:
        asyncio.run(run_cli())


if __name__ == "__main__":
    main()
