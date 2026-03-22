#!/usr/bin/env python3
"""Morning brief - queued for next app launch.

Runs via launchd at 7am. Gathers weather (Leeds), active threads,
recent session summaries, and observations. Composes a natural brief
via oneshot inference. Writes to the message queue with pre-synthesised
TTS audio so it plays instantly on next launch.

Schedule: 0 7 * * *  (daily at 7am)
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from config import DB_PATH, MESSAGE_QUEUE, OBSIDIAN_AGENT_DIR, OBSIDIAN_AGENT_NOTES, AGENT_NAME
from core.queue import queue_message
from core.memory import (
    _connect, get_active_threads, get_recent_summaries,
    get_recent_observations,
)
from core.inference import run_inference_oneshot
from core.prompts import load_prompt


def _fetch_weather() -> str:
    """Fetch weather for Leeds via wttr.in (plain text, no deps)."""
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://wttr.in/Leeds?format=%C+%t+%w+%h",
            headers={"User-Agent": "curl/7.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode().strip()
    except Exception as e:
        print(f"[brief] weather fetch failed: {e}")
        return ""


def _fetch_headlines() -> str:
    """Fetch top UK headlines from BBC RSS (no deps)."""
    import urllib.request
    import defusedxml.ElementTree as ET
    try:
        req = urllib.request.Request(
            "https://feeds.bbci.co.uk/news/rss.xml",
            headers={"User-Agent": "curl/7.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            tree = ET.fromstring(resp.read())
        items = tree.findall(".//item")[:5]
        return "\n".join(f"- {item.find('title').text}" for item in items if item.find('title') is not None)
    except Exception as e:
        print(f"[brief] headlines fetch failed: {e}")
        return ""


def _gather_context() -> str:
    parts = []

    # Weather
    weather = _fetch_weather()
    if weather:
        parts.append(f"## Weather in Leeds\n{weather}")

    # Headlines
    headlines = _fetch_headlines()
    if headlines:
        parts.append(f"## UK headlines\n{headlines}")

    # Active threads
    threads = get_active_threads()
    if threads:
        lines = [f"- {t['name']}: {t.get('summary', '...')}" for t in threads[:5]]
        parts.append(f"## Active threads\n" + "\n".join(lines))

    # Recent sessions (last 2 days)
    summaries = get_recent_summaries(n=3)
    if summaries:
        lines = [f"- {s.get('created_at', '?')}: {s.get('content', 'No summary')[:200]}" for s in summaries]
        parts.append(f"## Recent sessions\n" + "\n".join(lines))

    # Recent observations
    observations = get_recent_observations(n=5)
    if observations:
        lines = [f"- {o['content']}" for o in observations]
        parts.append(f"## Recent observations\n" + "\n".join(lines))

    # Companion reflections (latest)
    reflections_path = OBSIDIAN_AGENT_NOTES / "notes" / "reflections.md"
    if reflections_path.is_file():
        content = reflections_path.read_text()
        if len(content) > 800:
            content = "..." + content[-800:]
        parts.append(f"## Your recent reflections\n{content}")

    return "\n\n".join(parts)


_BRIEF_FALLBACK = f"You are {AGENT_NAME}. Write a short natural morning message for the user. 3-6 sentences. Warm but not performative."


def _synthesise_audio(text: str) -> str:
    """Pre-generate TTS audio. Returns path or empty string."""
    try:
        from voice.tts import synthesise_sync
        path = synthesise_sync(text)
        if path and path.exists() and path.stat().st_size > 100:
            return str(path)
    except Exception as e:
        print(f"[brief] TTS failed: {e}")
    return ""


def morning_brief():
    context = _gather_context()
    if not context.strip():
        print("[brief] No context gathered. Skipping.")
        return

    print("[brief] Generating morning brief...")
    try:
        brief = run_inference_oneshot(
            [{"role": "user", "content": f"Here's what you have this morning:\n\n{context}"}],
            system=load_prompt("morning-brief", _BRIEF_FALLBACK),
        )
    except Exception as e:
        print(f"[brief] Inference failed: {e}")
        return

    if not brief or not brief.strip():
        print("[brief] Empty response. Skipping.")
        return

    print(f"[brief] Generated: {brief[:100]}...")

    # Pre-synthesise TTS
    audio = _synthesise_audio(brief)
    if audio:
        print(f"[brief] Audio cached: {audio}")

    # Send via Telegram
    try:
        from channels.telegram import send_message as send_telegram
        send_telegram(brief)
        print("[brief] Sent via Telegram.")
    except Exception as e:
        print(f"[brief] Telegram send failed: {e}")

    # Queue for next app launch
    queue_message(MESSAGE_QUEUE, brief, source="morning_brief", audio_path=audio)
    print("[brief] Queued for next launch.")


if __name__ == "__main__":
    morning_brief()
