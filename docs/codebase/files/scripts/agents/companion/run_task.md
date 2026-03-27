# scripts/agents/companion/run_task.py - Generic Task Runner

**Line count:** ~263 lines  
**Dependencies:** `json`, `os`, `sys`, `datetime`, `pathlib`, `urllib`, `dotenv`, `config`, `core.*`  
**Purpose:** Execute prompt-based tasks defined in Obsidian - scheduled via manage_schedule

## Overview

The companion agent can schedule this via manage_schedule to create arbitrary recurring tasks without writing Python code.

**Usage:**
```bash
python scripts/agents/companion/run_task.py <task_name>
```

**Task definitions:** `Agent Workspace/<agent>/tasks/<task_name>.md`

## Task File Format

```markdown
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

You are the companion. Fetch and summarise the latest UK news headlines.
Keep it to 3-5 bullet points. Be conversational.
```

**Frontmatter fields:**
- `deliver`: Delivery channel
- `voice`: Pre-synthesize TTS
- `sources`: Data sources to fetch

## Task Loading

### _load_task

```python
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
            import re
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
```

**Purpose:** Load task definition from Obsidian.

**Parsing:**
- Simple YAML parsing (no external dependency)
- Boolean conversion (true/yes → True, false/no → False)
- List parsing for sources field

## Source Gathering

### _gather_sources

```python
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
```

**Purpose:** Fetch requested data sources.

**Supported sources:**
1. **weather**: wttr.in (Leeds)
2. **headlines**: BBC RSS feed (top 8)
3. **threads**: Active threads (top 5)
4. **summaries**: Recent session summaries (last 3)
5. **observations**: Recent observations (last 5)

## Delivery

### _deliver

```python
def _deliver(text: str, meta: dict, task_name: str):
    """Deliver the result via the specified channel."""
    deliver = meta.get("deliver", "message_queue")

    # Pre-synthesize TTS if requested
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

    elif deliver in ("telegram", "telegram_voice"):
        try:
            if deliver == "telegram_voice" and audio_path:
                from channels.telegram import send_voice_note, send_message
                if not send_voice_note(audio_path):
                    send_message(text)
            else:
                from channels.telegram import send_message
                send_message(text)
            print(f"[task] Sent via Telegram.")
        except Exception as e:
            print(f"[task] Telegram failed: {e}")
        # Also queue for app
        queue_message(MESSAGE_QUEUE, text, source=task_name, audio_path=audio_path)

    elif deliver == "notification":
        try:
            from core.notify import send_notification
            send_notification(task_name, text)
            print(f"[task] Notification sent.")
        except Exception as e:
            print(f"[task] Notification failed: {e}")
        # Also queue for app
        queue_message(MESSAGE_QUEUE, text, source=task_name, audio_path=audio_path)

    elif deliver == "obsidian":
        try:
            output_dir = OBSIDIAN_AGENT_NOTES / "notes" / "tasks"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{task_name}-{datetime.now().strftime('%Y-%m-%d-%H%M')}.md"
            output_path.write_text(f"# {task_name}\n\n*{datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n{text}")
            print(f"[task] Written to {output_path}")
        except Exception as e:
            print(f"[task] Obsidian write failed: {e}")
```

**Purpose:** Deliver result via specified channel.

**Delivery channels:**
1. **message_queue**: Queue for next app launch
2. **telegram**: Send via Telegram
3. **telegram_voice**: Send as voice note (if TTS available)
4. **notification**: macOS notification
5. **obsidian**: Write to Obsidian notes/tasks/

## Main Function

### run_task

```python
def run_task(task_name: str):
    # Load task definition
    meta, prompt = _load_task(task_name)

    # Gather sources
    sources = meta.get("sources", [])
    context = _gather_sources(sources) if sources else ""

    # Build full prompt
    full_prompt = f"{context}\n\n---\n\n{prompt}" if context else prompt

    # Run inference
    try:
        result = run_inference_oneshot(
            [{"role": "user", "content": full_prompt}],
            system=f"You are {AGENT_DISPLAY_NAME}. Execute the following task.",
            timeout=120,
        )
    except Exception as e:
        print(f"[task] Inference failed: {e}")
        return

    if not result or not result.strip():
        print("[task] Empty result")
        return

    print(f"[task] Generated: {result[:100]}...")

    # Deliver result
    _deliver(result, meta, task_name)
```

**Flow:**
1. Load task definition (metadata + prompt)
2. Gather requested sources
3. Build full prompt (context + task prompt)
4. Run inference
5. Deliver result via specified channel

## File I/O

| File | Purpose |
|------|---------|
| `<Obsidian>/Agents/<name>/tasks/<name>.md` | Task definitions |
| `<Obsidian>/Agents/<name>/notes/tasks/*.md` | Task output (obsidian delivery) |
| `~/.atrophy/agents/<name>/data/.message_queue.json` | Queued messages |

## Exported API

| Function | Purpose |
|----------|---------|
| `run_task(task_name)` | Execute task |
| `_load_task(name)` | Load task definition |
| `_gather_sources(sources)` | Fetch data sources |
| `_deliver(text, meta, task_name)` | Deliver result |

## See Also

- `src/main/jobs/run-task.ts` - TypeScript task runner
- `scripts/cron.py` - Task scheduling via cron
- `core/memory.py` - Source data functions
