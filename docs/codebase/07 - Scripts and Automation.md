# Scripts and Automation

Background jobs and utilities. All TypeScript job modules live in `src/main/jobs/`. Shared tooling lives in `src/main/`. Python scripts that remain as subprocesses live in `mcp/` and `scripts/`.

## src/main/cron.ts - launchd Control Plane

Manages macOS launchd jobs for scheduled tasks.

### API

```typescript
import { listJobs, addJob, removeJob, editJobSchedule, runJobNow, installAllJobs, uninstallAllJobs, toggleCron } from './cron';

listJobs()                                          // show all jobs
addJob('name', '30 7 * * *', 'script.py', 'desc')  // add a job
removeJob('name')                                   // remove a job
editJobSchedule('name', '0 8 * * *')                // change schedule
runJobNow('name')                                   // run now (manual trigger)
installAllJobs()                                    // install all jobs to launchd
uninstallAllJobs()                                  // uninstall all from launchd
toggleCron(true)                                    // install or uninstall all
```

### How It Works

1. Jobs are defined in `scripts/agents/<name>/jobs.json`
2. `installAllJobs()` generates macOS plist files in `~/Library/LaunchAgents/`
3. Plists are labelled `com.atrophiedmind.<agent>.<job_name>`
4. Logs go to the bundle root `logs/<agent>/<job_name>.log`

### Schedule Types

**Calendar** (default): Uses `StartCalendarInterval` with standard 5-field cron notation (`min hour dom month dow`).

**Interval**: Uses `StartInterval` with a seconds-based period. Defined with `"type": "interval"` and `"interval_seconds"` in jobs.json.

### Plist Generation

The `generatePlist()` function builds a `PlistDict` object and serialises it to XML via a minimal hand-built serialiser (no plist library dependency). Each plist includes:

- `ProgramArguments` - Python path and script path
- `WorkingDirectory` - bundle root
- `EnvironmentVariables` - `PATH` and `AGENT` name
- `StandardOutPath` / `StandardErrorPath` - log file paths

### Environment

Each plist sets `AGENT=<name>` and inherits the Python path, ensuring agent-scoped execution.

## src/main/create-agent.ts - Agent Scaffolding

Programmatic agent creation that builds a complete agent directory structure. Unlike the Python version's 9-step interactive questionnaire, the TypeScript version accepts a typed `CreateAgentOptions` object for non-interactive use (called from the setup wizard or IPC).

### CreateAgentOptions Interface

The full set of fields accepted by `createAgent()`:

| Group | Field | Type | Notes |
|-------|-------|------|-------|
| **Naming** | `name` | `string?` | Internal slug (lowercase, underscores). Derived from `displayName` if omitted. |
| | `displayName` | `string` | Human-readable display name. **Required.** |
| | `description` | `string?` | Short description for roster display (truncated to 120 chars). |
| | `userName` | `string?` | Name of the human user (default: `'User'`). |
| **Identity** | `originStory` | `string?` | 2-3 sentence origin narrative. |
| | `coreNature` | `string?` | What the agent fundamentally is. |
| | `characterTraits` | `string?` | Temperament, edges, how they talk. |
| | `values` | `string?` | What they care about. |
| | `relationship` | `string?` | How they relate to the user. |
| **Boundaries** | `wontDo` | `string?` | Refusal list - what they will not do. |
| | `frictionModes` | `string?` | How they push back when the user is avoiding something. |
| | `sessionLimitBehaviour` | `string?` | What happens at the soft time limit. |
| | `softLimitMins` | `number?` | Session soft limit in minutes (default: 60). |
| **Voice** | `openingLine` | `string?` | First words the agent ever says. |
| | `writingStyle` | `string?` | How they write - register, tone, length. |
| | `voice` | `VoiceConfig?` | TTS settings: `ttsBackend`, `elevenlabsVoiceId`, `elevenlabsModel`, `elevenlabsStability`, `elevenlabsSimilarity`, `elevenlabsStyle`, `falVoiceId`, `playbackRate`. |
| **Appearance** | `appearance` | `AppearanceConfig?` | `hasAvatar`, `appearanceDescription`, `avatarResolution`. |
| **Channels** | `wakeWords` | `string[]?` | Wake word phrases (default: `['hey <name>', '<name>']`). |
| | `telegramEmoji` | `string?` | Emoji prefix for Telegram messages. |
| | `telegramBotToken` | `string?` | Telegram bot token (stored as env key reference). |
| | `telegramChatId` | `string?` | Telegram chat ID (stored as env key reference). |
| **Heartbeat** | `heartbeatActiveStart` | `number?` | Hour to start outreach checks (default: 9). |
| | `heartbeatActiveEnd` | `number?` | Hour to stop outreach checks (default: 22). |
| | `heartbeatIntervalMins` | `number?` | Minutes between heartbeat checks (default: 30). |
| | `outreachStyle` | `string?` | Agent-specific outreach personality notes. |
| **Tools** | `tools` | `ToolsConfig?` | `disabledTools` (MCP tool names to block) and `customSkills` (array of `{ name, description }` pairs written to skills dir). |

