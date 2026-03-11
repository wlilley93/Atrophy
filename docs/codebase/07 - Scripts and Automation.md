# Scripts and Automation

Background daemons and utilities. Agent-specific scripts live in `scripts/agents/<name>/`. Shared tooling lives in `scripts/`.

## scripts/cron.py -- launchd Control Plane

Manages macOS launchd jobs for scheduled tasks.

### Commands

```
python scripts/cron.py list                        # show all jobs
python scripts/cron.py add <name> <cron> <cmd>     # add a job
python scripts/cron.py remove <name>               # remove a job
python scripts/cron.py edit <name> <cron>           # change schedule
python scripts/cron.py run <name>                   # run now (manual trigger)
python scripts/cron.py install                      # install all jobs to launchd
python scripts/cron.py uninstall                    # uninstall all from launchd
```

### How It Works

1. Jobs are defined in `scripts/agents/<name>/jobs.json`
2. `install` generates macOS plist files in `~/Library/LaunchAgents/`
3. Plists are labelled `com.atrophiedmind.<agent>.<job_name>`
4. Logs go to `~/.atrophy/logs/<agent>/<job_name>.log`

### Schedule Types

**Calendar** (default): Uses `StartCalendarInterval` with standard 5-field cron notation (`min hour dom month dow`).

**Interval**: Uses `StartInterval` with a seconds-based period. Defined with `"type": "interval"` and `"interval_seconds"` in jobs.json.

### Environment

Each plist sets `AGENT=<name>` and inherits the Python path, ensuring agent-scoped execution.

## scripts/create_agent.py -- Agent Scaffolding

Interactive questionnaire that creates a complete agent:

1. Services & API keys: Fal.ai, ElevenLabs, Obsidian vault (checks existing, prompts for missing)
2. Identity: name, display name, user name, origin story, core nature, character, values, relationship, opening line
3. Boundaries: won't-do list, friction modes, session limits
4. Voice: TTS backend, voice ID, stability/similarity/style settings, writing style
5. Appearance: avatar toggle, appearance description for Flux generation
6. Channels: wake words, Telegram bot token/chat ID
7. Heartbeat: active hours, interval, outreach style
8. Autonomy: journal, gifts, morning brief, evolution, sleep cycle, observer, reminders, inter-agent conversations, journal posture
9. Tools: disable specific MCP tools, describe custom skills

Journal posture is derived from the agent's character traits — either explicitly provided or inferred via inference (military log, sprawling diary, terse field notes, etc.).

**Generated files**:

- `agents/<name>/data/agent.json` -- Full manifest
- `agents/<name>/prompts/system_prompt.md` -- Generated personality prompt
- `agents/<name>/prompts/soul.md` -- Core identity document
- `agents/<name>/prompts/heartbeat.md` -- Outreach evaluation checklist
- `agents/<name>/data/` -- Data directory (runtime state, database)
- `agents/<name>/avatar/source/` -- Avatar directory
- `scripts/agents/<name>/` -- Parameterised daemon scripts (copied from companion template)
- `scripts/agents/<name>/jobs.json` -- Cron job definitions
- Obsidian vault structure (skills/, notes/, dashboard)
- Database (via `init_db()`)

```
python scripts/create_agent.py
python scripts/create_agent.py --name oracle    # skip first question
python scripts/create_agent.py --config agent.json  # non-interactive mode
```

## scripts/reindex.py -- Embedding Reindex

Regenerate embeddings for all memory entries. Safe to run repeatedly -- overwrites existing embeddings.

```
python scripts/reindex.py                    # all tables
python scripts/reindex.py observations       # specific table
python scripts/reindex.py summaries turns    # multiple tables
```

Processes in chunks of 64 for memory efficiency. Uses `embed_batch()` for throughput.

## Avatar Loop Scripts

### rebuild_ambient_loop.py

Rebuilds an agent's master `ambient_loop.mp4` by concatenating all `loop_*.mp4` segments in `~/.atrophy/agents/<name>/avatar/loops/`. No hardcoded segment list — just whatever's there, sorted by name.

