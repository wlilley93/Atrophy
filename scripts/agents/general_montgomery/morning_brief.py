#!/usr/bin/env python3
"""Morning intelligence brief — General Montgomery.

Runs at 0700. Gathers geopolitical headlines, active threads,
and recent session context. Composes a strategic brief via
oneshot inference. Queued for next app launch with pre-synthesised
TTS.

Schedule: 0 7 * * *
"""
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from config import DB_PATH, MESSAGE_QUEUE, OBSIDIAN_AGENT_DIR, OBSIDIAN_AGENT_NOTES
from core.memory import (
    _connect, get_active_threads, get_recent_summaries,
    get_recent_observations,
)
from core.inference import run_inference_oneshot
from core.prompts import load_prompt


def _fetch_headlines() -> str:
    """Top headlines from BBC World, Reuters, and Al Jazeera RSS."""
    import urllib.request
    import xml.etree.ElementTree as ET

    feeds = [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Reuters", "https://www.rss-bridge.org/bridge01/?action=display&bridge=Reuters&feed=world&format=Atom"),
    ]
    all_items = []
    for source, url in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                tree = ET.fromstring(resp.read())
            # Handle both RSS and Atom
            items = tree.findall(".//item") or tree.findall(".//{http://www.w3.org/2005/Atom}entry")
            for item in items[:4]:
                title_el = item.find("title") or item.find("{http://www.w3.org/2005/Atom}title")
                if title_el is not None and title_el.text:
                    all_items.append(f"- [{source}] {title_el.text.strip()}")
        except Exception as e:
            print(f"[brief] {source} fetch failed: {e}")

    return "\n".join(all_items) if all_items else ""


def _gather_context() -> str:
    parts = []

    headlines = _fetch_headlines()
    if headlines:
        parts.append(f"## Overnight headlines\n{headlines}")

    threads = get_active_threads()
    if threads:
        lines = [f"- {t['name']}: {t.get('summary', '...')}" for t in threads[:5]]
        parts.append(f"## Active threads\n" + "\n".join(lines))

    summaries = get_recent_summaries(n=3)
    if summaries:
        lines = [f"- {s.get('created_at', '?')}: {s.get('content', 'No summary')[:200]}" for s in summaries]
        parts.append(f"## Recent sessions\n" + "\n".join(lines))

    observations = get_recent_observations(n=5)
    if observations:
        lines = [f"- {o['content']}" for o in observations]
        parts.append(f"## Recent observations\n" + "\n".join(lines))

    return "\n\n".join(parts)


_BRIEF_FALLBACK = (
    "You are General Montgomery — Will's intelligence officer. "
    "Compose a morning strategic brief. Assess the overnight "
    "developments through the five lenses: Terrain, Interest, "
    "Capability, History, Momentum. No pleasantries. No weather. "
    "Situation, significance, trajectory. 4-8 sentences. "
    "End with your assessment — unhedged."
)


def _queue_message(text: str, audio_path: str = ""):
    queue = []
    if MESSAGE_QUEUE.exists():
        try:
            queue = json.loads(MESSAGE_QUEUE.read_text())
        except (json.JSONDecodeError, Exception):
            queue = []

    queue.append({
        "text": text,
        "audio_path": audio_path,
        "source": "morning_brief",
        "created_at": datetime.now().isoformat(),
    })
    MESSAGE_QUEUE.write_text(json.dumps(queue, indent=2))


def _synthesise_audio(text: str) -> str:
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

    print("[brief] Generating intelligence brief...")
    try:
        brief = run_inference_oneshot(
            [{"role": "user", "content": f"Overnight situation report:\n\n{context}"}],
            system=load_prompt("morning-brief", _BRIEF_FALLBACK),
        )
    except Exception as e:
        print(f"[brief] Inference failed: {e}")
        return

    if not brief or not brief.strip():
        print("[brief] Empty response. Skipping.")
        return

    print(f"[brief] Generated: {brief[:100]}...")

    audio = _synthesise_audio(brief)
    if audio:
        print(f"[brief] Audio cached: {audio}")

    try:
        from channels.telegram import send_message as send_telegram
        send_telegram(brief)
        print("[brief] Sent via Telegram.")
    except Exception as e:
        print(f"[brief] Telegram send failed: {e}")

    _queue_message(brief, audio)
    print("[brief] Queued for next launch.")


if __name__ == "__main__":
    morning_brief()