### What It Creates

1. **Directories** under `~/.atrophy/agents/<name>/`:
   - `data/` - agent.json manifest + memory.db
   - `prompts/` - system.md, soul.md, heartbeat.md
   - `avatar/` - source/, loops/, candidates/
   - `audio/` - TTS cache and recordings
   - `skills/` - system.md, soul.md, custom skill files, tools reference
   - `notes/` - reflections, threads, journal/, evolution-log/, conversations/, tasks/
   - `state/` - runtime state files

2. **agent.json** - Full manifest with identity, voice, telegram, display, heartbeat, avatar, and disabled tools configuration

3. **Prompt documents** - Template-based generation:

| Function | Output | Content | Scale |
|----------|--------|---------|-------|
| `generateSystemPrompt()` | `prompts/system.md` | Operating manual with Origin, Who You Are, Character, Relationship, Values, Constraints, Friction, Voice, Capabilities (CONVERSATION, MEMORY, RESEARCH, REFLECTION, WRITING, SCHEDULING, MONITORING), Session Behaviour, Opening Line | Template-based, ~500-800 words |
| `generateSoul()` | `prompts/soul.md` | First-person working notes - origin, nature, character, constraints, push-back style, values, relationship, writing style | Template-based, ~300-500 words |
| `generateHeartbeat()` | `prompts/heartbeat.md` | Outreach evaluation checklist with timing, unfinished threads, agent-specific considerations, and the real question ("would hearing from you right now feel like a gift, or like noise?") | Template-based, ~200-300 words |

Unlike the Python version, the Electron version does **not** have `generateGiftMd()` or `generateMorningBriefMd()` functions. Python's create_agent generates 5 prompt documents; the Electron version generates 3. The gift and morning-brief prompts are instead loaded at runtime from Obsidian skills files or from task definitions.

All three generators use template interpolation with the `CreateAgentOptions` fields. Sections that have no input are filled with `(To be written.)` placeholders. There is no LLM-expanded generation step - the templates are the final output. This differs from the Python version, which uses `run_inference_oneshot()` to expand sparse questionnaire fields into richly detailed, character-specific documents (1000-2500 words for the system prompt). The intent is that the setup wizard's Xan conversation gathers richer input upfront, and the evolve.ts daemon expands the documents over time.

4. **Skills copies** - system.md and soul.md duplicated to `skills/` for Obsidian workspace access. Custom skills from `tools.customSkills` are written as individual markdown files (slugified names).

5. **Starter notes** - reflections.md, for-<user>.md, threads.md, journal-prompts.md, gifts.md

6. **Database** - SQLite database initialised from `db/schema.sql`

**Generated files summary:**

