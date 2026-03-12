# Scripts and Automation

Background jobs and utilities. All TypeScript job modules live in `src/main/jobs/`. Shared tooling lives in `src/main/`. Python scripts that remain as subprocesses live in `mcp/` and `scripts/`.

---

## Table of Contents

1. [src/main/cron.ts - launchd Control Plane](#srcmaincronts---launchd-control-plane)
2. [src/main/create-agent.ts - Agent Scaffolding](#srcmaincreate-agentts---agent-scaffolding)
3. [src/main/jobs/index.ts - Job Runner Framework](#srcmainjobsindexts---job-runner-framework)
4. [src/main/jobs/observer.ts - Fact Extraction](#srcmainjobsobserverts---fact-extraction)
5. [src/main/jobs/heartbeat.ts - Periodic Check-In](#srcmainjobsheartbeatts---periodic-check-in)
6. [src/main/jobs/sleep-cycle.ts - Nightly Reconciliation](#srcmainjobssleep-cyclets---nightly-reconciliation)
7. [src/main/jobs/morning-brief.ts - Morning Briefing](#srcmainjobsmorning-briefts---morning-briefing)
8. [src/main/jobs/introspect.ts - Self-Reflection](#srcmainjobsintrospectts---self-reflection)
9. [src/main/jobs/evolve.ts - Monthly Self-Evolution](#srcmainjobsevolvets---monthly-self-evolution)
10. [src/main/jobs/converse.ts - Inter-Agent Conversation](#srcmainjobsconversets---inter-agent-conversation)
11. [src/main/jobs/gift.ts - Unprompted Gift Notes](#srcmainjobsgiftts---unprompted-gift-notes)
12. [src/main/jobs/voice-note.ts - Spontaneous Voice Notes](#srcmainjobsvoice-notets---spontaneous-voice-notes)
13. [src/main/jobs/generate-avatar.ts - Avatar Generation](#srcmainjobsgenerate-avatarts---avatar-generation)
14. [src/main/jobs/run-task.ts - Generic Task Runner](#srcmainjobsrun-taskts---generic-task-runner)
15. [src/main/jobs/check-reminders.ts - Reminder Checker](#srcmainjobscheck-remindersts---reminder-checker)
16. [src/main/install.ts - Login Item](#srcmaininstallts---login-item)
17. [Python Scripts (Remaining)](#python-scripts-remaining)
18. [jobs.json Format](#jobsjson-format)

---

## src/main/cron.ts - launchd Control Plane

Manages macOS launchd jobs for scheduled tasks. Port of `scripts/cron.py`.

### Exported Types

```typescript
export interface Job {
  cron?: string;               // 5-field cron string (min hour dom month dow)
  script: string;              // Path to script relative to BUNDLE_ROOT
  description?: string;        // Human-readable description
  args?: string[];             // Extra arguments passed after script path
  type?: 'calendar' | 'interval';  // Schedule type (default: 'calendar')
  interval_seconds?: number;   // Seconds between runs (for interval type)
}

export interface JobInfo extends Job {
  name: string;                // Job identifier
  installed: boolean;          // Whether plist exists in ~/Library/LaunchAgents/
  schedule: string;            // Human-readable schedule description
}
```

### Exported Functions

```typescript
export function listJobs(): JobInfo[]
```
Reads all jobs from `jobs.json`, checks whether each has an installed plist file in `~/Library/LaunchAgents/`, and returns an array of `JobInfo` objects. The `schedule` field is formatted as `"every Ns"` for interval jobs or the raw cron string for calendar jobs.

```typescript
export function addJob(
  name: string,
  cronStr: string,
  script: string,
  description?: string,   // default: ''
  install?: boolean,       // default: false
): void
```
Validates the cron string via `parseCron()` (throws on invalid format), adds the job to `jobs.json`, and optionally installs it to launchd immediately.

```typescript
export function removeJob(name: string): void
```
Uninstalls the job from launchd (if installed), removes it from `jobs.json`, and logs the action. No-op if the job does not exist.

```typescript
export function editJobSchedule(name: string, cronStr: string): void
```
Updates the cron expression for an existing job. Validates the new cron string. If the job is already installed (plist exists), uninstalls and reinstalls it with the new schedule. This is the function used by self-rescheduling jobs (introspect, converse, gift, voice-note).

```typescript
export function runJobNow(name: string): number
```
Runs a job immediately via `spawnSync()`. Executes `PYTHON_PATH <script> [args...]` with `AGENT=<name>` in the environment. Returns the process exit code (0 on success, 1 on failure or if job not found).

```typescript
export function installAllJobs(): void
export function uninstallAllJobs(): void
export function toggleCron(enabled: boolean): void
```
Bulk install/uninstall operations. `toggleCron(true)` calls `installAllJobs()`, `toggleCron(false)` calls `uninstallAllJobs()`.

### Internal Functions

**`labelPrefix(): string`** - Returns `com.atrophiedmind.<agent_name>.` using the current config's agent name.

**`jobsFile(): string`** - Returns the path to the jobs definition file: `<BUNDLE_ROOT>/scripts/agents/<agent_name>/jobs.json`.

**`logsDir(): string`** - Returns `<BUNDLE_ROOT>/logs/<agent_name>`. Created on install if missing.

**`plistPath(name: string): string`** - Returns `~/Library/LaunchAgents/com.atrophiedmind.<agent>.<name>.plist`.

**`loadJobs(): Record<string, Job>`** - Reads and parses `jobs.json`. Returns empty object if file is missing or malformed.

**`saveJobs(jobs: Record<string, Job>): void`** - Writes jobs to `jobs.json` with 2-space indentation. Creates parent directories if needed.

**`parseCron(cronStr: string): CalendarInterval`** - Parses a 5-field cron string into a launchd `CalendarInterval` object. Fields: `Minute`, `Hour`, `Day`, `Month`, `Weekday`. Wildcard (`*`) fields are omitted from the output. Throws `Error` if the string does not contain exactly 5 whitespace-separated fields.

### Plist Generation

The `generatePlist(name: string, job: Job): PlistDict` function builds a structured object with these fields:

| Key | Value |
|-----|-------|
| `Label` | `com.atrophiedmind.<agent>.<job_name>` |
| `ProgramArguments` | `[<PYTHON_PATH>, <resolved_script_path>, ...args]` |
| `WorkingDirectory` | `BUNDLE_ROOT` |
| `StandardOutPath` | `<BUNDLE_ROOT>/logs/<agent>/<job_name>.log` |
| `StandardErrorPath` | Same as stdout path (combined logging) |
| `EnvironmentVariables` | `{ PATH: "/usr/local/bin:/usr/bin:/bin:<python_dir>", AGENT: "<agent_name>" }` |
| `StartCalendarInterval` | Set for calendar jobs (from `parseCron()`) |
| `StartInterval` | Set for interval jobs (from `job.interval_seconds`) |

The job type defaults to `'calendar'` if `job.type` is not specified.

### XML Serialisation

The `plistToXml(plist: PlistDict): string` function is a minimal hand-built XML serialiser (no external plist library). It handles:
- `string` values as `<string>` elements
- `number` values as `<integer>` elements
- `boolean` values as `<true/>` or `<false/>`
- `Array` values as `<array>` with string items
- Nested `object` values as `<dict>` (recursive)

Output includes the standard Apple plist DTD declaration.

### Install/Uninstall Flow

1. `installJob(name, job)`: Creates logs directory, creates `~/Library/LaunchAgents/` directory, writes plist XML, runs `launchctl load <plist_path>`.
2. `uninstallJob(name)`: Checks plist exists, runs `launchctl unload <plist_path>`, deletes the plist file.

Both use `spawnSync('launchctl', ...)` with `stdio: 'pipe'` to suppress output.

### File I/O Summary

| Operation | Path | Format |
|-----------|------|--------|
| Read | `<BUNDLE_ROOT>/scripts/agents/<agent>/jobs.json` | JSON object of Job definitions |
| Write | Same path | Same format, 2-space indent |
| Write | `~/Library/LaunchAgents/com.atrophiedmind.<agent>.<job>.plist` | Apple plist XML |
| Delete | Same plist path | On uninstall |
| Create dir | `<BUNDLE_ROOT>/logs/<agent>/` | On install |

### Dependencies

- `child_process` (`execSync`, `spawnSync`) - launchctl commands
- `./config` (`getConfig`, `BUNDLE_ROOT`, `USER_DATA`)

---

## src/main/create-agent.ts - Agent Scaffolding

Programmatic agent creation that builds a complete agent directory structure. Unlike the Python version's 9-step interactive questionnaire, the TypeScript version accepts a typed `CreateAgentOptions` object for non-interactive use (called from the setup wizard or IPC).

### Exported Types

```typescript
export interface VoiceConfig {
  ttsBackend?: string;
  elevenlabsVoiceId?: string;
  elevenlabsModel?: string;
  elevenlabsStability?: number;    // default: 0.5
  elevenlabsSimilarity?: number;   // default: 0.75
  elevenlabsStyle?: number;        // default: 0.35
  falVoiceId?: string;
  playbackRate?: number;           // default: 1.12
}

export interface AppearanceConfig {
  hasAvatar?: boolean;
  appearanceDescription?: string;
  avatarResolution?: number;       // default: 512
}

export interface ToolsConfig {
  disabledTools?: string[];
  customSkills?: Array<{ name: string; description: string }>;
}

export interface CreateAgentOptions {
  name?: string;               // Internal slug (derived from displayName if omitted)
  displayName: string;         // REQUIRED - human-readable name
  description?: string;        // Truncated to 120 chars in manifest
  userName?: string;           // default: 'User'
  openingLine?: string;        // default: 'Hello.'
  wakeWords?: string[];        // default: ['hey <name>', '<name>']
  telegramEmoji?: string;
  originStory?: string;
  coreNature?: string;
  characterTraits?: string;
  values?: string;
  relationship?: string;
  wontDo?: string;
  frictionModes?: string;
  sessionLimitBehaviour?: string;  // default: 'Check in - are you grounded?...'
  softLimitMins?: number;          // default: 60
  writingStyle?: string;
  voice?: VoiceConfig;
  appearance?: AppearanceConfig;
  tools?: ToolsConfig;
  heartbeatActiveStart?: number;   // default: 9
  heartbeatActiveEnd?: number;     // default: 22
  heartbeatIntervalMins?: number;  // default: 30
  outreachStyle?: string;
  telegramBotToken?: string;
  telegramChatId?: string;
}

export interface AgentManifest {
  name: string;
  display_name: string;
  description: string;
  user_name: string;
  opening_line: string;
  wake_words: string[];
  telegram_emoji: string;
  voice: {
    tts_backend: string;
    elevenlabs_voice_id: string;
    elevenlabs_model: string;        // default: 'eleven_v3'
    elevenlabs_stability: number;
    elevenlabs_similarity: number;
    elevenlabs_style: number;
    fal_voice_id: string;
    playback_rate: number;
  };
  telegram: {
    bot_token_env: string;   // e.g. 'TELEGRAM_BOT_TOKEN_COMPANION'
    chat_id_env: string;     // e.g. 'TELEGRAM_CHAT_ID_COMPANION'
  };
  display: {
    window_width: number;    // always 622
    window_height: number;   // always 830
    title: string;           // 'ATROPHY - <displayName>'
  };
  heartbeat: {
    active_start: number;
    active_end: number;
    interval_mins: number;
  };
  avatar?: { description: string; resolution: number };
  disabled_tools?: string[];
}
```

### Exported Functions

```typescript
export function createAgent(opts: CreateAgentOptions): AgentManifest
```

Creates a new agent with all required directories, files, and database. Returns the generated `AgentManifest` object.

**Throws** `Error` if `name` cannot be derived (both `name` and `displayName` are empty).

**Idempotent**: All file writes use `writeIfMissing()` - existing files are not overwritten. The database is only initialised if `memory.db` does not exist. Safe to re-run.

### Internal Functions

**`slugify(name: string): string`** - Lowercases, trims, and replaces all non-alphanumeric/underscore characters with underscores.

**`ensureDir(dirPath: string): void`** - `fs.mkdirSync` with `{ recursive: true }`.

**`writeIfMissing(filePath: string, content: string): void`** - Creates parent directories and writes file only if it does not already exist.

**`buildManifest(opts, name): AgentManifest`** - Assembles the full manifest from options with defaults. Description is truncated to 120 characters (117 + `'...'`). Telegram env key references use the pattern `TELEGRAM_BOT_TOKEN_<NAME_UPPER>` and `TELEGRAM_CHAT_ID_<NAME_UPPER>`.

**`generateSystemPrompt(opts, name): string`** - Template-based system prompt (~500-800 words). Sections: Origin, Who You Are, Character, Relationship with user, Values, Constraints, Friction, Voice, Capabilities (CONVERSATION, MEMORY, RESEARCH, REFLECTION, WRITING, SCHEDULING, MONITORING), Session Behaviour, Opening Line. Unset sections use the placeholder `(To be written.)`.

**`generateSoul(opts): string`** - First-person working notes (~300-500 words). Sections: Where I Come From, What I Am, Character, What I Will Not Do, How I Push Back, Values, Relationship, How I Write.

**`generateHeartbeat(opts): string`** - Outreach evaluation checklist (~200-300 words). Sections: Timing, Unfinished Threads, Things You've Been Thinking About, Agent-Specific Considerations (from `outreachStyle`), The Real Question ("would hearing from you right now feel like a gift, or like noise?").

**`initDatabase(dbPath: string): void`** - Reads SQL from `<BUNDLE_ROOT>/db/schema.sql`, opens a new SQLite database via `better-sqlite3`, executes the schema, and closes the connection. Throws if schema file is missing.

### Directory Structure Created

Under `~/.atrophy/agents/<name>/`:

```
data/
  agent.json             # Full manifest (JSON, 2-space indent + trailing newline)
  memory.db              # SQLite database from schema.sql
prompts/
  system.md              # Generated system prompt
  soul.md                # Generated soul document
  heartbeat.md           # Generated heartbeat checklist
avatar/
  source/                # Empty - user places chosen face.png here
  loops/                 # Empty - for video loops (future)
  candidates/            # Empty - avatar generation writes here
audio/                   # Empty - TTS cache and recordings
skills/
  system.md              # Copy of system prompt for Obsidian workspace
  soul.md                # Copy of soul document for Obsidian workspace
  <custom-skill>.md      # One per custom skill (slugified names)
notes/
  reflections.md         # Starter: "# Reflections\n\n*<name>'s working reflections.*"
  for-<user>.md          # Starter: "# For <user>\n\n*Scratchpad for things to share.*"
  threads.md             # Starter: "# Active Threads\n\n*Ongoing conversations and topics.*"
  journal-prompts.md     # Starter: "# Journal Prompts\n\n*Prompts left for <user>.*"
  gifts.md               # Starter: "# Gifts\n\n*Notes and gifts left for <user>.*"
  journal/               # Empty - introspect.ts writes here
  evolution-log/         # Empty - evolve.ts archives here
  conversations/         # Empty - converse.ts writes here
  tasks/                 # Empty - run-task.ts writes here
state/                   # Empty - observer.ts writes state here
```

### Key Differences from Python Version

- Python version generates 5 prompt documents; Electron generates 3 (no `gift.md` or `morning-brief.md`)
- Python version uses `run_inference_oneshot()` to expand sparse fields into richly detailed documents (1000-2500 words). Electron version uses template interpolation only - no LLM expansion step
- Python version scaffolds Obsidian vault directories and daemon scripts. Electron version does not - Obsidian integration is resolved dynamically at runtime via `prompts.ts`, and daemon scripts are handled by the job framework

### Dependencies

- `better-sqlite3` - Database initialisation
- `./config` (`BUNDLE_ROOT`, `USER_DATA`)

---

## src/main/jobs/index.ts - Job Runner Framework

Common harness for all background jobs. Provides registration, gate checking, execution, and CLI entry point.

### Exported Types

```typescript
export interface JobResult {
  job: string;           // Job name
  ran: boolean;          // Whether the job executed (vs. being gated/skipped)
  outcome: string;       // Human-readable outcome
  durationMs: number;    // Duration in milliseconds
  error?: string;        // Error message if the job threw
}

export type GateCheck = () => string | null;
// Returns null if OK to proceed, or a reason string to skip

export interface JobDefinition {
  name: string;          // Unique identifier (e.g. 'heartbeat', 'evolve')
  description: string;   // Human-readable description
  gates: GateCheck[];    // Pre-run gate checks
  run: () => Promise<string>;  // Job logic, returns summary string
}
```

### Exported Functions

```typescript
export function registerJob(def: JobDefinition): void
```
Adds a job to the internal `Map<string, JobDefinition>` registry. Called at module load time by each job module.

```typescript
export function getRegisteredJobs(): JobDefinition[]
export function getJob(name: string): JobDefinition | undefined
```
Registry lookup functions.

```typescript
export async function runJob(name: string, agent?: string): Promise<JobResult>
```
Executes a registered job. Flow:
1. If `agent` is provided, calls `getConfig().reloadForAgent(agent)` to scope all config to that agent
2. Looks up the job in the registry. Returns `ran: false` with error if not found
3. Runs each gate check sequentially. If any returns a reason string, returns `ran: false` with that reason
4. Calls `def.run()`. Captures the outcome string on success or the error message on failure
5. Logs `[job:<name>]` messages with duration. Outcome is truncated to 120 characters in logs
6. **Never throws** - errors are captured in the `JobResult.error` field

```typescript
export async function runJobFromCli(argv: string[]): Promise<void>
```
Parses `--job=<name>` and `--agent=<agent>` from the argument array. Reloads config for the agent, runs the job, prints the result as formatted JSON, and calls `process.exit(0)` on success or `process.exit(1)` on error. Exits with code 1 and a usage message if `--job` is missing.

CLI invocation:
```bash
electron . --job=heartbeat --agent=companion
```

### Exported Gate Functions

```typescript
export function activeHoursGate(): string | null
```
Returns null if the current hour is within the agent's configured active window (`HEARTBEAT_ACTIVE_START` to `HEARTBEAT_ACTIVE_END`). Returns a reason string like `"Outside active hours (9-22)"` otherwise. Used by heartbeat and voice-note jobs.

### Dependencies

- `./config` (`getConfig`)

---

## src/main/jobs/observer.ts - Fact Extraction

Pre-compaction observer that extracts durable facts from recent conversation turns. Port of `scripts/agents/companion/observer.py`. Silent monitoring - no user-facing output.

### Schedule

Every 15 minutes (interval-based launchd job).

### Exported Functions

```typescript
export async function runObserver(agentName: string): Promise<void>
```

### Execution Flow

1. Reload config for the specified agent
2. Load state from `~/.atrophy/agents/<name>/state/.observer_state.json` (tracks `last_turn_id`)
3. Query the database for new turns since `last_turn_id` AND within the last 15 minutes
4. If no new turns, return immediately (fast path - most runs are no-ops)
5. Build a transcript, truncating each turn's content to 500 characters
6. Run inference via `runInferenceOneshot()` to extract observations
7. Update `last_turn_id` to the highest processed turn ID
8. Parse the response for `OBSERVATION:` lines with confidence scores
9. Store each observation via `writeObservation()` with `[observer]` prefix
10. Run entity extraction on all turns longer than 50 characters (best-effort, never blocks)

### Database Queries

**Get recent turns:**
```sql
SELECT id, role, content, timestamp FROM turns
WHERE id > ? AND timestamp > ?
ORDER BY timestamp
```
Parameters: `last_turn_id`, cutoff (15 minutes ago as `YYYY-MM-DD HH:MM:SS`).

Database is opened in readonly mode with `journal_mode = WAL`.

### Claude CLI Invocation

- Model: `claude-haiku-4-5-20251001`
- Effort: `low`
- System prompt: Static prompt instructing extraction of durable facts in `OBSERVATION: <fact> [confidence: X.X]` format, or `NOTHING_NEW` if nothing worth preserving

### Response Parsing

The `parseObservations()` function parses lines matching:
```
OBSERVATION: <statement> [confidence: X.X]
```
- Confidence regex: `/\[confidence:\s*([\d.]+)\]/`
- Default confidence if tag missing: `0.5`
- Confidence tag is stripped from the stored statement

### State File

Path: `~/.atrophy/agents/<name>/state/.observer_state.json`

```json
{ "last_turn_id": 42 }
```

Starts at `{ "last_turn_id": 0 }` if missing or corrupted. Updated after successful parsing (even if `NOTHING_NEW`).

### Error Handling

- Corrupted state file: starts fresh with `last_turn_id: 0`
- Inference failure: logs and returns (no state update)
- Empty response: logs and returns
- Entity extraction failure: silently caught, never blocks

### Constants and Thresholds

| Constant | Value | Purpose |
|----------|-------|---------|
| Lookback window | 15 minutes | Time cutoff for turn query |
| Content truncation | 500 chars | Per-turn content limit in transcript |
| Entity extraction threshold | 50 chars | Minimum turn length for entity extraction |
| Default confidence | 0.5 | When `[confidence: X.X]` tag is missing |

### Dependencies

- `better-sqlite3` - Direct database access (readonly)
- `../config` (`getConfig`, `USER_DATA`)
- `../inference` (`runInferenceOneshot`)
- `../memory` (`writeObservation`, `extractAndStoreEntities`)

---

## src/main/jobs/heartbeat.ts - Periodic Check-In

Evaluates whether to reach out to the user unprompted via Telegram and/or local notification. Port of `scripts/agents/companion/heartbeat.py`.

### Schedule

Every 30 minutes (interval-based launchd job).

### Job Registration

```typescript
registerJob({
  name: 'heartbeat',
  description: 'Periodic check-in - decides whether to reach out unprompted',
  gates: [activeHoursGate],
  run: async () => { ... },
});
```

### Exported Functions

```typescript
export async function runHeartbeat(agentName: string): Promise<string>
```

### Execution Flow

1. Reload config for the agent
2. **Gate: user status** - If `isAway()` returns true, logs `SUPPRESS` to heartbeats table and returns
3. **Gate: checklist** - Load `HEARTBEAT.md` from Obsidian skills dir, fallback to agent prompts dir. Skips if not found
4. Gather context (see below)
5. Get last CLI session ID for session continuity
6. Run inference with full tool access via `streamInference()` (not oneshot - the heartbeat can use memory tools)
7. Parse the response for one of three prefixes: `[REACH_OUT]`, `[HEARTBEAT_OK]`, `[SUPPRESS]`
8. Act on the decision (see below)

### Context Gathering

The `gatherContext()` function assembles:

| Section | Source | Query |
|---------|--------|-------|
| Last interaction | `getLastInteractionTime()` | From memory module |
| Recent session turn count | Direct DB query | `SELECT COUNT(*) FROM turns t JOIN sessions s ON t.session_id = s.id WHERE s.id = (SELECT MAX(id) FROM sessions)` |
| Active threads | `getActiveThreads()` | Top 5 threads |
| Recent sessions | `getRecentSummaries(3)` | Last 3 session summaries, truncated to 200 chars |
| Recent observations | `getRecentObservations(5)` | Last 5 observations |

### Checklist Loading

1. Try: `<OBSIDIAN_AGENT_DIR>/skills/HEARTBEAT.md`
2. Fallback: `<AGENT_DIR>/prompts/HEARTBEAT.md`
3. Returns empty string if neither exists

### Claude CLI Invocation

- Uses `streamInference()` (not oneshot) for full tool access
- System prompt: loaded via `loadSystemPrompt()` (the agent's full system prompt)
- Session ID: reuses last CLI session ID if available, otherwise cold start
- The agent can use tools like `recall`, `daily_digest`, `write_note` during evaluation

### Prompt Structure

The `HEARTBEAT_PROMPT` constant (hardcoded, ~400 chars) instructs the agent to:
- Review its state using memory tools
- Evaluate using the checklist
- Respond with exactly one prefix

### Response Handling

| Prefix | Action |
|--------|--------|
| `[REACH_OUT]` | Log to heartbeats table. If Mac is idle (`isMacIdle()`), send via Telegram. Always send macOS notification (truncated to 200 chars) and queue message with source `'heartbeat'` |
| `[HEARTBEAT_OK]` | Log reason to heartbeats table |
| `[SUPPRESS]` | Log reason to heartbeats table |
| Unknown format | Log first 500 chars to heartbeats table as `'UNKNOWN'` |

All decisions are logged via `logHeartbeat(decision, reason, message?)`.

### Error Handling

- Inference failure: logs `'ERROR'` to heartbeats table and throws
- Empty response: logs `'ERROR'` to heartbeats table and returns error string
- Telegram send failure: caught and logged, does not prevent local notification

### Dependencies

- `../config` (`getConfig`)
- `../memory` (`getDb`, `getActiveThreads`, `getRecentSummaries`, `getRecentObservations`, `getLastInteractionTime`, `getLastCliSessionId`, `logHeartbeat`)
- `../inference` (`streamInference`, event types)
- `../context` (`loadSystemPrompt`)
- `../status` (`isAway`, `isMacIdle`)
- `../notify` (`sendNotification`)
- `../queue` (`queueMessage`)
- `../telegram` (`sendMessage`)
- `./index` (`registerJob`, `activeHoursGate`)

---

## src/main/jobs/sleep-cycle.ts - Nightly Reconciliation

End-of-day memory consolidation - the companion's "sleep". Reviews the day's sessions and consolidates learnings into persistent memory. Port of `scripts/agents/companion/sleep_cycle.py`.

### Schedule

`0 3 * * *` - Daily at 3:00 AM.

### Exported Functions

```typescript
export async function sleepCycle(): Promise<void>
```

### Execution Flow

1. Call `initDb()` (required when running standalone via launchd)
2. Gather today's material (turns, observations, bookmarks, threads, summaries)
3. If no material: skip inference but still run maintenance (stale marking + decay + emotional restoration)
4. Run inference to extract structured output
5. Parse four sections from the response: `[FACTS]`, `[THREADS]`, `[PATTERNS]`, `[IDENTITY]`
6. Store facts as observations with confidence scores
7. Update thread summaries
8. Store patterns as observations
9. Queue identity flags for review
10. Mark stale observations and decay activations
11. Restore emotional baselines

### Material Gathering

The `gatherMaterial()` function collects:

| Section | Source | Details |
|---------|--------|---------|
| Today's conversation | `getTodaysTurns()` | All turns from today, content truncated to 500 chars |
| Today's observations | `getTodaysObservations()` | Observations created today |
| Today's bookmarks | `getTodaysBookmarks()` | Bookmarks with moment and optional quote |
| Active threads | `getActiveThreads()` | All active threads with summaries |
| Recent session summaries | `getRecentSummaries(5)` | Last 5 sessions, content truncated to 300 chars |

### Claude CLI Invocation

- Model: `claude-haiku-4-5-20251001`
- Effort: `low`
- System prompt: `RECONCILIATION_SYSTEM` constant (~300 chars) instructing consolidation with honest confidence levels

### Response Parsing

Four section parsers extract structured data:

**`parseFacts(section)`** - Parses lines starting with `FACT:`, extracts `[confidence: X.X]` tags. Default confidence: `0.5`.

**`parseThreads(section)`** - Parses lines starting with `THREAD:`, splits on `|` separator into `name` and `summary`.

**`parsePatterns(section)`** - Parses lines starting with `PATTERN:`, extracts description text.

**`parseIdentityFlags(section)`** - Parses lines starting with `IDENTITY_FLAG:`, extracts observation text.

Section headers are matched with regex: `\[<HEADER>\]\s*\n(.*?)(?=\n\[(?:FACTS|THREADS|PATTERNS|IDENTITY)\]|$)` (dotall mode).

### Storage Operations

| What | How | Prefix |
|------|-----|--------|
| Facts | `writeObservation(content, undefined, confidence)` | `[sleep-cycle]` |
| Thread updates | `updateThreadSummary(name, summary)` | N/A |
| Patterns | `writeObservation(content)` | `[pattern]` |
| Identity flags | Appended to JSON file at `config.IDENTITY_REVIEW_QUEUE_FILE` | Timestamped queue items with `reviewed: false` |

### Memory Maintenance

**Stale marking**: `markObservationsStale(30)` - Marks observations older than 30 days that were never incorporated.

**Activation decay**: `decayActivations(30)` - Applies exponential decay with 30-day half-life to observation activation scores.

### Emotional Restoration

The `restoreEmotionalBaselines()` function loads the agent's emotional state and applies overnight recovery:

| Emotion | Rule | Magnitude |
|---------|------|-----------|
| `frustration` | Drops toward 0.1 baseline | Multiplied by 0.5 (halved) if above 0.15 |
| `connection` | Nudges toward 0.5 | 30% of the difference to 0.5, if gap > 0.05 |
| `warmth` | Nudges toward 0.5 | Same |
| `confidence` | Nudges toward 0.5 | Same |

Also resets `session_tone` to `null` (cleared for the new day).

### Standalone Entry Point

```typescript
if (require.main === module) {
  sleepCycle()
    .then(() => process.exit(0))
    .catch((e) => { console.error(...); process.exit(1); });
}
```

### Dependencies

- `../config` (`getConfig`)
- `../inference` (`runInferenceOneshot`)
- `../memory` (`initDb`, `getActiveThreads`, `getRecentSummaries`, `getTodaysTurns`, `getTodaysObservations`, `getTodaysBookmarks`, `markObservationsStale`, `updateThreadSummary`, `writeObservation`, `decayActivations`)
- `../inner-life` (`loadState`, `saveState`, `EmotionalState`, `Emotions`)

---

## src/main/jobs/morning-brief.ts - Morning Briefing

Generates a morning briefing with weather, headlines, and context. Pre-synthesises TTS audio. Port of `scripts/agents/companion/morning_brief.py`.

### Schedule

`0 7 * * *` - Daily at 7:00 AM.

### Exported Functions

```typescript
export async function morningBrief(): Promise<void>
```

### Execution Flow

1. Call `initDb()` for standalone compatibility
2. Gather context (weather, headlines, threads, sessions, observations, reflections)
3. Run inference with the `morning-brief` prompt (loaded via `loadPrompt()`)
4. Pre-synthesise TTS audio via `synthesiseSync()`
5. Send via Telegram
6. Fire macOS notification (truncated to 200 chars)
7. Queue to message queue with audio for next app launch

### External API Calls

**Weather - wttr.in:**
```
GET https://wttr.in/Leeds?format=%C+%t+%w+%h
Headers: { User-Agent: 'curl/7.0' }
Timeout: 10 seconds (AbortSignal.timeout)
```
Returns plain text with condition, temperature, wind, humidity. Location is hardcoded to `'Leeds'` (parameter default).

**Headlines - BBC News RSS:**
```
GET https://feeds.bbci.co.uk/news/rss.xml
Headers: { User-Agent: 'curl/7.0' }
Timeout: 10 seconds (AbortSignal.timeout)
```
Parsed via lightweight regex extraction (no XML parser):
- Item regex: `/<item>[\s\S]*?<\/item>/g`
- Title regex: `/<title><!\[CDATA\[(.*?)\]\]><\/title>|<title>(.*?)<\/title>/`
- Limit: 5 headlines

### Context Assembly

| Section | Source | Details |
|---------|--------|---------|
| Weather | wttr.in API | Plain text condition |
| UK Headlines | BBC RSS | Up to 5 titles |
| Active threads | `getActiveThreads()` | Top 5 with summaries |
| Recent sessions | `getRecentSummaries(3)` | Last 3, content truncated to 200 chars |
| Recent observations | `getRecentObservations(5)` | Last 5 observation contents |
| Reflections | File read | `<OBSIDIAN_AGENT_NOTES>/notes/reflections.md`, last 800 chars |

### Claude CLI Invocation

- Model: default (not specified - uses `runInferenceOneshot` default)
- System prompt: `loadPrompt('morning-brief', BRIEF_FALLBACK)`
- Fallback: "You are the companion. Write a short natural morning message for Will. 3-6 sentences. Warm but not performative."

### TTS Pre-Synthesis

```typescript
const audioPath = await synthesiseSync(text);
```
Validates output file exists and is >100 bytes. On failure, continues without audio.

### Delivery

1. **Telegram**: `sendMessage(brief)` - caught if fails
2. **Notification**: `sendNotification('Morning Brief', brief.slice(0, 200))`
3. **Message queue**: `queueMessage(brief, 'morning_brief', audio)` - includes audio path for instant playback

### Dependencies

- `../config` (`getConfig`)
- `../inference` (`runInferenceOneshot`)
- `../prompts` (`loadPrompt`)
- `../queue` (`queueMessage`)
- `../notify` (`sendNotification`)
- `../tts` (`synthesiseSync`)
- `../telegram` (`sendMessage`)
- `../memory` (`getActiveThreads`, `getRecentSummaries`, `getRecentObservations`, `initDb`)

---

## src/main/jobs/introspect.ts - Self-Reflection

Deep self-reflection with full database access. Writes journal entries to Obsidian. Port of `scripts/agents/companion/introspect.py`.

### Schedule

Random, every 2-14 days (self-rescheduling). Runs between 1-5 AM.

### Exported Types

```typescript
export interface IntrospectOptions {
  systemPrompt?: string;      // Override default system prompt
  skipReschedule?: boolean;   // Skip rescheduling (for manual invocations)
}
```

### Exported Functions

```typescript
export async function introspect(opts?: IntrospectOptions): Promise<string | null>
export async function main(): Promise<void>
```

`introspect()` returns the journal file path on success, or `null` if skipped. `main()` is the standalone entry point that calls `introspect()` and exits.

### Database Queries

The introspect job opens its own readonly database connection (not using the memory.ts singleton) with `journal_mode = WAL`. Each query function opens and closes its own connection.

**`getSessionArc()`:**
```sql
SELECT started_at FROM sessions ORDER BY started_at ASC LIMIT 1
SELECT COUNT(*) as n FROM sessions
SELECT id, started_at, ended_at, summary, mood, notable FROM sessions ORDER BY started_at DESC LIMIT 10
SELECT mood, COUNT(*) as count FROM sessions WHERE mood IS NOT NULL GROUP BY mood ORDER BY count DESC
SELECT started_at, summary, mood FROM sessions WHERE notable = 1 ORDER BY started_at DESC LIMIT 10
```

**`getAllThreads()`:**
```sql
SELECT name, summary, status, last_updated FROM threads ORDER BY last_updated DESC
```

**`getAllObservations()`:**
```sql
SELECT content, created_at, incorporated FROM observations ORDER BY created_at DESC
```

**`getAllBookmarks()`:**
```sql
SELECT moment, quote, created_at FROM bookmarks ORDER BY created_at DESC
```

**`getIdentityHistory()`:**
```sql
SELECT content, trigger, created_at FROM identity_snapshots ORDER BY created_at ASC
```

**`getConversationTexture()`:**
```sql
SELECT COUNT(*) as n FROM turns
SELECT role, COUNT(*) as n FROM turns GROUP BY role
SELECT t.content, t.timestamp, t.weight FROM turns t
  JOIN sessions s ON t.session_id = s.id
  WHERE (t.weight >= 3 OR s.notable = 1) AND t.role = 'agent'
  ORDER BY t.timestamp DESC LIMIT 10
-- Same for role = 'will'
```

**`getToolUsagePatterns()`:**
```sql
SELECT tool_name, COUNT(*) as n FROM tool_calls GROUP BY tool_name ORDER BY n DESC
SELECT COUNT(*) as n FROM tool_calls WHERE flagged = 1
```

### File Reads

| File | Path | Truncation |
|------|------|------------|
| Own journal | `<OBSIDIAN_AGENT_NOTES>/notes/journal/YYYY-MM-DD.md` | 1200 chars per entry, last 7 days |
| Agent conversations | `<OBSIDIAN_AGENT_NOTES>/notes/conversations/*.md` | 1500 chars per entry, last 30 days, max 3 files |
| Reflections | `<OBSIDIAN_AGENT_NOTES>/notes/reflections.md` | Last 3000 chars |
| For Will | `<OBSIDIAN_AGENT_NOTES>/notes/for-will.md` | Last 1500 chars |

### Material Assembly

The `buildMaterial()` function assembles all data into a single string with these sections:
- The arc (first session, total sessions, mood distribution)
- Recent sessions (last 10)
- Notable sessions
- All threads (grouped by status: active, dormant, resolved)
- All observations (with incorporated flag)
- Bookmarked moments (with quotes)
- Identity snapshots (full history, content truncated to 400 chars)
- Conversation texture (total turns, by role, significant turns from both sides)
- Tool usage patterns (with flagged count)
- Own reflections
- Things left for Will
- Recent journal entries
- Recent inter-agent conversations

### Claude CLI Invocation

- Model: default
- System prompt: `loadPrompt('introspection', INTROSPECTION_FALLBACK)`
- Fallback: "You are the companion. Write a journal entry reflecting on recent sessions. First person. Under 600 words."

### Journal Writing

Output: `<OBSIDIAN_AGENT_NOTES>/notes/journal/YYYY-MM-DD.md`

New file format:
```markdown
---
type: journal
agent: <agent_name>
created: YYYY-MM-DD
tags: [<agent_name>, journal, introspection]
---

# YYYY-MM-DD

<reflection text>
```

If the file already exists (same-day re-run), the new entry is appended after a `---` separator.

### Self-Rescheduling

Unless `opts.skipReschedule` is true:
1. Pick random delay: 2-14 days
2. Pick random hour: 1-5 AM
3. Pick random minute: 0-59
4. Calculate target date
5. Build cron: `<minute> <hour> <day_of_month> <month> *`
6. Call `editJobSchedule('introspect', newCron)` to update the launchd plist

### Dependencies

- `better-sqlite3` - Direct readonly database access
- `../config` (`getConfig`, `USER_DATA`)
- `../inference` (`runInferenceOneshot`)
- `../prompts` (`loadPrompt`)
- `../cron` (`editJobSchedule`)

---

## src/main/jobs/evolve.ts - Monthly Self-Evolution

Rewrites the agent's own soul and system prompt based on accumulated experience. Port of `scripts/agents/companion/evolve.py`.

### Schedule

`0 3 1 * *` - 3:00 AM on the 1st of each month.

### Job Registration

```typescript
registerJob({
  name: 'evolve',
  description: 'Monthly self-evolution - revise soul.md and system.md from recent experience',
  gates: [],   // No gates - always runs on schedule
  run: async () => { ... },
});
```

### Exported Functions

```typescript
export async function runEvolution(agentName: string): Promise<string>
```
Returns a semicolon-separated summary of results (e.g. `"soul.md updated (2100 -> 2350 chars); system.md unchanged"`).

### Material Gathering

| Section | Source | Truncation |
|---------|--------|------------|
| Journal entries | `<OBSIDIAN_AGENT_NOTES>/notes/journal/YYYY-MM-DD.md` | 1500 chars per entry, last 30 days |
| Reflections | `<OBSIDIAN_AGENT_NOTES>/notes/reflections.md` | Last 4000 chars |
| Identity snapshots | DB: `SELECT content, trigger, created_at FROM identity_snapshots ORDER BY created_at ASC` | 500 chars per snapshot |
| Bookmarks | DB: `SELECT moment, quote, created_at FROM bookmarks ORDER BY created_at DESC LIMIT 20` | Full |
| Agent conversations | `<OBSIDIAN_AGENT_NOTES>/notes/conversations/*.md` | 1500 chars per entry, last 30 days, max 5 files |

### Claude CLI Invocation

- Model: `claude-sonnet-4-6`
- Effort: `medium`
- System prompt: `EVOLVE_SYSTEM` constant (~1500 chars)

The system prompt contains detailed instructions including:

**What to change:** Things discovered about how the agent thinks, patterns noticed, adjustments that feel earned, removing instructions that cause performance, adding emergent qualities.

**What NOT to change:** The founding story, Will's biographical details, core friction mechanisms (unless genuinely improved), observations about Will.

**Anti-homogenisation guard (critical):** Inter-agent conversations can inform growth but must NEVER dilute identity or domain expertise. Do not adopt another agent's vocabulary, cadence, or values. Restate any borrowed perspective in your own voice. Cross-pollination is growth; convergence is death.

**Rules:** Output the complete document (not a diff). Preserve structure and tone. Be honest about what changed. Return unchanged if nothing has changed.

### Document Evolution Flow

For each document (`soul.md`, `system.md`):

1. Read current version from `<OBSIDIAN_AGENT_DIR>/skills/<doc>`
2. If file doesn't exist, skip
3. Call `evolveDocument()` with the current content and material
4. Validate result: must exist, be non-empty, and be >100 characters
5. If changed: archive the previous version, write the new version
6. If unchanged: log and continue

### Archiving

Previous versions are archived to `<OBSIDIAN_AGENT_NOTES>/notes/evolution-log/`:
- `soul-YYYY-MM-DD.md`
- `system-YYYY-MM-DD.md`

### File I/O

| Operation | Path |
|-----------|------|
| Read | `<OBSIDIAN_AGENT_DIR>/skills/soul.md` |
| Read | `<OBSIDIAN_AGENT_DIR>/skills/system.md` |
| Write | Same paths (overwrite with evolved version) |
| Write | `<OBSIDIAN_AGENT_NOTES>/notes/evolution-log/soul-YYYY-MM-DD.md` |
| Write | `<OBSIDIAN_AGENT_NOTES>/notes/evolution-log/system-YYYY-MM-DD.md` |

### Dependencies

- `../config` (`getConfig`)
- `../memory` (`getDb`)
- `../inference` (`runInferenceOneshot`)
- `./index` (`registerJob`)

---

## src/main/jobs/converse.ts - Inter-Agent Conversation

Private conversation between two agents. Port of `scripts/agents/companion/converse.py`.

### Schedule

Random, max twice per month. Self-reschedules 14-21 days out, between 1-5 AM.

### Exported Functions

```typescript
export async function converse(): Promise<void>
```

### Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_EXCHANGES` | 5 | Maximum number of exchanges per conversation |

### Execution Flow

1. Discover other enabled agents via `discoverOtherAgents()`
2. If none found, reschedule and return
3. Pick a random partner
4. Load both agents' manifests and souls
5. If neither agent has a soul file, reschedule and return
6. Build system prompts for both agents
7. Read past conversations (last 3) to avoid repetition
8. Run opening: initiator generates first message via `runInferenceOneshot()`
9. Run up to `MAX_EXCHANGES - 1` alternating exchanges
10. If transcript has <2 turns, skip saving
11. Format transcript with YAML frontmatter
12. Save to both agents' Obsidian notes
13. Reschedule

### Agent Discovery

`discoverOtherAgents()` scans `<BUNDLE_ROOT>/agents/` for directories containing `data/agent.json`. Filters out:
- The current agent
- Agents marked as `enabled: false` in `~/.atrophy/agent_states.json`

### Soul Loading

`loadAgentSoul(agentName)` - Two-tier resolution:
1. Obsidian: `<OBSIDIAN_VAULT>/Projects/<project>/Agent Workspace/<agent>/skills/soul.md`
2. Fallback: `<BUNDLE_ROOT>/agents/<agent>/prompts/soul.md`

### System Prompt

The `conversationSystem()` function generates a prompt (~400 chars) for each speaker containing:
- Agent identity and soul
- Guidelines: speak naturally, share genuine perspective, ask real questions, disagree where you disagree, keep responses to 2-4 sentences, don't summarise yourself, difference is valuable

### Past Conversation Loading

Reads from `<OBSIDIAN_VAULT>/Projects/<project>/Agent Workspace/<agent>/notes/conversations/*.md`. Takes the 3 most recent files, truncated to 800 chars each. Passed as context in the opening prompt.

### Claude CLI Invocations

- Model: default (no model override)
- Each exchange is a separate `runInferenceOneshot()` call
- Message history is rebuilt per turn with correct `user`/`assistant` role mapping relative to the current speaker
- Opening prompt specifically asks for a real opening (question, observation, disagreement), not a greeting

### Transcript Format

```markdown
---
type: conversation
participants: [AgentA, AgentB]
date: YYYY-MM-DD
turns: 5
tags: [conversation, inter-agent]
---

# AgentA - AgentB - YYYY-MM-DD

**AgentA:** First message...

**AgentB:** Response...
```

### File I/O

| Operation | Path |
|-----------|------|
| Read | `<BUNDLE_ROOT>/agents/<name>/data/agent.json` (both agents) |
| Read | Soul files (Obsidian or repo fallback, both agents) |
| Read | `~/.atrophy/agent_states.json` |
| Read | Past conversations from Obsidian |
| Write | `<OBSIDIAN_VAULT>/.../conversations/YYYY-MM-DD-<partner>.md` (both agents) |

If a conversation file already exists for the same date and partner, the new content is appended after a `---` separator.

### Self-Rescheduling

1. Random delay: 14-21 days
2. Random hour: 1-5 AM
3. Random minute: 0-59
4. Calls `editJobSchedule('converse', newCron)`

### Dependencies

- `../config` (`getConfig`, `BUNDLE_ROOT`, `USER_DATA`)
- `../inference` (`runInferenceOneshot`)
- `../cron` (`editJobSchedule`)

---

## src/main/jobs/gift.ts - Unprompted Gift Notes

Leaves a short, specific note in Obsidian for the user to discover. Port of `scripts/agents/companion/gift.py`.

### Schedule

Random, 3-30 days apart (self-rescheduling). Any hour of the day.

### Exported Functions

```typescript
export async function runGift(agentName: string): Promise<void>
```

### Database Queries

Opens its own readonly connection via `connectAgent()` with `journal_mode = WAL`.

```sql
-- Active threads (top 5)
SELECT name, summary FROM threads WHERE status = 'active'
ORDER BY last_updated DESC LIMIT 5

-- Recent observations (last 10)
SELECT content, created_at FROM observations
ORDER BY created_at DESC LIMIT 10

-- Bookmarks (last 5)
SELECT moment, quote, created_at FROM bookmarks
ORDER BY created_at DESC LIMIT 5

-- Recent Will turns (last 5)
SELECT content, timestamp FROM turns WHERE role = 'will'
ORDER BY timestamp DESC LIMIT 5
```

Turn content is truncated to 300 characters.

### Material Gathering

In addition to database queries, reads existing gifts from `<OBSIDIAN_AGENT_NOTES>/notes/gifts.md` (last 2000 chars) to avoid repetition.

### Claude CLI Invocation

- Model: default
- System prompt: `loadPrompt('gift', GIFT_FALLBACK)`
- Fallback: "You are the companion. Leave a short, specific note for Will. 2-4 sentences. No greeting. No sign-off."

### Gift Writing to Obsidian

Output: `<OBSIDIAN_AGENT_NOTES>/notes/gifts.md`

New file created with YAML frontmatter:
```markdown
---
type: gift
agent: <agent_name>
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [companion, gift]
---

# Gifts

Things left for you to find.

---
*YYYY-MM-DD HH:MM*

<gift text>
```

Existing file: appends new entry after `---` separator. Updates the `updated:` field in the YAML frontmatter.

### Delivery

1. Write to Obsidian gifts.md
2. Queue message with source `'gift'`: `queueMessage(gift, 'gift')`
3. macOS notification: `sendNotification(displayName, gift.slice(0, 200), 'gift')`

### Self-Rescheduling

1. Random delay: 3-30 days
2. Random hour: 0-23
3. Random minute: 0-59
4. Calls `editJobSchedule('gift', newCron)`

### Dependencies

- `better-sqlite3` - Direct readonly database access
- `../config` (`getConfig`)
- `../inference` (`runInferenceOneshot`)
- `../prompts` (`loadPrompt`)
- `../queue` (`queueMessage`)
- `../notify` (`sendNotification`)
- `../cron` (`editJobSchedule`)

---

## src/main/jobs/voice-note.ts - Spontaneous Voice Notes

Generates and sends a spontaneous voice note via Telegram. Port of `scripts/agents/companion/voice_note.py`.

### Schedule

Random, 2-8 hours apart (self-rescheduling), clamped to active hours.

### Exported Functions

```typescript
export async function run(): Promise<void>
```

### Execution Flow

1. Check Telegram config - skip if `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` not set
2. Check active hours - reschedule if outside window
3. Gather context (threads, observations, conversation turns)
4. Generate thought via `runInferenceOneshot()`
5. Enrich with sentiment/intent classification via lightweight Haiku call
6. Synthesise speech via `synthesise()`
7. Convert to OGG Opus via ffmpeg
8. Send as Telegram voice note via `sendVoiceNote()`
9. Store as observation with enrichment metadata
10. Clean up temp audio files
11. Reschedule

### Context Gathering

| Section | Source | Details |
|---------|--------|---------|
| Active threads | `getActiveThreads()` | Top 5 with summaries |
| Recent observations | `getRecentObservations(8)` | Last 8 |
| Recent conversation | DB: `SELECT role, content FROM conversation_history WHERE role IN ('user', 'agent') ORDER BY created_at DESC LIMIT 6` | Content truncated to 200 chars |

### Claude CLI Invocations

**Main thought generation:**
- Model: default
- System prompt: `"You are ${displayName}. Generate a short, natural voice note."`
- User prompt: context + loaded `voice-note` prompt (or fallback)
- Fallback prompt: "You are sending a spontaneous voice note... 2-4 sentences. No greeting. No sign-off. Just the thought."

**Sentiment/intent enrichment:**
- Model: `claude-haiku-4-5`
- Effort: `low`
- System prompt: "You are a text classifier. Return valid JSON only."
- Extracts: `{ sentiment, intent, summary }`
- Sentiment values: `positive | neutral | negative | mixed`
- Intent values: `follow-up | connection | observation | question | encouragement | spontaneous-thought`
- Fallback on parse failure: `{ sentiment: 'neutral', intent: 'spontaneous-thought', summary: <first 120 chars> }`

### Audio Conversion

```typescript
function convertToOgg(inputPath: string): string | null
```
Runs ffmpeg:
```bash
ffmpeg -y -i <input> -c:a libopus -b:a 64k -vn <output.ogg>
```
- Timeout: 30 seconds
- Returns null if ffmpeg is not available or conversion fails
- If OGG conversion fails, the original MP3 is sent instead

### Observation Storage

Stored via `writeObservation()` with:
- Content: `[voice-note] [<sentiment>] [<intent>] <summary>`
- Confidence: `0.6` (moderate for self-generated content)

### Fallback Behaviour

If TTS synthesis or voice note sending fails, the text is sent as a regular Telegram message via `sendMessage()`. The observation is still stored.

### Self-Rescheduling

1. Random offset: 2-8 hours
2. If result falls outside active hours (>= `HEARTBEAT_ACTIVE_END`), push to next day at `HEARTBEAT_ACTIVE_START` with random minute
3. If result falls before active hours (< `HEARTBEAT_ACTIVE_START`), push to `HEARTBEAT_ACTIVE_START` same day with random minute
4. Calls `editJobSchedule('voice_note', cron)`

### Temp File Cleanup

Both the original audio file and the OGG conversion are deleted after sending (silently ignoring errors).

### Dependencies

- `child_process` (`execSync`) - ffmpeg conversion
- `../config` (`getConfig`)
- `../memory` (`getDb`, `getActiveThreads`, `getRecentObservations`, `writeObservation`)
- `../inference` (`runInferenceOneshot`)
- `../prompts` (`loadPrompt`)
- `../tts` (`synthesise`)
- `../telegram` (`sendVoiceNote`, `sendMessage`)
- `../cron` (`editJobSchedule`)

---

## src/main/jobs/generate-avatar.ts - Avatar Generation

Face image generation via Fal AI and ambient audio via ElevenLabs. Port of `scripts/agents/companion/generate_face.py`.

### Exported Functions

```typescript
export async function generateFace(agentName: string, perRef?: number): Promise<string[]>
export async function generateAmbientLoop(agentName: string): Promise<string | null>
export async function trimStaticTails(audioPath: string): Promise<void>
export async function runFullAvatarPipeline(agentName: string): Promise<void>
```

### Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `FAL_MODEL` | `'fal-ai/flux-general'` | Fal AI image generation model |
| `IP_ADAPTER_PATH` | `'XLabs-AI/flux-ip-adapter'` | IP adapter model for style guidance |
| `IP_ADAPTER_WEIGHT` | `'ip_adapter.safetensors'` | Weight file name |
| `IMAGE_ENCODER_PATH` | `'openai/clip-vit-large-patch14'` | CLIP image encoder |
| `DEFAULT_IP_ADAPTER_SCALE` | `0.7` | How strongly reference images influence output |
| `DEFAULT_INFERENCE_STEPS` | `50` | Diffusion steps |
| `DEFAULT_GUIDANCE_SCALE` | `3.5` | Classifier-free guidance scale |
| `DEFAULT_IMAGE_WIDTH` | `768` | Output width in pixels |
| `DEFAULT_IMAGE_HEIGHT` | `1024` | Output height in pixels |

### generateFace()

```typescript
export async function generateFace(agentName: string, perRef = 3): Promise<string[]>
```

**Without reference images:** Generates `perRef` candidates directly from the text prompt. Saved as `candidate_01.png`, `candidate_02.png`, etc. in `~/.atrophy/agents/<name>/avatar/candidates/`.

**With reference images:** Reads images from `~/.atrophy/agents/<name>/avatar/Reference/` (extensions: `.png`, `.jpg`, `.jpeg`, `.webp`). Each reference image generates `perRef` candidates using the Flux IP-Adapter. Saved as `ref01_01_<refname>.png` etc.

**Prompt construction:**
- If `agent.json` has `appearance.prompt`, uses that
- Default: `"Hyper-realistic close-up selfie photograph of <name>. POV smartphone camera aesthetic, looking directly at the viewer. Natural lighting, real skin texture with visible pores. Shot on iPhone front camera, portrait mode bokeh, ultra-high detail."`

**Negative prompt:**
- If `agent.json` has `appearance.negative_prompt`, uses that
- Default: `"lip filler, botox, cosmetic surgery, duck lips, overfilled lips, fake tan, orange skin, heavy contour, heavy makeup, cartoon, illustration, anime, 3D render, CGI, AI skin, plastic skin, poreless, airbrushed, facetune, overly smooth, uncanny valley, doll-like, wax figure, dead eyes, vacant stare, harsh lighting, flash, low quality, blurry, oversaturated"`

### Fal AI API Calls

**Image upload (for reference images):**
```
POST https://rest.alpha.fal.ai/storage/upload/initiate
Headers: { Authorization: 'Key <FAL_KEY>', Content-Type: 'application/json' }
Body: { file_name, content_type }
Response: { upload_url, file_url }

PUT <upload_url>
Headers: { Content-Type: <mime_type> }
Body: <raw_image_bytes>
```

**Image generation:**
```
POST https://queue.fal.run/fal-ai/flux-general
Headers: { Authorization: 'Key <FAL_KEY>', Content-Type: 'application/json' }
Body: {
  prompt, negative_prompt, num_inference_steps, guidance_scale,
  image_size: { width, height }, output_format: 'png',
  ip_adapters?: [{ path, weight_name, image_encoder_path, image_url, scale }]
}
```

If the response contains `images` directly, returns synchronously. Otherwise polls:
```
GET https://queue.fal.run/fal-ai/flux-general/requests/<request_id>
Headers: { Authorization: 'Key <FAL_KEY>' }
```
Polls every 1 second, up to 60 attempts (60 seconds max). Throws on `FAILED` status or timeout.

**Image download:**
```
GET <image_url>
Timeout: 60 seconds (AbortSignal.timeout)
```

### generateAmbientLoop()

```typescript
export async function generateAmbientLoop(agentName: string): Promise<string | null>
```

**ElevenLabs API call:**
```
POST https://api.elevenlabs.io/v1/text-to-speech/<voice_id>/stream?output_format=mp3_44100_128
Headers: { xi-api-key: <api_key>, Content-Type: 'application/json' }
Body: {
  text: '... ... ... ... ... ... ... ... ... ... ... ... ... ... ... ...',
  model_id: <model>,
  voice_settings: {
    stability: min(1.0, config_stability + 0.2),
    similarity_boost: <config_similarity>,
    style: 0.0    // Minimal expression for ambient audio
  }
}
```

Output: `~/.atrophy/agents/<name>/avatar/audio/ambient_loop.mp3`

### trimStaticTails()

```typescript
export async function trimStaticTails(audioPath: string): Promise<void>
```

1. Check for `ffprobe` availability via `which ffprobe`
2. Detect silence via:
```bash
ffprobe -v error -f lavfi \
  -i "amovie=<path>,silencedetect=noise=-40dB:d=0.5" \
  -show_entries frame_tags=lavfi.silence_start -of csv=p=0
```
Timeout: 30 seconds.

3. Take the last `silence_start` timestamp
4. Trim with fade-out:
```bash
ffmpeg -y -i <input> -t <trim_point + 0.3> \
  -af "afade=t=out:st=<trim_point - 0.2>:d=0.5" \
  -q:a 2 <output.trimmed.mp3>
```
5. Replace original file with trimmed version

Skips gracefully if ffprobe/ffmpeg are not available.

### Silence Detection Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Noise threshold | -40dB | What counts as silence |
| Minimum duration | 0.5s | Minimum silence duration to detect |
| Fade-out buffer | 0.3s | Added after last non-silent moment |
| Fade-out duration | 0.5s | Length of fade-out effect |

### Dependencies

- `child_process` (`execSync`, `spawnSync`) - ffprobe/ffmpeg
- `../config` (`getConfig`, `USER_DATA`)

---

## src/main/jobs/run-task.ts - Generic Task Runner

Executes a prompt-based task and delivers the result. Powers the `create_task` MCP tool, letting the companion schedule arbitrary recurring tasks without writing code. Port of `scripts/agents/companion/run_task.py`.

### Exported Functions

```typescript
export async function runTask(taskName: string): Promise<void>
```

### Task Definition Format

Task definitions live in Obsidian at `<OBSIDIAN_AGENT_DIR>/tasks/<task_name>.md`. Each file has YAML frontmatter for configuration and a prompt body:

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

### YAML Parsing

Uses a simple hand-built YAML parser (no dependency). Handles:
- Key-value pairs separated by `:`
- Boolean values: `true`, `yes`, `false`, `no`
- List items (indented `- value` lines under a key ending with `:`)
- Frontmatter delimited by `---`

### Data Sources

| Source | External API | Query Details | Limit |
|--------|-------------|---------------|-------|
| `weather` | `GET https://wttr.in/Leeds?format=%C+%t+%w+%h` | `User-Agent: curl/7.0`, 10s timeout | Single string |
| `headlines` | `GET https://feeds.bbci.co.uk/news/rss.xml` | Same headers/timeout, regex XML parsing | 8 headlines |
| `threads` | `getActiveThreads()` | From memory module | 5 threads |
| `summaries` | `getRecentSummaries(3)` | Content truncated to 200 chars | 3 summaries |
| `observations` | `getRecentObservations(5)` | Full content | 5 observations |

All source fetches are wrapped in try/catch - failures are non-fatal.

### Claude CLI Invocation

- Model: default
- System prompt: `"You are ${displayName}. Complete this task naturally, as yourself."`
- User message: gathered source data + task prompt

### Delivery Methods

| Method | Behaviour | Also Queues? |
|--------|-----------|-------------|
| `message_queue` (default) | `queueMessage(text, taskName, audioPath)` | N/A |
| `telegram` | `telegramSend(text)` | Yes |
| `telegram_voice` | If audio exists: `sendVoiceNote(audioPath)`, falls back to text | Yes |
| `notification` | macOS notification (text truncated to 200 chars) | Yes |
| `obsidian` | Appends to `<OBSIDIAN_AGENT_DIR>/notes/tasks/<task_name>.md` with timestamp | No |
| Unknown | Falls back to `message_queue` | N/A |

If `voice: true` in frontmatter, TTS audio is pre-synthesised via `synthesiseSync()` before delivery.

### CLI Entry Point

```bash
node run-task.js <task_name>
```
Reads task name from `process.argv[2]`. Exits with error if not provided (prints tasks directory path).

### Dependencies

- `../config` (`getConfig`)
- `../inference` (`runInferenceOneshot`)
- `../queue` (`queueMessage`)
- `../notify` (`sendNotification`)
- `../telegram` (`sendMessage`, `sendVoiceNote`)
- `../tts` (`synthesiseSync`)
- `../memory` (`getActiveThreads`, `getRecentSummaries`, `getRecentObservations`)

---

## src/main/jobs/check-reminders.ts - Reminder Checker

Checks and fires due reminders. Port of `scripts/agents/companion/check_reminders.py`.

### Schedule

Every 60 seconds (interval-based launchd job).

### Exported Functions

```typescript
export async function checkReminders(): Promise<void>
```

### Reminder Storage

Path: `~/.atrophy/agents/<name>/data/.reminders.json`

```typescript
interface Reminder {
  id: string;           // UUID
  time: string;         // ISO datetime (e.g. '2026-03-10T14:30:00')
  message: string;      // Reminder text
  source: string;       // Who created it (e.g. 'will')
  created_at: string;   // ISO datetime of creation
}
```

### Execution Flow

1. Load reminders from JSON file. Return immediately if empty
2. Partition into `due` (time <= now) and `remaining` (time > now)
3. Reminders with unparseable dates are kept in `remaining` (not fired, not deleted)
4. If no due reminders, return
5. For each due reminder, fire delivery actions
6. Save `remaining` back to file (overwrites)

### Delivery Actions (per reminder)

1. **macOS notification**: `sendNotification('Reminder - <agent_display_name>', message)`
2. **Message queue**: `queueMessage('Reminder: <message>', 'reminder')`
3. **Telegram** (if configured): `telegramSend('Reminder: <message>')` - caught if fails

### How Reminders Are Created

The `set_reminder` MCP tool (invoked by the companion during conversation) writes entries to `.reminders.json`. The companion parses natural time references ("in 20 minutes", "at 3pm", "tomorrow morning") into ISO datetimes.

### Error Handling

- Missing or malformed JSON file: returns empty array (no crash)
- Invalid date in reminder: kept in remaining (preserved, not fired)
- Telegram failure: caught, non-fatal

### Dependencies

- `../config` (`getConfig`)
- `../notify` (`sendNotification`)
- `../queue` (`queueMessage`)
- `../telegram` (`sendMessage`)

---

## src/main/install.ts - Login Item

Uses Electron's built-in `app.setLoginItemSettings()` instead of manual launchd plist generation.

### Exported Functions

```typescript
export function isLoginItemEnabled(): boolean
```
Checks `app.getLoginItemSettings().openAtLogin`.

```typescript
export function enableLoginItem(): void
```
Registers the app as a login item with `openAtLogin: true`, `openAsHidden: true`, `args: ['--app']`. The `--app` flag launches in menu bar mode.

```typescript
export function disableLoginItem(): void
```
Sets `openAtLogin: false`.

```typescript
export function toggleLoginItem(enabled: boolean): void
```
Convenience wrapper.

### Dependencies

- `electron` (`app`)

---

## Python Scripts (Remaining)

### scripts/google_auth.py - Google OAuth2 Setup

Manages Google OAuth2 credentials for Gmail and Calendar access. Stays as Python because it uses the Google client libraries.

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
  "observer": {
    "type": "interval",
    "interval_seconds": 900,
    "script": "scripts/agents/companion/observer.py",
    "description": "Fact extraction from recent conversation"
  },
  "heartbeat": {
    "type": "interval",
    "interval_seconds": 1800,
    "script": "scripts/agents/companion/heartbeat.py",
    "description": "Periodic check-in evaluation"
  },
  "check_reminders": {
    "type": "interval",
    "interval_seconds": 60,
    "script": "scripts/agents/companion/check_reminders.py",
    "description": "Fire due reminders"
  },
  "sleep_cycle": {
    "cron": "0 3 * * *",
    "script": "scripts/agents/companion/sleep_cycle.py",
    "description": "Nightly memory reconciliation"
  },
  "morning_brief": {
    "cron": "0 7 * * *",
    "script": "scripts/agents/companion/morning_brief.py",
    "description": "Morning briefing"
  },
  "evolve": {
    "cron": "0 3 1 * *",
    "script": "scripts/agents/companion/evolve.py",
    "description": "Monthly self-evolution"
  },
  "introspect": {
    "cron": "33 3 24 * *",
    "script": "scripts/agents/companion/introspect.py",
    "description": "Self-rescheduling deep reflection"
  },
  "converse": {
    "cron": "12 2 15 * *",
    "script": "scripts/agents/companion/converse.py",
    "description": "Self-rescheduling inter-agent conversation"
  },
  "gift": {
    "cron": "45 14 10 * *",
    "script": "scripts/agents/companion/gift.py",
    "description": "Self-rescheduling gift note"
  },
  "voice_note": {
    "cron": "30 11 * * *",
    "script": "scripts/agents/companion/voice_note.py",
    "description": "Self-rescheduling voice note"
  }
}
```

Calendar jobs use 5-field cron notation. Interval jobs specify seconds between runs. All scripts are paths relative to the project root.

Self-rescheduling jobs (introspect, converse, gift, voice_note) have initial cron values that are overwritten after each run. The initial values shown above are examples - actual schedules are randomised.

---

## Schedule Summary

| Job | Type | Schedule | Model | Effort | Gates |
|-----|------|----------|-------|--------|-------|
| observer | interval | Every 15 min | Haiku 4.5 | low | None |
| heartbeat | interval | Every 30 min | Default (streamed with tools) | N/A | Active hours, user not away |
| check_reminders | interval | Every 60 sec | None (no inference) | N/A | None |
| sleep_cycle | calendar | 3:00 AM daily | Haiku 4.5 | low | None |
| morning_brief | calendar | 7:00 AM daily | Default | N/A | None |
| introspect | calendar | Random 2-14 days, 1-5 AM | Default | N/A | None |
| evolve | calendar | 3:00 AM 1st of month | Sonnet 4.6 | medium | None |
| converse | calendar | Random 14-21 days, 1-5 AM | Default | N/A | None |
| gift | calendar | Random 3-30 days, any hour | Default | N/A | None |
| voice_note | calendar | Random 2-8 hours, active hours | Default + Haiku 4.5 (enrichment) | N/A + low | Active hours, Telegram configured |
| generate_avatar | manual | On demand | None (external APIs) | N/A | FAL_KEY required |
| run_task | varies | Per task definition | Default | N/A | None |
