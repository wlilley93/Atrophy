#!/usr/bin/env python3
"""Generic task runner - executes a prompt-based task and delivers the result.

Xan can schedule this via manage_schedule to create arbitrary recurring
tasks without writing Python code.

Usage:
  AGENT=xan python scripts/agents/xan/run_task.py <task_name>

Task definitions live in Obsidian at:
  Agent Workspace/xan/tasks/<task_name>.md

Each task file is YAML frontmatter + prompt body:

  ---
  deliver: message_queue     # message_queue | telegram | notification | obsidian
  voice: true                # pre-synthesise TTS audio
  sources:                   # optional data sources to fetch before running
    - weather
    - headlines
    - threads
    - summaries
    - observations
  ---

  You are Xan. Check system status and summarise any issues.

The prompt is sent to oneshot inference with gathered source data.
The response is delivered via the specified channel.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from config import (
    DB_PATH, MESSAGE_QUEUE, OBSIDIAN_AGENT_DIR,
    AGENT_DISPLAY_NAME,
)
from core.queue import queue_message
from core.memory import get_active_threads, get_recent_summaries, get_recent_observations
from core.inference import run_inference_oneshot


TASKS_DIR = OBSIDIAN_AGENT_DIR / "tasks"


def _load_task(name: str) -> tuple[dict, str]:
    """Load task definition. Returns (metadata dict, prompt string)."""
    task_path = TASKS_DIR / f"{name}.md"
    if not task_path.exists():
        print(f"[task] Not found: {task_path}")
        sys.exit(1)

    content = task_path.read_text()

    # Parse YAML frontmatter
    meta = {}
    prompt = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            prompt = parts[2].strip()
            # Simple YAML parsing (no dependency)
            for line in frontmatter.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if val.lower() in ("true", "yes"):
                        meta[key] = True
                    elif val.lower() in ("false", "no"):
                        meta[key] = False
                    elif val.startswith("[") or val.startswith("-"):
                        # List handling for sources
                        pass
                    else:
                        meta[key] = val
            # Parse sources list
            if "sources" not in meta:
                sources = []
                in_sources = False
                for line in frontmatter.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("sources:"):
                        in_sources = True
                        continue
                    if in_sources and stripped.startswith("- "):
                        sources.append(stripped[2:].strip())
                    elif in_sources and not stripped.startswith("-"):
                        in_sources = False
                if sources:
                    meta["sources"] = sources

    return meta, prompt


def _gather_sources(sources: list[str]) -> str:
    """Fetch requested data sources."""
    parts = []

    if "weather" in sources:
        import urllib.request
        try:
            req = urllib.request.Request(
                "https://wttr.in/Leeds?format=%C+%t+%w+%h",
                headers={"User-Agent": "curl/7.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                weather = resp.read().decode().strip()
            if weather:
                parts.append(f"## Weather\n{weather}")
        except Exception:
            pass

    if "headlines" in sources:
        import urllib.request
        import defusedxml.ElementTree as ET
        try:
            req = urllib.request.Request(
                "https://feeds.bbci.co.uk/news/rss.xml",
                headers={"User-Agent": "curl/7.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                tree = ET.fromstring(resp.read())
            items = tree.findall(".//item")[:8]
            lines = [f"- {item.find('title').text}" for item in items if item.find('title') is not None]
            if lines:
                parts.append(f"## Headlines\n" + "\n".join(lines))
        except Exception:
            pass

    if "threads" in sources:
        threads = get_active_threads()
        if threads:
            lines = [f"- {t['name']}: {t.get('summary', '...')}" for t in threads[:5]]
            parts.append(f"## Active threads\n" + "\n".join(lines))

    if "summaries" in sources:
        summaries = get_recent_summaries(n=3)
        if summaries:
            lines = [f"- {s.get('content', '')[:200]}" for s in summaries]
            parts.append(f"## Recent sessions\n" + "\n".join(lines))

    if "observations" in sources:
        obs = get_recent_observations(n=5)
        if obs:
            lines = [f"- {o['content']}" for o in obs]
            parts.append(f"## Observations\n" + "\n".join(lines))

    return "\n\n".join(parts)


def _deliver(text: str, meta: dict, task_name: str):
    """Deliver the result via the specified channel."""
    deliver = meta.get("deliver", "message_queue")

    # Pre-synthesise TTS if requested
    audio_path = ""
    if meta.get("voice", False):
        try:
            from voice.tts import synthesise_sync
            path = synthesise_sync(text)
            if path and path.exists():
                audio_path = str(path)
        except Exception as e:
            print(f"[task] TTS failed: {e}")

    if deliver == "message_queue":
        queue_message(MESSAGE_QUEUE, text, source=task_name, audio_path=audio_path)
        print(f"[task] Queued for next interaction.")

    elif deliver == "telegram":
        try:
            from channels.telegram import send_message
            send_message(text)
            print(f"[task] Sent via Telegram.")
        except Exception as e:
            print(f"[task] Telegram failed: {e}")
        # Also queue for app
        queue_message(MESSAGE_QUEUE, text, source=task_name, audio_path=audio_path)

    elif deliver == "notification":
        from core.notify import send_notification
        # Truncate for notification (macOS has limits)
        body = text[:200] + "..." if len(text) > 200 else text
        send_notification(AGENT_DISPLAY_NAME, body, subtitle=task_name)
        # Also queue full text
        queue_message(MESSAGE_QUEUE, text, source=task_name, audio_path=audio_path)

    elif deliver == "obsidian":
        note_path = OBSIDIAN_AGENT_DIR / "notes" / "tasks" / f"{task_name}.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n---\n**{timestamp}**\n\n{text}\n"
        with open(note_path, "a") as f:
            f.write(entry)
        print(f"[task] Written to Obsidian: {note_path}")

    else:
        print(f"[task] Unknown delivery method: {deliver}")
        queue_message(MESSAGE_QUEUE, text, source=task_name, audio_path=audio_path)


def run_task(task_name: str):
    meta, prompt = _load_task(task_name)
    print(f"[task] Running: {task_name}")
    print(f"[task] Deliver via: {meta.get('deliver', 'message_queue')}")

    # Gather sources if specified
    sources = meta.get("sources", [])
    context = ""
    if sources:
        print(f"[task] Fetching sources: {sources}")
        context = _gather_sources(sources)

    # Build inference input
    user_msg = prompt
    if context:
        user_msg = f"Here's the data you requested:\n\n{context}\n\n---\n\n{prompt}"

    try:
        result = run_inference_oneshot(
            [{"role": "user", "content": user_msg}],
            system=f"You are {AGENT_DISPLAY_NAME}. Complete this task naturally, as yourself.",
        )
    except Exception as e:
        print(f"[task] Inference failed: {e}")
        return

    if not result or not result.strip():
        print(f"[task] Empty response. Skipping delivery.")
        return

    print(f"[task] Result: {result[:100]}...")
    _deliver(result, meta, task_name)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_task.py <task_name>")
        print(f"Tasks dir: {TASKS_DIR}")
        sys.exit(1)
    run_task(sys.argv[1])