- `~/.atrophy/agents/<name>/data/agent.json` - Full manifest
- `~/.atrophy/agents/<name>/prompts/system.md` - Template-generated personality prompt (includes a `## Capabilities` section listing labeled strengths like CONVERSATION, MEMORY, RESEARCH)
- `~/.atrophy/agents/<name>/prompts/soul.md` - Template-generated first-person identity document
- `~/.atrophy/agents/<name>/prompts/heartbeat.md` - Template-generated outreach evaluation checklist
- `~/.atrophy/agents/<name>/skills/system.md` - Copy of system prompt for Obsidian workspace
- `~/.atrophy/agents/<name>/skills/soul.md` - Copy of soul doc for Obsidian workspace
- `~/.atrophy/agents/<name>/skills/<custom-skill>.md` - One per custom skill (if any)
- `~/.atrophy/agents/<name>/notes/reflections.md` - Starter reflections scratchpad
- `~/.atrophy/agents/<name>/notes/for-<user>.md` - Scratchpad for things to share
- `~/.atrophy/agents/<name>/notes/threads.md` - Active threads tracker
- `~/.atrophy/agents/<name>/notes/journal-prompts.md` - Journal prompts scratchpad
- `~/.atrophy/agents/<name>/notes/gifts.md` - Gifts and notes scratchpad
- `~/.atrophy/agents/<name>/data/memory.db` - SQLite database from schema.sql

Note: The Python version also creates an Obsidian vault structure (`skills/`, `notes/`, dashboard) and parameterised daemon scripts under `scripts/agents/<name>/`. The Electron version does not scaffold Obsidian vault directories or daemon scripts during agent creation - Obsidian integration is resolved dynamically at runtime via `prompts.ts`, and daemon scripts are handled by the job framework.

### Usage

```typescript
import { createAgent, CreateAgentOptions } from './create-agent';

const manifest = createAgent({
  displayName: 'Oracle',
  userName: 'Will',
  description: 'A contemplative agent',
  originStory: '...',
  coreNature: '...',
  characterTraits: '...',
  values: '...',
  relationship: '...',
  wontDo: '...',
  frictionModes: '...',
  writingStyle: '...',
  openingLine: 'What are you avoiding?',
  voice: { ttsBackend: 'elevenlabs', elevenlabsVoiceId: '...' },
  heartbeatActiveStart: 9,
  heartbeatActiveEnd: 22,
});
```

The function returns the generated `AgentManifest` object. If `name` is not provided, it is derived from `displayName` via slugification. All file writes use `writeIfMissing()` - existing files are not overwritten, making the function safe to re-run.

## Background Job Framework

All background jobs use a common runner framework defined in `src/main/jobs/index.ts`.

### Job Runner

```typescript
export interface JobDefinition {
  name: string;
  description: string;
  gates: GateCheck[];
  run: () => Promise<string>;
}

export async function runJob(name: string, agent?: string): Promise<JobResult>
```

The runner handles:
- Agent-scoped config reloading
- Pre-run gate checks (e.g. active hours, user status)
- Error capture and structured result reporting
- Logging with duration tracking

### CLI Entry Point

Jobs can be invoked from launchd via:

```bash
electron . --job=heartbeat --agent=companion
```

The `runJobFromCli()` function parses `--job` and `--agent` flags, runs the job, and exits with the appropriate code.

### Common Gates

- `activeHoursGate()` - only runs during the agent's configured active hours (`HEARTBEAT_ACTIVE_START` to `HEARTBEAT_ACTIVE_END`)

## Agent Background Jobs

All live in `src/main/jobs/`. Each is a TypeScript module that registers with the job framework and can run both as a standalone launchd script and as an imported function from the main process.

### observer.ts

**Schedule**: Every 15 minutes (interval)

Extracts facts from recent conversation turns. Uses `runInferenceOneshot()` with Haiku at low effort to identify new observations, then writes them to the database via `writeObservation()`. Also runs entity extraction on turns longer than 50 characters.