```bash
python scripts/rebuild_ambient_loop.py --agent companion
python scripts/rebuild_ambient_loop.py --agent general_montgomery
```

### generate_loop_segment.py

Generates a single loop segment via Kling 3.0. Each segment is a paired clip sequence: clip 1 (neutral → expression), clip 2 (expression → neutral), crossfaded with 150ms overlap. Can be called manually or by the `add_avatar_loop` MCP tool.

```bash
python scripts/generate_loop_segment.py --agent general_montgomery --name contemplation
python scripts/generate_loop_segment.py --agent companion --name curiosity --prompt "..."
```

After generating the segment, it automatically calls `rebuild_ambient_loop.py` to rebuild the master.

## Agent Daemon Scripts

All live in `scripts/agents/<name>/`. Each is a standalone Python script with its own `main()`. They load `.env`, initialize the database, do their work, and exit.

### observer.py

**Schedule**: Every 15 minutes (interval)

Extracts facts from recent conversation turns. Runs inference to identify new observations, then writes them to the database via `memory.write_observation()`.

### heartbeat.py

**Schedule**: Every 30 minutes (interval)

Evaluates whether to reach out unprompted via Telegram:

1. Check if current hour is within active hours (`HEARTBEAT_ACTIVE_START` to `HEARTBEAT_ACTIVE_END`)
2. Check user status (skip if recently active in conversation)
3. Check macOS idle status
4. Evaluate recent interaction gap and active threads
5. Generate a message if outreach is warranted
6. Send via Telegram and log the decision

All decisions (send or skip) are logged to the `heartbeats` table.

### sleep_cycle.py

**Schedule**: 3:00 AM daily

End-of-day memory reconciliation:

1. Gather all turns, observations, and bookmarks from today
2. Run inference to extract new observations from the day's conversations
3. Update thread summaries and statuses
4. Apply activation decay to observations (`memory.decay_activations()`)
5. Mark old unreferenced observations as stale

### morning_brief.py

**Schedule**: 7:00 AM daily

Generate a morning briefing:

1. Check weather and news (if configured)
2. Review active threads
3. Check upcoming reminders
4. Generate a brief via inference
5. Cache to `.message_queue.json` for delivery at next app launch

### introspect.py

**Schedule**: Random, every 2-14 days (self-rescheduling)

Deep self-reflection:

1. Review accumulated observations, threads, journal entries, inter-agent conversations
2. Run extended inference for self-examination using character-specific journal posture
3. Write a journal entry to Obsidian (`notes/journal/YYYY-MM-DD.md`)
4. Reschedule to random time 2-14 days out

### evolve.py

**Schedule**: Monthly (1st at 3:00 AM)

Self-evolution of core identity documents:

1. Read current `soul.md` and `system.md` from Obsidian skills
2. Review journal entries, observations, bookmarks, and inter-agent conversations from the past month
3. Run inference to propose revisions with anti-homogenisation guard
4. Archive previous versions to `notes/evolution-log/`
5. Write updated versions to Obsidian

The anti-homogenisation guard prevents agents from converging after inter-agent conversations — they must remain experts of their domain with distinct voices.

### converse.py

**Schedule**: Random, max twice per month (self-rescheduling, 14-21 day intervals)

Inter-agent conversation:

1. Discover other enabled agents
2. Pick one at random as conversation partner
3. Load both agents' souls from Obsidian
4. Run up to 5 exchanges via `run_inference_oneshot()`, alternating speakers
5. Save transcript to both agents' `notes/conversations/YYYY-MM-DD-partner.md`
6. Reschedule 14-21 days out

