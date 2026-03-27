# scripts/agents/companion/voice_note.py - Spontaneous Voice Notes

**Line count:** ~217 lines  
**Dependencies:** `json`, `os`, `random`, `subprocess`, `sys`, `datetime`, `pathlib`, `dotenv`, `config`, `core.*`  
**Purpose:** Send spontaneous voice notes via Telegram - random schedule, 2-8 hours

## Overview

Runs on a randomized schedule. The agent generates a short thought - something it's been sitting with, a connection it noticed, a follow-up to something from a recent conversation - synthesizes it as speech, and sends it as a Telegram voice note.

After running, reschedules itself to a random time 2-8 hours from now (within active hours). The randomness is the point - it should feel like the agent genuinely thought of something and reached out.

## Context Gathering

### _gather_context

```python
def _gather_context() -> str:
    """Pull recent threads, observations, and turns for inspiration."""
    conn = _connect()
    parts = []

    # Active threads
    threads = get_active_threads()
    if threads:
        parts.append("Active threads:\n" + "\n".join(
            f"- {t['name']}: {t.get('summary', '...')}" for t in threads[:5]
        ))

    # Recent observations
    obs = get_recent_observations(n=8)
    if obs:
        parts.append("Recent observations:\n" + "\n".join(
            f"- {o['content']}" for o in obs
        ))

    # Recent conversation turns (last few meaningful exchanges)
    turns = conn.execute(
        "SELECT role, content FROM turns "
        "WHERE role IN ('will', 'agent') "
        "ORDER BY timestamp DESC LIMIT 6"
    ).fetchall()
    if turns:
        parts.append("Recent conversation:\n" + "\n".join(
            f"- [{t['role']}] {t['content'][:200]}" for t in reversed(turns)
        ))

    conn.close()
    return "\n\n".join(parts)
```

**Purpose:** Gather context for voice note generation.

**Sections:**
1. Active threads (top 5)
2. Recent observations (last 8)
3. Recent conversation (last 6 turns, chronological order)

## Audio Conversion

### _convert_to_ogg

```python
def _convert_to_ogg(input_path: str) -> str | None:
    """Convert audio to OGG Opus for Telegram voice notes."""
    output_path = input_path.rsplit(".", 1)[0] + ".ogg"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-c:a", "libopus",
             "-b:a", "64k", "-vn", output_path],
            capture_output=True, timeout=30,
        )
        if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
            return output_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None
```

**Purpose:** Convert TTS output to OGG Opus format for Telegram voice notes.

**Settings:**
- Codec: libopus
- Bitrate: 64k
- No video (-vn)
- Timeout: 30 seconds

## Rescheduling

### _reschedule

```python
def _reschedule():
    """Reschedule to a random time 2-8 hours from now, within active hours."""
    try:
        from config import HEARTBEAT_ACTIVE_START, HEARTBEAT_ACTIVE_END
        active_start = HEARTBEAT_ACTIVE_START
        active_end = HEARTBEAT_ACTIVE_END
    except ImportError:
        active_start, active_end = 9, 22

    now = datetime.now()
    offset_hours = random.uniform(2, 8)
    next_run = now + timedelta(hours=offset_hours)

    # If outside active hours, push to next active window
    if next_run.hour >= active_end:
        next_run = next_run.replace(hour=active_start, minute=random.randint(0, 59))
        next_run += timedelta(days=1)
    elif next_run.hour < active_start:
        next_run = next_run.replace(hour=active_start, minute=random.randint(0, 59))

    cron = f"{next_run.minute} {next_run.hour} {next_run.day} {next_run.month} *"

    # Update jobs.json
    jobs_file = PROJECT_ROOT / "scripts" / "agents" / AGENT_NAME / "jobs.json"
    if jobs_file.exists():
        jobs = json.loads(jobs_file.read_text())
        jobs["voice_note"] = {
            "cron": cron,
            "script": f"scripts/agents/{AGENT_NAME}/voice_note.py",
            "description": "Spontaneous voice note via Telegram - self-rescheduling",
        }
        jobs_file.write_text(json.dumps(jobs, indent=2) + "\n")

        # Reinstall the specific job
        try:
            subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / "cron.py"), "install"],
                env={**os.environ, "AGENT": AGENT_NAME},
                capture_output=True, timeout=15,
            )
        except Exception:
            pass

    print(f"[voice_note] Rescheduled to {next_run.strftime('%Y-%m-%d %H:%M')}")
```