Tracks state in `~/.atrophy/agents/<name>/state/.observer_state.json` (last processed turn ID). Most runs are no-ops when there are no new turns.

### heartbeat.ts

**Schedule**: Every 30 minutes (interval)

Evaluates whether to reach out unprompted via Telegram:

1. Check gate: active hours, user away status
2. Load HEARTBEAT.md checklist from Obsidian skills (fallback to prompts dir)
3. Gather context: last interaction time, recent turn count, active threads, session summaries, observations
4. Run inference via `streamInference()` with full tool access (can use memory tools for context)
5. Parse structured response: `[REACH_OUT]`, `[HEARTBEAT_OK]`, or `[SUPPRESS]`
6. If reaching out: send notification, queue message, send via Telegram only if Mac is idle

All decisions (send or skip) are logged to the `heartbeats` table.

### sleep-cycle.ts

**Schedule**: 3:00 AM daily

End-of-day memory reconciliation:

1. Gather all turns, observations, and bookmarks from today
2. Run inference with Haiku to extract structured output: `[FACTS]`, `[THREADS]`, `[PATTERNS]`, `[IDENTITY]`
3. Store new facts as observations with confidence scores
4. Update thread summaries
5. Store patterns as observations
6. Queue identity flags for review
7. Mark old unreferenced observations as stale (>30 days)
8. Apply activation decay to observations (`decayActivations()` with 30-day half-life)
9. Restore emotional baselines (frustration drains, warmth/confidence/connection nudge toward 0.5)

### morning-brief.ts

**Schedule**: 7:00 AM daily

Generate a morning briefing:

1. Fetch weather from wttr.in (plain text, no dependencies)
2. Fetch BBC News RSS headlines (lightweight XML title extraction)
3. Review active threads, recent session summaries, observations
4. Read companion reflections from Obsidian
5. Generate brief via `runInferenceOneshot()` using the `morning-brief` prompt
6. Pre-synthesise TTS audio via `synthesiseSync()`
7. Send via Telegram, fire macOS notification
8. Queue to `.message_queue.json` with audio for delivery at next app launch

### introspect.ts

**Schedule**: Random, every 2-14 days (self-rescheduling)

Deep self-reflection with full database access:

1. Gather the complete record: session arc (first session, total count, mood distribution, notable sessions), all threads, all observations, all bookmarks, identity snapshots, conversation texture (significant turns), tool usage patterns, reflections, journal entries, inter-agent conversations
2. Run inference using character-specific journal posture from the `introspection` prompt
3. Write a journal entry to Obsidian (`notes/journal/YYYY-MM-DD.md`) with YAML frontmatter
4. Reschedule to random time 2-14 days out (1-5 AM)

### evolve.ts

**Schedule**: Monthly (1st at 3:00 AM)

Self-evolution of core identity documents:

1. Read current `soul.md` and `system.md` from Obsidian skills
2. Review journal entries, reflections, identity snapshots, bookmarks, and inter-agent conversations from the past month
3. Run inference with Sonnet at medium effort to propose revisions
4. Archive previous versions to `notes/evolution-log/` (date-stamped copies)
5. Write updated versions to Obsidian

The anti-homogenisation guard prevents agents from converging after inter-agent conversations - they must remain experts of their domain with distinct voices. The system prompt explicitly warns against adopting other agents' vocabulary or values.

### converse.ts

**Schedule**: Random, max twice per month (self-rescheduling, 14-21 day intervals)

Inter-agent conversation:

1. Discover other enabled agents via manifest scanning
2. Pick one at random as conversation partner
3. Load both agents' souls from Obsidian (fallback to repo prompts)
4. Read past conversations to avoid retreading ground
5. Run up to 5 exchanges via `runInferenceOneshot()`, alternating speakers
6. Save transcript with YAML frontmatter to both agents' `notes/conversations/YYYY-MM-DD-partner.md`
7. Reschedule 14-21 days out (1-5 AM)

