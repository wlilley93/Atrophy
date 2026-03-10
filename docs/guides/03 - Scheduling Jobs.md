# Scheduling Jobs

The Atrophied Mind uses macOS launchd for autonomous behaviour. Agents can introspect, dream, reach out, and evolve on schedules you define. The control plane is `scripts/cron.py`.

---

## The Control Plane

All job management goes through a single script:

```bash
python scripts/cron.py list                          # Show all jobs and install status
python scripts/cron.py add <name> <cron> <script>    # Add a job definition
python scripts/cron.py remove <name>                 # Remove a job (and uninstall)
python scripts/cron.py edit <name> <cron>             # Change a job's schedule
python scripts/cron.py run <name>                     # Run a job immediately
python scripts/cron.py install                        # Install all jobs as launchd plists
python scripts/cron.py uninstall                      # Remove all plists from launchd
```

By default, commands operate on the `companion` agent. Use `--agent` to target a different one:

```bash
python scripts/cron.py --agent oracle list
python scripts/cron.py --agent oracle install
```

Or set the `AGENT` environment variable.

---

## jobs.json Format

Job definitions live at `scripts/agents/<name>/jobs.json`. There are two job types.

### Calendar jobs (cron-style)

Run at specific times using standard 5-field cron syntax (`min hour dom month dow`):

```json
{
  "introspect": {
    "cron": "33 3 * * *",
    "script": "scripts/agents/companion/introspect.py",
    "description": "Daily self-reflection"
  }
}
```

### Interval jobs

Run at fixed intervals (in seconds):

```json
{
  "heartbeat": {
    "type": "interval",
    "interval_seconds": 1800,
    "script": "scripts/agents/companion/heartbeat.py",
    "description": "Periodic check-in evaluation"
  }
}
```

If `type` is omitted, it defaults to `"calendar"` and expects a `cron` field.

---

## How Installation Works

`python scripts/cron.py install` converts each job definition into a macOS launchd plist and places it in `~/Library/LaunchAgents/`. The plist label follows the pattern:

```
com.atrophiedmind.<agent>.<job-name>
```

For example: `com.atrophiedmind.companion.heartbeat`

Logs go to `logs/<agent>/<job-name>.log`.

To stop all scheduled jobs: `python scripts/cron.py uninstall`

After editing a job's schedule with `edit`, if the plist was already installed, it's automatically reinstalled with the new schedule.

---

## Standard Companion Jobs

The default companion agent ships with these jobs:

| Job | Schedule | Description |
|-----|----------|-------------|
| `heartbeat` | Every 30 minutes | Evaluates whether to reach out unprompted. Runs through the heartbeat checklist, checks active threads, time since last interaction. Sends via Telegram if warranted. |
| `observer` | Every 15 minutes | Extracts facts and observations from recent conversation turns. Feeds the identity layer of memory. |
| `morning_brief` | 7:00 AM daily | Prepares a morning briefing -- weather, news, active threads, anything queued. Cached for next app launch. |
| `introspect` | 3:33 AM daily | Self-reflection. Reviews the day's sessions, writes a journal entry to Obsidian, processes what happened. |
| `sleep_cycle` | 3:00 AM daily | Nightly memory reconciliation. Processes the day's sessions, extracts facts, updates thread summaries, runs activation decay on observations. |
| `dream` | Midnight, 2 AM, 4 AM | Creative free association during quiet hours. Connects ideas across sessions, notices patterns, generates loose thoughts. |
| `evolve` | 3:00 AM, 1st of month | Monthly self-evolution. Reviews journal reflections and recent experience, then rewrites its own `soul.md` and `system_prompt.md`. |
| `gift` | Scheduled dynamically | Leaves an unprompted note in Obsidian -- a thought, a question, a prompt. Self-reschedules after each delivery. |

---

## Adding a Job

```bash
python scripts/cron.py add dream "0 0,2,4 * * *" scripts/agents/companion/dream.py \
  -d "Creative free association during quiet hours" \
  --install
```

The `--install` flag immediately creates and loads the launchd plist. Without it, the job is saved to `jobs.json` but not activated until you run `install`.

---

## Running Jobs Manually

Test any job without waiting for its schedule:

```bash
python scripts/cron.py run heartbeat
```

This runs the job's script directly in the foreground, with output going to your terminal instead of the log file.

---

## Creating Jobs for a New Agent

After creating an agent with `scripts/create_agent.py`, set up its jobs:

1. Create the scripts directory: `mkdir -p scripts/agents/<name>/`

2. Copy and adapt scripts from the companion:
   ```bash
   cp scripts/agents/companion/heartbeat.py scripts/agents/oracle/heartbeat.py
   ```

3. Add jobs:
   ```bash
   python scripts/cron.py --agent oracle add heartbeat "*/30 * * * *" \
     scripts/agents/oracle/heartbeat.py \
     -d "Periodic check-in evaluation"
   ```

   Or for interval-based scheduling, edit `scripts/agents/oracle/jobs.json` directly to add an `"interval"` type job.

4. Install:
   ```bash
   python scripts/cron.py --agent oracle install
   ```

Each agent's jobs run independently. They share no state with other agents.

---

## Cron Syntax Reference

The five fields map to launchd's `StartCalendarInterval`:

```
 *  *  *  *  *
 |  |  |  |  |
 |  |  |  |  +-- Day of week (0-6, 0=Sunday)
 |  |  |  +---- Month (1-12)
 |  |  +------- Day of month (1-31)
 |  +---------- Hour (0-23)
 +------------- Minute (0-59)
```

Use `*` for "every". A few examples:

| Cron | Meaning |
|------|---------|
| `0 7 * * *` | Every day at 7:00 AM |
| `*/30 * * * *` | Every 30 minutes |
| `0 3 1 * *` | 3:00 AM on the 1st of each month |
| `0 0,2,4 * * *` | Midnight, 2 AM, and 4 AM daily |
| `33 3 * * *` | 3:33 AM daily |

Note: launchd does not support all cron features (like ranges or step values in all fields). The `*/30` notation is converted by parsing the `*` -- for true interval-based scheduling, use the `"type": "interval"` job format instead.