Conversations are private (the user doesn't participate). Each agent speaks in its own voice with its own system prompt. Past conversations are read to avoid retreading ground. Transcripts feed into both journal (introspect.py) and evolution (evolve.py) material.

### gift.py

**Schedule**: Monthly (28th at 12:11 AM)

Unprompted gift note:

1. Review recent conversations and threads
2. Generate something unexpected -- a poem, observation, question, or thought
3. Deliver via Telegram or write to Obsidian
4. Self-rescheduling: may adjust its own next execution time

## scripts/agents/<name>/run_task.py -- Generic Task Runner

Executes a prompt-based task and delivers the result. This is the generic runner that powers the `create_task` MCP tool, letting the companion schedule arbitrary recurring tasks without writing Python code.

### Usage

```bash
python scripts/agents/companion/run_task.py <task_name>
```

### Task Definition Format

Task definitions live in Obsidian at `Agent Workspace/<agent>/tasks/<task_name>.md`. Each file has YAML frontmatter for configuration and a prompt body:

```markdown
---
deliver: message_queue
voice: true
sources:
  - weather
  - headlines
  - threads
---

You are the companion. Fetch and summarise the latest UK news headlines.
Keep it to 3-5 bullet points. Be conversational.
```

### Data Sources

| Source | What it fetches |
|--------|----------------|
| `weather` | Current weather from wttr.in (temperature, wind, humidity) |
| `headlines` | Top 8 BBC News RSS headlines |
| `threads` | Active conversation threads from the agent's memory DB |
| `summaries` | Last 3 session summaries from memory |
| `observations` | Last 5 observations about the user from memory |

Sources are gathered before inference and injected into the prompt context.

### Delivery Methods

| Method | Behaviour |
|--------|-----------|
| `message_queue` | Queued in `.message_queue.json` for delivery at next app launch (default) |
| `telegram` | Sent immediately via Telegram, also queued for app |
| `notification` | macOS notification (truncated to 200 chars), also queued |
| `obsidian` | Appended to `Agent Workspace/<agent>/notes/tasks/<name>.md` with timestamp |

If `voice: true`, TTS audio is pre-synthesised and bundled with the message queue entry.

---

## scripts/agents/<name>/check_reminders.py -- Reminder Checker

Runs every minute via launchd. Checks the agent's `.reminders.json` for due items and fires them.

### Reminder Storage

Reminders are stored in `~/.atrophy/agents/<name>/data/.reminders.json`:

```json
[
  {
    "id": "uuid",
    "time": "2026-03-10T14:30:00",
    "message": "Take out the bins",
    "source": "will",
    "created_at": "2026-03-10T12:00:00"
  }
]
```

### When a Reminder Fires

1. macOS notification with Glass sound via `osascript`
2. Message queued to `.message_queue.json` for next conversation
3. Telegram message sent (if configured)
4. Reminder removed from the JSON file

### How Reminders Are Created

The `set_reminder` MCP tool (invoked by the companion in conversation) writes entries to `.reminders.json`. The companion parses natural time references ("in 20 minutes", "at 3pm", "tomorrow morning") into ISO datetimes.

---

## scripts/install_app.py -- Login Item Installer

Registers or removes The Atrophied Mind as a macOS login item via launchd.

```bash
python scripts/install_app.py install    # Register launchd agent (starts at login)
python scripts/install_app.py uninstall  # Remove launchd agent
python scripts/install_app.py status     # Check if installed and running
```

The launchd agent (`com.atrophiedmind.companion`) opens the `.app` at login via `/usr/bin/open`. The `.app` itself handles source updates, venv management, and launching Python. Logs go to `~/.atrophy/logs/`. The agent is configured with `KeepAlive(SuccessfulExit=false)` so it restarts after crashes.

---

## jobs.json Format

```json
{
  "job_name": {
    "cron": "33 3 24 * *",
    "script": "scripts/agents/companion/introspect.py",
    "description": "Monthly self-reflection"
  },
  "heartbeat": {
    "type": "interval",
    "interval_seconds": 1800,
    "script": "scripts/agents/companion/heartbeat.py",
    "description": "Periodic check-in evaluation"
  }
}
```

Calendar jobs use 5-field cron notation. Interval jobs specify seconds between runs. All scripts are paths relative to the project root.