Conversations are private (the user doesn't participate). Each agent speaks in its own voice with its own system prompt. Transcripts feed into both journal (introspect.ts) and evolution (evolve.ts) material.

### gift.ts

**Schedule**: Random, 3-30 days apart (self-rescheduling)

Unprompted gift note:

1. Access agent database directly: active threads, recent observations, bookmarks, recent Will turns
2. Read existing gifts from Obsidian to avoid repetition
3. Generate something unexpected via `runInferenceOneshot()` using the `gift` prompt
4. Write to Obsidian `notes/gifts.md` with timestamp and YAML frontmatter
5. Queue notification and macOS notification for discovery
6. Reschedule to random future time

### voice-note.ts

**Schedule**: Random, 2-8 hours apart (self-rescheduling, within active hours)

Spontaneous voice note via Telegram:

1. Gather context: active threads, recent observations, recent conversation turns
2. Generate a short thought via `runInferenceOneshot()` using the `voice-note` prompt
3. Enrich with sentiment/intent classification via a lightweight Haiku call
4. Synthesise speech via TTS
5. Convert to OGG Opus format via ffmpeg
6. Send as a Telegram voice note using `sendVoiceNote()` in `src/main/telegram.ts`
7. Store as an observation with sentiment/intent metadata
8. Clean up temp audio files
9. Self-reschedule to a random time 2-8 hours later (clamped to active hours)

Falls back to a text message if TTS synthesis or voice note sending fails.

### generate-avatar.ts

Avatar generation via Fal AI for face images and ElevenLabs for ambient audio.

**Pipeline stages** (`runFullAvatarPipeline(agentName)`):

1. **Face candidate generation** (`generateFace()`): Uses Fal AI's Flux model (`fal-ai/flux-general`) to generate face images.
   - If reference images exist in `avatar/Reference/`, uses the Flux IP-Adapter (`XLabs-AI/flux-ip-adapter`) for style guidance. Each reference image generates `perRef` candidates (default 3).
   - If no reference images, generates without IP adapter.
   - Appearance prompt, negative prompt, IP adapter scale, inference steps, guidance scale, and image dimensions are all configurable via the `appearance` field in `agent.json`.
   - Default prompt generates a hyper-realistic close-up selfie photograph.
   - Default negative prompt excludes cosmetic surgery, cartoon, airbrushed, and uncanny valley artefacts.
   - Candidates are saved to `avatar/candidates/` as PNG files for manual review.
   - The user copies their chosen face to `avatar/source/face.png` for use with the idle loop renderer.

2. **Ambient audio loop** (`generateAmbientLoop()`): Uses ElevenLabs TTS with the agent's voice to synthesise a soft breathing/ambient audio clip. The text is a sequence of ellipsis markers designed to produce near-silent breathing audio. Voice settings use elevated stability (+0.2) and zero style for minimal expression. Output saved to `avatar/audio/ambient_loop.mp3`.

3. **Trailing silence trim** (`trimStaticTails()`): After ambient audio generation, trailing silence is detected via `ffprobe`'s `silencedetect` filter (threshold: -40dB, minimum duration: 0.5s) and trimmed via `ffmpeg` with a 0.3s buffer and 0.5s fade-out. Skips gracefully if ffprobe/ffmpeg are not available.

Note: Unlike the Python version which uses Kling 3.0 for video loop segments (paired clip sequence with neutral-to-expression and expression-to-neutral transitions crossfaded with 150ms overlap), the Electron version generates static face images only. Video loop generation is not yet ported.

## src/main/jobs/run-task.ts - Generic Task Runner

Executes a prompt-based task and delivers the result. This is the generic runner that powers the `create_task` MCP tool, letting the companion schedule arbitrary recurring tasks without writing code.

### Usage

```bash
electron . --job=run_task --agent=companion
```

Or imported directly:

```typescript
import { runTask } from './jobs/run-task';
await runTask('morning_news');
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
| `headlines` | Top 8 BBC News RSS headlines (lightweight XML extraction) |
| `threads` | Active conversation threads from the agent's memory DB |
| `summaries` | Last 3 session summaries from memory |
| `observations` | Last 5 observations about the user from memory |

Sources are gathered before inference and injected into the prompt context. Weather and headlines use `fetch()` with 10-second timeouts.

### Delivery Methods

| Method | Behaviour |
|--------|-----------|
| `message_queue` | Queued in `.message_queue.json` for delivery at next app launch (default) |
| `telegram` | Sent immediately via Telegram, also queued for app |
| `notification` | macOS notification (truncated to 200 chars), also queued |
| `telegram_voice` | Synthesised as speech, converted to OGG Opus, sent as a Telegram voice note (falls back to text on failure) |
| `obsidian` | Appended to `Agent Workspace/<agent>/notes/tasks/<name>.md` with timestamp |

If `voice: true`, TTS audio is pre-synthesised via `synthesiseSync()` and bundled with the message queue entry.

---

## src/main/jobs/check-reminders.ts - Reminder Checker

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

1. macOS notification via `sendNotification()` (uses AppleScript `display notification` - note: unlike the Python version which includes `sound name "Glass"` for an alarm chime, the Electron version uses the default notification sound)
2. Message queued to `.message_queue.json` for next conversation
3. Telegram message sent (if configured)
4. Reminder removed from the JSON file

### How Reminders Are Created

The `set_reminder` MCP tool (invoked by the companion in conversation) writes entries to `.reminders.json`. The companion parses natural time references ("in 20 minutes", "at 3pm", "tomorrow morning") into ISO datetimes.

---

## Python Scripts (Remaining)

### scripts/google_auth.py - Google OAuth2 Setup

Manages Google OAuth2 credentials for Gmail and Calendar access. This stays as Python because it uses the Google client libraries.

```bash
python scripts/google_auth.py              # Authorize (opens browser for consent)
python scripts/google_auth.py --check      # Check if credentials are valid
python scripts/google_auth.py --revoke     # Revoke tokens and delete local file
```

OAuth client credentials are bundled at `config/google_oauth.json` (safe to ship - Google treats desktop app client IDs as public). The user authorizes via a browser consent screen. Tokens are stored at `~/.atrophy/.google/token.json` (directory 700, file 600).

Scopes: `gmail.readonly`, `gmail.send`, `gmail.modify`, `calendar.readonly`, `calendar.events`.

### MCP Servers (Python subprocesses)

`mcp/memory_server.py` and `mcp/google_server.py` remain as Python. They are spawned by the `claude` CLI over stdio and bundled as `extraResources` in the Electron app. See [05 - MCP Server](05%20-%20MCP%20Server.md) for details.

---

## src/main/install.ts - Login Item

Uses Electron's built-in `app.setLoginItemSettings()` instead of manual launchd plist generation.

```typescript
import { enableLoginItem, disableLoginItem, isLoginItemEnabled, toggleLoginItem } from './install';

isLoginItemEnabled()    // Check if registered as login item
enableLoginItem()       // Register (opens hidden with --app flag)
disableLoginItem()      // Remove
toggleLoginItem(true)   // Enable or disable
```

The app launches at login in menu bar mode (`--app` flag) with `openAsHidden: true`. No launchd plist, no manual process management - Electron handles registration with the system directly.

---

## Building and Distribution

Building uses `electron-builder` (configured in `electron-builder.yml`), not a custom Python build script. The builder handles:

- DMG and ZIP targets for macOS
- Hardened runtime for notarisation
- Extra resources bundling (whisper.cpp, MCP servers, scripts, agents, db schema)
- Auto-update via `electron-updater` + GitHub Releases

See [Building and Distribution](../guides/10%20-%20Building%20and%20Distribution.md) for full details.

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
