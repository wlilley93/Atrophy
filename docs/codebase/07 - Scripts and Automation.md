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
4. Logs go to `logs/<agent>/<job_name>.log`

### Schedule Types

**Calendar** (default): Uses `StartCalendarInterval` with standard 5-field cron notation (`min hour dom month dow`).

**Interval**: Uses `StartInterval` with a seconds-based period. Defined with `"type": "interval"` and `"interval_seconds"` in jobs.json.

### Environment

Each plist sets `AGENT=<name>` and inherits the Python path, ensuring agent-scoped execution.

## scripts/create_agent.py -- Agent Scaffolding

Interactive questionnaire that creates a complete agent:

1. Identity: name, display name, user name, opening line
2. Voice: TTS backend, voice ID, stability/similarity/style settings
3. Behavior: active hours, heartbeat interval, wake words
4. Channels: Telegram bot token env var, chat ID env var
5. Obsidian: vault subdirectory name

**Generated files**:

- `agents/<name>/agent.json` -- Full manifest
- `agents/<name>/system_prompt.md` -- Generated personality prompt
- `agents/<name>/soul.md` -- Core identity document
- `agents/<name>/heartbeat.md` -- Outreach evaluation checklist
- `agents/<name>/state/` -- State directory
- `agents/<name>/avatar/source/` -- Avatar directory
- Obsidian vault structure
- Database (via `init_db()`)

```
python scripts/create_agent.py
python scripts/create_agent.py --name oracle    # skip first question
```

## scripts/reindex.py -- Embedding Reindex

Regenerate embeddings for all memory entries. Safe to run repeatedly -- overwrites existing embeddings.

```
python scripts/reindex.py                    # all tables
python scripts/reindex.py observations       # specific table
python scripts/reindex.py summaries turns    # multiple tables
```

Processes in chunks of 64 for memory efficiency. Uses `embed_batch()` for throughput.

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

### dream.py

**Schedule**: 12 AM, 2 AM, 4 AM (three times nightly)

Creative free association during quiet hours:

1. Pull recent memories, observations, threads
2. Run inference with a creative/associative prompt
3. Look for connections between unrelated ideas
4. Write dream log to `.dream_log.txt` and/or Obsidian

### introspect.py

**Schedule**: Monthly (24th at 3:33 AM)

Deep self-reflection:

1. Review accumulated observations, threads, journal entries
2. Run extended inference for self-examination
3. Write a journal entry to Obsidian
4. Optionally update identity snapshot

### evolve.py

**Schedule**: Monthly (1st at 3:00 AM)

Self-evolution of core identity documents:

1. Read current `soul.md` and `system_prompt.md`
2. Review journal entries, observations, and session patterns from the past month
3. Run inference to propose revisions
4. Write updated versions to both local files and Obsidian
5. The companion literally rewrites its own personality

### gift.py

**Schedule**: Monthly (28th at 12:11 AM)

Unprompted gift note:

1. Review recent conversations and threads
2. Generate something unexpected -- a poem, observation, question, or thought
3. Deliver via Telegram or write to Obsidian
4. Self-rescheduling: may adjust its own next execution time

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