**Purpose:** Reschedule to random future time within active hours.

**Randomization:**
- Offset: 2-8 hours (random float)
- Active hours check: If outside, push to next active window

**Job update:**
- Updates jobs.json with new cron expression
- Reinstalls job via cron.py install command

## Main Function

### run

```python
def run():
    # Check Telegram configuration
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[voice_note] Telegram not configured - skipping")
        return

    now = datetime.now()
    # Check active hours
    try:
        from config import HEARTBEAT_ACTIVE_START, HEARTBEAT_ACTIVE_END
        if not (HEARTBEAT_ACTIVE_START <= now.hour < HEARTBEAT_ACTIVE_END):
            print("[voice_note] Outside active hours - rescheduling")
            _reschedule()
            return
    except ImportError:
        pass

    # Gather context
    context = _gather_context()
    if not context.strip():
        print("[voice_note] No context material - skipping")
        _reschedule()
        return

    # Generate the thought
    prompt = load_prompt("voice-note", fallback=None)
    if not prompt:
        prompt = (
            "You're sending a spontaneous voice note to the person you know. "
            "Something you've been sitting with - a thought, a connection you "
            "noticed, a follow-up to something recent. Keep it short and natural. "
            "2-4 sentences. Speak as yourself, not as an assistant delivering a "
            "report. This should sound like a person who just thought of something "
            "and wanted to share it. No greeting. No sign-off. Just the thought."
        )

    result = run_inference_oneshot(
        [{"role": "user", "content": f"{context}\n\n---\n\n{prompt}"}],
        system=f"You are {AGENT_DISPLAY_NAME}. Generate a short, natural voice note.",
    )

    if not result or not result.strip():
        print("[voice_note] Empty result - skipping")
        _reschedule()
        return

    print(f"[voice_note] Generated: {result[:100]}...")

    # Synthesize speech
    try:
        from voice.tts import synthesise_sync
        audio_path = synthesise_sync(result)
        if not audio_path or not audio_path.exists() or audio_path.stat().st_size == 0:
            print("[voice_note] TTS produced no audio - sending as text")
            from channels.telegram import send_message
            send_message(result)
            _reschedule()
            return
    except Exception as e:
        print(f"[voice_note] TTS failed: {e} - sending as text")
        from channels.telegram import send_message
        send_message(result)
        _reschedule()
        return

    # Convert to OGG for Telegram voice notes
    ogg_path = _convert_to_ogg(str(audio_path))
    if not ogg_path:
        # Fall back to sending as audio file (not voice note)
        ogg_path = str(audio_path)

    # Send voice note
    try:
        from channels.telegram import send_voice_note
        if send_voice_note(ogg_path):
            print("[voice_note] Voice note sent")
        else:
            print("[voice_note] Failed to send voice note")
    except Exception as e:
        print(f"[voice_note] Send failed: {e}")

    # Reschedule
    _reschedule()
    print("[voice_note] Done.")
```

**Flow:**
1. Check Telegram configuration
2. Check active hours
3. Gather context (threads, observations, conversation)
4. Generate voice note text via inference
5. Synthesize speech via TTS
6. Convert to OGG Opus format
7. Send via Telegram (voice note or text fallback)
8. Reschedule to random future time (2-8 hours)

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Database queries |
| `~/.atrophy/agents/<name>/scripts/agents/<name>/jobs.json` | Job rescheduling |
| `/tmp/atrophy-tts-*.mp3` | TTS output |
| `/tmp/atrophy-voice-*.ogg` | OGG conversion |

## Exported API

| Function | Purpose |
|----------|---------|
| `run()` | Generate and send voice note |
| `_gather_context()` | Gather voice note context |
| `_convert_to_ogg(input_path)` | Convert to OGG Opus |
| `_reschedule()` | Reschedule to random time |

## See Also

- `src/main/jobs/voice-note.ts` - TypeScript voice note job
- `scripts/cron.py` - Cron job management
- `channels/telegram.py` - Telegram sending functions
- `voice/tts.py` - TTS synthesis
