# scripts/agents/shared/morning_brief.py - Morning Briefing

**Line count:** ~166 lines  
**Dependencies:** `json`, `sys`, `datetime`, `pathlib`, `urllib`, `dotenv`, `config`, `core.*`  
**Purpose:** Morning briefing queued for next app launch

## Overview

Runs via launchd at 7am. Gathers weather (Leeds), active threads, recent session summaries, and observations. Composes a natural brief via oneshot inference. Writes to the message queue with pre-synthesised TTS audio so it plays instantly on next launch.

**Schedule:** `0 7 * * *` (daily at 7am)

## Data Fetching

### _fetch_weather

```python
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
```

**Purpose:** Fetch weather for Leeds.

**Format:** `%C+%t+%w+%h` = Condition + Temperature + Wind + Humidity

**Example output:** `☀️+15°C+↑15km/h+62%`

### _fetch_headlines

```python
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
```

**Purpose:** Fetch top 5 UK headlines from BBC RSS.

**Dependencies:** `defusedxml` for safe XML parsing.

## Context Gathering

### _gather_context

```python
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
```

**Purpose:** Gather morning brief context.

**Sections:**
1. Weather in Leeds
2. UK headlines (top 5)
3. Active threads (top 5)
4. Recent sessions (last 3)
5. Recent observations (last 5)
6. Latest companion reflections (last 800 chars)

## Brief Prompt

```python
_BRIEF_FALLBACK = f"You are {AGENT_NAME}. Write a short natural morning message for the user. 3-6 sentences. Warm but not performative."
```

**Purpose:** Fallback prompt if morning-brief prompt not found.

## TTS Synthesis

### _synthesise_audio

```python
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
```

**Purpose:** Pre-synthesize TTS audio for instant playback.

**Validation:** Check file exists and size > 100 bytes.

## Main Function

### morning_brief

```python
def morning_brief():
    # Gather context
    context = _gather_context()
    if not context.strip():
        print("[brief] No context gathered. Skipping.")
        return

    print("[brief] Generating morning brief...")

    # Run inference
    try:
        brief = run_inference_oneshot(
            [{"role": "user", "content": f"Here's what you have this morning:\n\n{context}"}],
            system=load_prompt("morning-brief", _BRIEF_FALLBACK),
            timeout=120,
        )
    except Exception as e:
        print(f"[brief] Inference failed: {e}")
        return

    if not brief or not brief.strip():
        print("[brief] Empty response. Skipping.")
        return

    print(f"[brief] Generated: {brief[:100]}...")

    # Pre-synthesize TTS
    audio = _synthesise_audio(brief)
    if audio:
        print(f"[brief] Audio cached: {audio}")

    # Queue message
    queue_message(brief, source="morning-brief", audio_path=audio)
    print(f"[brief] Queued for next launch")
```

**Flow:**
1. Gather context (weather, headlines, threads, sessions, observations, reflections)
2. Run inference with morning brief prompt
3. Pre-synthesize TTS audio
4. Queue message with audio for next app launch

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/.message_queue.json` | Queued message with audio |
| `~/.atrophy/agents/<name>/notes/reflections.md` | Companion reflections |
| `/tmp/atrophy-tts-*.mp3` | Pre-synthesized audio |

## Exported API

| Function | Purpose |
|----------|---------|
| `morning_brief()` | Generate morning brief |
| `_fetch_weather()` | Fetch Leeds weather |
| `_fetch_headlines()` | Fetch BBC headlines |
| `_gather_context()` | Gather brief context |
| `_synthesise_audio(text)` | Pre-synthesize TTS |

## See Also

- `src/main/jobs/morning-brief.ts` - TypeScript morning brief job
- `scripts/cron.py` - Cron job management
- `voice/tts.py` - TTS synthesis
