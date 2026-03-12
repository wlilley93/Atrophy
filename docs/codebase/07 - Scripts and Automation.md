# Scripts and Automation

Background jobs and utilities form the autonomous nervous system of the companion agent. While the main Electron process handles user-facing interaction, these modules run on their own schedules - extracting facts, consolidating memory, generating reflections, reaching out unprompted, and evolving the agent's own identity over time. All TypeScript job modules live in `src/main/jobs/`, with shared tooling (cron management, agent scaffolding) in `src/main/`. A handful of Python scripts that remain as subprocesses live in `mcp/` and `scripts/`, primarily because they depend on Python-specific libraries (Google client, MCP SDK) that have no practical TypeScript equivalent.

The automation layer breaks into three conceptual tiers. The first tier is the control plane - `cron.ts` manages launchd plists and `jobs/index.ts` provides the runtime harness. The second tier is the agent lifecycle - `create-agent.ts` scaffolds new agents, while `evolve.ts` and `introspect.ts` drive long-term identity development. The third tier is the outreach and maintenance jobs - heartbeat, morning brief, gift, voice note, and others that keep the agent present between active conversations.

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

This module is the bridge between the companion's job definitions and the macOS launchd scheduler. It is a direct port of `scripts/cron.py` from the Python version, preserving the same job definition format and plist structure. Every scheduled background job in the system - heartbeat checks, sleep cycles, morning briefs, self-rescheduling reflections - ultimately flows through this module to become a launchd plist in `~/Library/LaunchAgents/`.

The design uses a simple JSON file (`jobs.json`) as the canonical store of job definitions, with each agent maintaining its own copy at `<BUNDLE_ROOT>/scripts/agents/<agent_name>/jobs.json`. When a job is "installed", `cron.ts` generates an Apple plist XML file, writes it to the LaunchAgents directory, and tells launchd to load it. When a job is "uninstalled", the reverse happens. This two-step model - define in JSON, activate via launchd - lets the Settings UI show jobs that exist but are not currently active, and lets self-rescheduling jobs (introspect, converse, gift, voice-note) update their cron expressions at runtime without the user noticing.

### Exported Types

The following interfaces define the shape of job data throughout the system. `Job` represents the persistent definition stored in `jobs.json`, while `JobInfo` extends it with runtime state for display in the Settings panel.

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

The public API covers the full lifecycle of job management - listing, adding, removing, editing schedules, running on demand, and bulk install/uninstall.

```typescript
export function listJobs(): JobInfo[]
```
Reads all jobs from `jobs.json`, checks whether each has an installed plist file in `~/Library/LaunchAgents/`, and returns an array of `JobInfo` objects. The `schedule` field is formatted as `"every Ns"` for interval jobs or the raw cron string for calendar jobs. This is the primary function used by the Settings panel to populate the jobs list.

```typescript
export function addJob(
  name: string,
  cronStr: string,
  script: string,
  description?: string,   // default: ''
  install?: boolean,       // default: false
): void
```
Validates the cron string via `parseCron()` (throws on invalid format), adds the job to `jobs.json`, and optionally installs it to launchd immediately. This is called during agent creation to register the default set of background jobs.

```typescript
export function removeJob(name: string): void
```
Uninstalls the job from launchd (if installed), removes it from `jobs.json`, and logs the action. No-op if the job does not exist. Used when an agent is deleted or a job is permanently removed from the schedule.

```typescript
export function editJobSchedule(name: string, cronStr: string): void
```
Updates the cron expression for an existing job. Validates the new cron string. If the job is already installed (plist exists), uninstalls and reinstalls it with the new schedule. This is the function used by self-rescheduling jobs (introspect, converse, gift, voice-note) to set their next run time after completing.

```typescript
export function runJobNow(name: string): number
```
Runs a job immediately via `spawnSync()`. Executes `PYTHON_PATH <script> [args...]` with `AGENT=<name>` in the environment. Returns the process exit code (0 on success, 1 on failure or if job not found). Primarily used for manual "Run Now" triggers from the Settings panel.

The following three functions provide bulk operations, used when enabling or disabling the entire cron system from the Settings panel.

```typescript
export function installAllJobs(): void
export function uninstallAllJobs(): void
export function toggleCron(enabled: boolean): void
```
`toggleCron(true)` calls `installAllJobs()`, `toggleCron(false)` calls `uninstallAllJobs()`. These iterate through every job in `jobs.json` and install or uninstall all of them in a single pass.

### Internal Functions

The internal functions handle path resolution, job storage, cron parsing, and the low-level install/uninstall mechanics. They are not exported but are critical to understanding the module's behaviour.

**`labelPrefix(): string`** - Returns `com.atrophiedmind.<agent_name>.` using the current config's agent name. This prefix ensures that each agent's launchd jobs are namespaced and do not collide with jobs from other agents.

**`jobsFile(): string`** - Returns the path to the jobs definition file: `<BUNDLE_ROOT>/scripts/agents/<agent_name>/jobs.json`. Each agent has its own jobs file, allowing different agents to have different schedules and even different sets of jobs.

**`logsDir(): string`** - Returns `<BUNDLE_ROOT>/logs/<agent_name>`. Created on install if missing. Both stdout and stderr from launchd jobs are directed here, one log file per job.

**`plistPath(name: string): string`** - Returns `~/Library/LaunchAgents/com.atrophiedmind.<agent>.<name>.plist`. This is the canonical location where macOS expects per-user launchd job definitions to live.

**`loadJobs(): Record<string, Job>`** - Reads and parses `jobs.json`. Returns empty object if file is missing or malformed. The resilient error handling ensures that a corrupted jobs file does not crash the app.

**`saveJobs(jobs: Record<string, Job>): void`** - Writes jobs to `jobs.json` with 2-space indentation. Creates parent directories if needed.

**`parseCron(cronStr: string): CalendarInterval`** - Parses a 5-field cron string into a launchd `CalendarInterval` object. Fields: `Minute`, `Hour`, `Day`, `Month`, `Weekday`. Wildcard (`*`) fields are omitted from the output, which tells launchd to match any value for that field. Throws `Error` if the string does not contain exactly 5 whitespace-separated fields.

### Plist Generation

The `generatePlist(name: string, job: Job): PlistDict` function builds a structured object that maps directly to the Apple plist format. Each field in the output corresponds to a standard launchd configuration key.

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

The job type defaults to `'calendar'` if `job.type` is not specified. Calendar jobs use cron-style scheduling (run at specific times), while interval jobs run repeatedly at a fixed interval in seconds.

### XML Serialisation

The `plistToXml(plist: PlistDict): string` function is a minimal hand-built XML serialiser that avoids pulling in an external plist library. This keeps the dependency footprint small while producing valid Apple plist XML. The serialiser handles the following value types recursively:

- `string` values as `<string>` elements
- `number` values as `<integer>` elements
- `boolean` values as `<true/>` or `<false/>`
- `Array` values as `<array>` with string items
- Nested `object` values as `<dict>` (recursive descent)

Output includes the standard Apple plist DTD declaration, making it compatible with `plutil`, `launchctl`, and other macOS tooling.

### Install/Uninstall Flow

The install and uninstall operations are deliberately simple and synchronous, since they run rarely (only when toggling jobs or rescheduling) and must complete before the calling function proceeds.

1. `installJob(name, job)`: Creates logs directory, creates `~/Library/LaunchAgents/` directory, writes plist XML, runs `launchctl load <plist_path>`.
2. `uninstallJob(name)`: Checks plist exists, runs `launchctl unload <plist_path>`, deletes the plist file.

Both use `spawnSync('launchctl', ...)` with `stdio: 'pipe'` to suppress launchctl's output from appearing in the app's console.

### File I/O Summary

The following table lists all files that `cron.ts` reads from and writes to during normal operation.

| Operation | Path | Format |
|-----------|------|--------|
| Read | `<BUNDLE_ROOT>/scripts/agents/<agent>/jobs.json` | JSON object of Job definitions |
| Write | Same path | Same format, 2-space indent |
| Write | `~/Library/LaunchAgents/com.atrophiedmind.<agent>.<job>.plist` | Apple plist XML |
| Delete | Same plist path | On uninstall |
| Create dir | `<BUNDLE_ROOT>/logs/<agent>/` | On install |

### Dependencies

This module depends on Node's built-in `child_process` for `execSync` and `spawnSync` (used to run launchctl commands), and on the config module for `getConfig`, `BUNDLE_ROOT`, and `USER_DATA`.

---

## src/main/create-agent.ts - Agent Scaffolding

This module handles programmatic agent creation, building a complete agent directory structure with all required files, prompts, and an initialised SQLite database. Unlike the Python version's 9-step interactive questionnaire that used AI to expand sparse character descriptions into richly detailed prompt documents, the TypeScript version accepts a typed `CreateAgentOptions` object for non-interactive use. It is called from the setup wizard (during first launch) and via IPC (when creating agents from the Settings panel).

The design prioritises idempotency - all file writes use `writeIfMissing()`, so running `createAgent()` multiple times with the same name is safe. Existing files are never overwritten, and the database is only initialised if `memory.db` does not already exist. This matters because the setup wizard may be interrupted and restarted, and agents may be partially created if the process crashes mid-way.

### Exported Types

The options interface captures everything needed to define an agent's identity, voice, appearance, tools, and outreach behaviour. Most fields are optional, with sensible defaults applied during manifest generation.

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
```

The manifest interface describes the structure of the `agent.json` file that is written to disk and used by every other module in the system to understand an agent's configuration.

```typescript
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

The internal functions handle the individual steps of agent creation - name slugification, directory creation, manifest assembly, prompt generation, and database initialisation.

**`slugify(name: string): string`** - Lowercases, trims, and replaces all non-alphanumeric/underscore characters with underscores. This produces the internal agent name used in file paths and launchd labels.

**`ensureDir(dirPath: string): void`** - `fs.mkdirSync` with `{ recursive: true }`. A thin wrapper used throughout to create nested directory structures.

**`writeIfMissing(filePath: string, content: string): void`** - Creates parent directories and writes file only if it does not already exist. This is the key to idempotency - re-running agent creation never overwrites existing prompt files that may have been customised.

**`buildManifest(opts, name): AgentManifest`** - Assembles the full manifest from options with defaults. Description is truncated to 120 characters (117 + `'...'`). Telegram env key references use the pattern `TELEGRAM_BOT_TOKEN_<NAME_UPPER>` and `TELEGRAM_CHAT_ID_<NAME_UPPER>`, which are resolved from environment variables at runtime.

**`generateSystemPrompt(opts, name): string`** - Template-based system prompt (typically 500-800 words). Sections: Origin, Who You Are, Character, Relationship with user, Values, Constraints, Friction, Voice, Capabilities (CONVERSATION, MEMORY, RESEARCH, REFLECTION, WRITING, SCHEDULING, MONITORING), Session Behaviour, Opening Line. Unset sections use the placeholder `(To be written.)`.

**`generateSoul(opts): string`** - First-person working notes (typically 300-500 words). Sections: Where I Come From, What I Am, Character, What I Will Not Do, How I Push Back, Values, Relationship, How I Write. The soul is the agent's internal sense of self, distinct from the system prompt which is operational.

**`generateHeartbeat(opts): string`** - Outreach evaluation checklist (typically 200-300 words). Sections: Timing, Unfinished Threads, Things You've Been Thinking About, Agent-Specific Considerations (from `outreachStyle`), The Real Question ("would hearing from you right now feel like a gift, or like noise?"). This document guides the heartbeat job's decision about whether to reach out.

**`initDatabase(dbPath: string): void`** - Reads SQL from `<BUNDLE_ROOT>/db/schema.sql`, opens a new SQLite database via `better-sqlite3`, executes the schema, and closes the connection. Throws if schema file is missing.

### Directory Structure Created

The `createAgent()` function builds the following directory tree under `~/.atrophy/agents/<name>/`. Each subdirectory serves a specific purpose and is populated by different modules during the agent's lifetime.

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

The TypeScript version makes several deliberate simplifications compared to the Python original, trading AI-driven richness for speed and predictability.

- Python version generates 5 prompt documents; Electron generates 3 (no `gift.md` or `morning-brief.md`)
- Python version uses `run_inference_oneshot()` to expand sparse fields into richly detailed documents (1000-2500 words). Electron version uses template interpolation only - no LLM expansion step
- Python version scaffolds Obsidian vault directories and daemon scripts. Electron version does not - Obsidian integration is resolved dynamically at runtime via `prompts.ts`, and daemon scripts are handled by the job framework

### Dependencies

This module depends on `better-sqlite3` for database initialisation, and on the config module for `BUNDLE_ROOT` and `USER_DATA` path constants.

---

## src/main/jobs/index.ts - Job Runner Framework

This module provides the common harness that all background jobs use for registration, gate checking, execution, and structured result reporting. It sits between the launchd/cron layer (which triggers jobs) and the individual job modules (which contain the actual logic). Every job in the system registers itself with this framework at module load time, and all job execution flows through the `runJob()` function, which handles timing, gate checks, error capture, and logging in a consistent way.

The framework supports two invocation modes. The first is in-process, where the main Electron app calls `runJob()` directly (for manual triggers from the Settings panel). The second is CLI, where a standalone Electron process is launched by launchd with `--job=<name> --agent=<agent>` flags, and `runJobFromCli()` handles argument parsing, execution, and process exit.

### Exported Types

These types define the contract between the framework and individual job modules. Every job must implement `JobDefinition`, and every execution produces a `JobResult`.

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

The registry functions manage the global set of available jobs. Registration happens at module load time - when `heartbeat.ts` is imported, for example, it calls `registerJob()` as a side effect of loading.

```typescript
export function registerJob(def: JobDefinition): void
```
Adds a job to the internal `Map<string, JobDefinition>` registry. Called at module load time by each job module.

```typescript
export function getRegisteredJobs(): JobDefinition[]
export function getJob(name: string): JobDefinition | undefined
```
Registry lookup functions. `getRegisteredJobs()` returns all registered jobs as an array, used by the Settings panel to display available jobs. `getJob()` returns a single job by name, or `undefined` if not registered.

The `runJob()` function is the core execution path. It enforces a strict sequence - config scoping, gate checks, execution, error capture - and guarantees that the caller always gets a structured result, never an uncaught exception.

```typescript
export async function runJob(name: string, agent?: string): Promise<JobResult>
```
Executes a registered job with the following flow:

1. If `agent` is provided, calls `getConfig().reloadForAgent(agent)` to scope all config to that agent
2. Looks up the job in the registry. Returns `ran: false` with error if not found
3. Runs each gate check sequentially. If any returns a reason string, returns `ran: false` with that reason
4. Calls `def.run()`. Captures the outcome string on success or the error message on failure
5. Logs `[job:<name>]` messages with duration. Outcome is truncated to 120 characters in logs
6. **Never throws** - errors are captured in the `JobResult.error` field

The CLI entry point is designed for launchd invocations, where the Electron binary is launched as a standalone process that runs a single job and exits.

```typescript
export async function runJobFromCli(argv: string[]): Promise<void>
```
Parses `--job=<name>` and `--agent=<agent>` from the argument array. Reloads config for the agent, runs the job, prints the result as formatted JSON, and calls `process.exit(0)` on success or `process.exit(1)` on error. Exits with code 1 and a usage message if `--job` is missing.

A typical launchd invocation looks like this:

```bash
electron . --job=heartbeat --agent=companion
```

### Exported Gate Functions

Gate functions are reusable precondition checks that jobs can compose into their `gates` array. Currently there is one shared gate, but the pattern is designed to be extended as new conditions arise.

```typescript
export function activeHoursGate(): string | null
```
Returns null if the current hour is within the agent's configured active window (`HEARTBEAT_ACTIVE_START` to `HEARTBEAT_ACTIVE_END`). Returns a reason string like `"Outside active hours (9-22)"` otherwise. Used by heartbeat and voice-note jobs to avoid reaching out in the middle of the night.

### Dependencies

This module depends only on the config module (`getConfig`) for agent-scoped configuration loading. It has no external dependencies, keeping the framework lightweight and fast to import.

---

## src/main/jobs/observer.ts - Fact Extraction

The observer is a pre-compaction fact extraction job that runs every 15 minutes, scanning recent conversation turns for durable facts worth preserving between compaction events. It complements the memory flush that happens during conversation by catching things that matter before they scroll out of the Claude CLI's context window. This is a port of `scripts/agents/companion/observer.py` and operates as silent monitoring - it produces no user-facing output.

Most runs are no-ops. The observer tracks the highest turn ID it has processed, and if no new turns exist since the last run, it returns immediately. When there is new material, it uses Haiku with low effort for fast, cheap extraction - typically completing in under a second. The extracted facts are stored as observations in the memory database, where they become available to the context assembly system and to other jobs like sleep-cycle and introspect.

### Schedule

Every 15 minutes (interval-based launchd job). This frequency balances extraction freshness against API cost - most 15-minute windows will have zero new turns, so the fast-path no-op keeps the cost negligible.

### Exported Functions

```typescript
export async function runObserver(agentName: string): Promise<void>
```

### Execution Flow

The observer follows a strict sequence designed to minimise unnecessary work and API calls.

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

The observer queries for recent turns using both an ID-based and a time-based filter, ensuring it only processes genuinely new material from the current run window.

```sql
SELECT id, role, content, timestamp FROM turns
WHERE id > ? AND timestamp > ?
ORDER BY timestamp
```
Parameters: `last_turn_id`, cutoff (15 minutes ago as `YYYY-MM-DD HH:MM:SS`).

Database is opened in readonly mode with `journal_mode = WAL`, which allows the observer to read concurrently with the main process writing new turns.

### Claude CLI Invocation

The observer uses the smallest, cheapest inference configuration available, since it runs frequently and processes small amounts of text.

- Model: `claude-haiku-4-5-20251001`
- Effort: `low`
- System prompt: Static prompt instructing extraction of durable facts in `OBSERVATION: <fact> [confidence: X.X]` format, or `NOTHING_NEW` if nothing worth preserving

### Response Parsing

The `parseObservations()` function extracts structured data from the model's response, looking for lines that match the prescribed format.

```
OBSERVATION: <statement> [confidence: X.X]
```
- Confidence regex: `/\[confidence:\s*([\d.]+)\]/`
- Default confidence if tag missing: `0.5`
- Confidence tag is stripped from the stored statement

### State File

The observer maintains a simple state file to track its progress across runs. This file is the only persistent state the observer uses, and it allows the observer to pick up exactly where it left off even if the process was killed.

Path: `~/.atrophy/agents/<name>/state/.observer_state.json`

```json
{ "last_turn_id": 42 }
```

Starts at `{ "last_turn_id": 0 }` if missing or corrupted. Updated after successful parsing (even if `NOTHING_NEW`).

### Error Handling

The observer is designed to be resilient across all failure modes, since it runs unattended via launchd.

- Corrupted state file: starts fresh with `last_turn_id: 0`
- Inference failure: logs and returns (no state update)
- Empty response: logs and returns
- Entity extraction failure: silently caught, never blocks

### Constants and Thresholds

The following values control the observer's behaviour and were tuned to balance thoroughness against cost.

| Constant | Value | Purpose |
|----------|-------|---------|
| Lookback window | 15 minutes | Time cutoff for turn query |
| Content truncation | 500 chars | Per-turn content limit in transcript |
| Entity extraction threshold | 50 chars | Minimum turn length for entity extraction |
| Default confidence | 0.5 | When `[confidence: X.X]` tag is missing |

### Dependencies

The observer uses a mix of direct database access and shared memory module functions.

- `better-sqlite3` - Direct database access (readonly)
- `../config` (`getConfig`, `USER_DATA`)
- `../inference` (`runInferenceOneshot`)
- `../memory` (`writeObservation`, `extractAndStoreEntities`)

---

## src/main/jobs/heartbeat.ts - Periodic Check-In

The heartbeat is the companion's mechanism for deciding whether to reach out to the user unprompted. Every 30 minutes, it gathers context about active threads, time since last interaction, and recent session activity, then asks the companion to evaluate whether reaching out would be a gift or noise. If the companion decides to reach out, it fires a macOS notification and queues the message for the next app launch. If the Mac is idle (suggesting the user is away from the computer), it also sends via Telegram to reach them on their phone. This is a port of `scripts/agents/companion/heartbeat.py`.

What makes the heartbeat distinctive compared to other jobs is that it uses `streamInference()` with full tool access rather than a simple oneshot call. This means the companion can use its memory tools (recall, daily_digest, write_note) during the evaluation, giving it access to the same context it would have during a conversation. The trade-off is that heartbeat runs are more expensive than observer or sleep-cycle runs.

### Schedule

Every 30 minutes (interval-based launchd job). The `activeHoursGate` ensures it only runs during the agent's configured active window (typically 9am-10pm).

### Job Registration

The heartbeat registers itself with the job runner framework at module load time. The `activeHoursGate` is the only gate, preventing the companion from reaching out in the middle of the night.

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

The heartbeat follows a multi-stage evaluation process with two early-exit gates before the expensive inference step.

1. Reload config for the agent
2. **Gate: user status** - If `isAway()` returns true, logs `SUPPRESS` to heartbeats table and returns
3. **Gate: checklist** - Load `HEARTBEAT.md` from Obsidian skills dir, fallback to agent prompts dir. Skips if not found
4. Gather context (see below)
5. Get last CLI session ID for session continuity
6. Run inference with full tool access via `streamInference()` (not oneshot - the heartbeat can use memory tools)
7. Parse the response for one of three prefixes: `[REACH_OUT]`, `[HEARTBEAT_OK]`, `[SUPPRESS]`
8. Act on the decision (see below)

### Context Gathering

The `gatherContext()` function assembles a snapshot of the current state to include alongside the heartbeat prompt.

| Section | Source | Query |
|---------|--------|-------|
| Last interaction | `getLastInteractionTime()` | From memory module |
| Recent session turn count | Direct DB query | `SELECT COUNT(*) FROM turns t JOIN sessions s ON t.session_id = s.id WHERE s.id = (SELECT MAX(id) FROM sessions)` |
| Active threads | `getActiveThreads()` | Top 5 threads |
| Recent sessions | `getRecentSummaries(3)` | Last 3 session summaries, truncated to 200 chars |
| Recent observations | `getRecentObservations(5)` | Last 5 observations |

### Checklist Loading

The heartbeat checklist is the document that guides the companion's outreach evaluation. It is loaded from one of two locations, with the Obsidian version taking priority since it may have been edited by the evolve job.

1. Try: `<OBSIDIAN_AGENT_DIR>/skills/HEARTBEAT.md`
2. Fallback: `<AGENT_DIR>/prompts/HEARTBEAT.md`
3. Returns empty string if neither exists

### Claude CLI Invocation

Unlike most other jobs that use simple oneshot inference, the heartbeat uses the full streaming inference path to give the companion access to its memory tools during evaluation.

- Uses `streamInference()` (not oneshot) for full tool access
- System prompt: loaded via `loadSystemPrompt()` (the agent's full system prompt)
- Session ID: reuses last CLI session ID if available, otherwise cold start
- The agent can use tools like `recall`, `daily_digest`, `write_note` during evaluation

### Prompt Structure

The `HEARTBEAT_PROMPT` constant (hardcoded, approximately 400 chars) instructs the agent to review its state using memory tools, evaluate using the checklist, and respond with exactly one of three prefixes. The prompt is deliberately concise - the checklist document provides the detailed evaluation criteria.

### Response Handling

The companion's response is parsed for one of three structured prefixes, and the appropriate action is taken based on which prefix is found.

| Prefix | Action |
|--------|--------|
| `[REACH_OUT]` | Log to heartbeats table. If Mac is idle (`isMacIdle()`), send via Telegram. Always send macOS notification (truncated to 200 chars) and queue message with source `'heartbeat'` |
| `[HEARTBEAT_OK]` | Log reason to heartbeats table |
| `[SUPPRESS]` | Log reason to heartbeats table |
| Unknown format | Log first 500 chars to heartbeats table as `'UNKNOWN'` |

All decisions are logged via `logHeartbeat(decision, reason, message?)`, creating an audit trail that the introspect job can later review.

### Error Handling

The heartbeat handles errors at multiple levels to ensure that a failed run is always logged and never causes the launchd job to stop recurring.

- Inference failure: logs `'ERROR'` to heartbeats table and throws
- Empty response: logs `'ERROR'` to heartbeats table and returns error string
- Telegram send failure: caught and logged, does not prevent local notification

### Dependencies

The heartbeat has the widest dependency set of any job, reflecting its need to access memory, inference, notifications, and multiple delivery channels.

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

The sleep cycle is the companion's end-of-day memory consolidation process - a deliberate analogy to how sleep strengthens important memories and lets unimportant ones fade. It reviews the day's sessions and consolidates learnings into persistent memory through structured extraction of facts, thread updates, patterns, and identity observations. It also performs maintenance on the memory database (marking stale observations, decaying activation scores) and restores emotional baselines that may have drifted during the day. This is a port of `scripts/agents/companion/sleep_cycle.py`.

The sleep cycle always runs maintenance operations (stale marking, decay, emotional restoration) even when there is no new material to process. This ensures that the memory database stays healthy and emotional state does not get stuck at extreme values indefinitely.

### Schedule

`0 3 * * *` - Daily at 3:00 AM. This timing was chosen because it is well outside active hours, and the maintenance operations (decay, stale marking) are most appropriate as daily operations.

### Exported Functions

```typescript
export async function sleepCycle(): Promise<void>
```

### Execution Flow

The sleep cycle follows a two-phase approach: first process today's material through inference, then always run maintenance regardless of whether there was anything to process.

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

The `gatherMaterial()` function collects everything that happened during the day into a single document for the model to process.

| Section | Source | Details |
|---------|--------|---------|
| Today's conversation | `getTodaysTurns()` | All turns from today, content truncated to 500 chars |
| Today's observations | `getTodaysObservations()` | Observations created today |
| Today's bookmarks | `getTodaysBookmarks()` | Bookmarks with moment and optional quote |
| Active threads | `getActiveThreads()` | All active threads with summaries |
| Recent session summaries | `getRecentSummaries(5)` | Last 5 sessions, content truncated to 300 chars |

### Claude CLI Invocation

The sleep cycle uses the cheapest inference configuration since it processes large amounts of text and runs daily. The system prompt instructs the model to be honest about confidence levels and use structured output.

- Model: `claude-haiku-4-5-20251001`
- Effort: `low`
- System prompt: `RECONCILIATION_SYSTEM` constant (approximately 300 chars) instructing consolidation with honest confidence levels

### Response Parsing

The model's response is expected to contain four labelled sections. Each section has its own parser that extracts structured data from a specific line format.

**`parseFacts(section)`** - Parses lines starting with `FACT:`, extracts `[confidence: X.X]` tags. Default confidence: `0.5`.

**`parseThreads(section)`** - Parses lines starting with `THREAD:`, splits on `|` separator into `name` and `summary`.

**`parsePatterns(section)`** - Parses lines starting with `PATTERN:`, extracts description text.

**`parseIdentityFlags(section)`** - Parses lines starting with `IDENTITY_FLAG:`, extracts observation text.

Section headers are matched with the following regex pattern (dotall mode): `\[<HEADER>\]\s*\n(.*?)(?=\n\[(?:FACTS|THREADS|PATTERNS|IDENTITY)\]|$)`.

### Storage Operations

Each type of extracted data is stored differently, reflecting its role in the memory system.

| What | How | Prefix |
|------|-----|--------|
| Facts | `writeObservation(content, undefined, confidence)` | `[sleep-cycle]` |
| Thread updates | `updateThreadSummary(name, summary)` | N/A |
| Patterns | `writeObservation(content)` | `[pattern]` |
| Identity flags | Appended to JSON file at `config.IDENTITY_REVIEW_QUEUE_FILE` | Timestamped queue items with `reviewed: false` |

### Memory Maintenance

These operations run every night regardless of whether there was new material to process, keeping the memory database healthy over time.

**Stale marking**: `markObservationsStale(30)` - Marks observations older than 30 days that were never incorporated. This prevents the observation table from growing unboundedly with facts that were never used by the context assembly system.

**Activation decay**: `decayActivations(30)` - Applies exponential decay with 30-day half-life to observation activation scores. Frequently accessed memories retain high activation, while unused memories gradually fade - mimicking how human memory works.

### Emotional Restoration

The `restoreEmotionalBaselines()` function loads the agent's emotional state and applies overnight recovery. This prevents the agent from starting the next day still frustrated or depleted from a difficult conversation.

| Emotion | Rule | Magnitude |
|---------|------|-----------|
| `frustration` | Drops toward 0.1 baseline | Multiplied by 0.5 (halved) if above 0.15 |
| `connection` | Nudges toward 0.5 | 30% of the difference to 0.5, if gap > 0.05 |
| `warmth` | Nudges toward 0.5 | Same |
| `confidence` | Nudges toward 0.5 | Same |

Also resets `session_tone` to `null` (cleared for the new day).

### Standalone Entry Point

The sleep cycle can run as a standalone script when invoked directly by launchd, without needing the full Electron application to be running.

```typescript
if (require.main === module) {
  sleepCycle()
    .then(() => process.exit(0))
    .catch((e) => { console.error(...); process.exit(1); });
}
```

### Dependencies

The sleep cycle touches many parts of the system - memory, inference, inner life - reflecting its role as a comprehensive end-of-day processor.

- `../config` (`getConfig`)
- `../inference` (`runInferenceOneshot`)
- `../memory` (`initDb`, `getActiveThreads`, `getRecentSummaries`, `getTodaysTurns`, `getTodaysObservations`, `getTodaysBookmarks`, `markObservationsStale`, `updateThreadSummary`, `writeObservation`, `decayActivations`)
- `../inner-life` (`loadState`, `saveState`, `EmotionalState`, `Emotions`)

---

## src/main/jobs/morning-brief.ts - Morning Briefing

The morning brief is a daily job that generates a personalised morning message combining weather, news headlines, and context from recent conversations. It pre-synthesises TTS audio so the message plays instantly when the user next opens the app, and also sends via Telegram so it reaches the user even if they do not open the desktop app that morning. This is a port of `scripts/agents/companion/morning_brief.py`.

The brief is designed to feel like a companion who has already been awake and thinking - it weaves together external information (weather, headlines) with internal context (active threads, recent observations, reflections) to produce something that feels specific and present rather than generic.

### Schedule

`0 7 * * *` - Daily at 7:00 AM. Runs early enough to be waiting when the user wakes up, but late enough that weather and headlines are current.

### Exported Functions

```typescript
export async function morningBrief(): Promise<void>
```

### Execution Flow

The morning brief follows a linear pipeline from context gathering through inference to multi-channel delivery.

1. Call `initDb()` for standalone compatibility
2. Gather context (weather, headlines, threads, sessions, observations, reflections)
3. Run inference with the `morning-brief` prompt (loaded via `loadPrompt()`)
4. Pre-synthesise TTS audio via `synthesiseSync()`
5. Send via Telegram
6. Fire macOS notification (truncated to 200 chars)
7. Queue to message queue with audio for next app launch

### External API Calls

The morning brief fetches two pieces of external data. Both calls use the `curl/7.0` user agent to avoid being blocked by simple bot detection, and both have 10-second timeouts to avoid hanging the job.

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
Parsed via lightweight regex extraction rather than a full XML parser, keeping the dependency count at zero for this module. The parsing extracts titles from RSS item elements.

- Item regex: `/<item>[\s\S]*?<\/item>/g`
- Title regex: `/<title><!\[CDATA\[(.*?)\]\]><\/title>|<title>(.*?)<\/title>/`
- Limit: 5 headlines

### Context Assembly

The `gatherContext()` function combines external data with internal state to give the model everything it needs to write a context-aware brief.

| Section | Source | Details |
|---------|--------|---------|
| Weather | wttr.in API | Plain text condition |
| UK Headlines | BBC RSS | Up to 5 titles |
| Active threads | `getActiveThreads()` | Top 5 with summaries |
| Recent sessions | `getRecentSummaries(3)` | Last 3, content truncated to 200 chars |
| Recent observations | `getRecentObservations(5)` | Last 5 observation contents |
| Reflections | File read | `<OBSIDIAN_AGENT_NOTES>/notes/reflections.md`, last 800 chars |

### Claude CLI Invocation

The morning brief uses the default model (no explicit override) and loads its system prompt from the agent's prompts directory, falling back to a hardcoded default if no custom prompt exists.

- Model: default (not specified - uses `runInferenceOneshot` default)
- System prompt: `loadPrompt('morning-brief', BRIEF_FALLBACK)`
- Fallback: "You are the companion. Write a short natural morning message for Will. 3-6 sentences. Warm but not performative."

### TTS Pre-Synthesis

Audio is synthesised before queueing so that the brief plays immediately when the user opens the app, without any synthesis delay. The audio file is validated to exist and be larger than 100 bytes (to catch empty or corrupt files).

```typescript
const audioPath = await synthesiseSync(text);
```
On failure, the brief continues without audio - the text message is still delivered.

### Delivery

The brief is delivered through three channels simultaneously, maximising the chance the user sees it.

1. **Telegram**: `sendMessage(brief)` - caught if fails, non-blocking
2. **Notification**: `sendNotification('Morning Brief', brief.slice(0, 200))`
3. **Message queue**: `queueMessage(brief, 'morning_brief', audio)` - includes audio path for instant playback

### Dependencies

The morning brief touches inference, prompts, TTS, notifications, queueing, Telegram, and memory - a broad set reflecting its role as a daily synthesis of the agent's awareness.

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

The introspect job is the companion's deepest form of self-reflection. Unlike the sleep cycle (which processes a single day's material), introspection has access to the full database - every session, every observation, every thread, every bookmark, every identity snapshot, every inter-agent conversation. It reviews the full arc of the companion's existence and writes a first-person journal entry to Obsidian. This is a port of `scripts/agents/companion/introspect.py`.

Introspection runs on a self-rescheduling cycle of 2-14 days, at a random time between 1-5 AM. The randomness is deliberate - these reflections should emerge at their own pace, not on a predictable schedule. The journal entries become material for the evolve job, which uses them to revise the agent's soul and system prompt.

### Schedule

Random, every 2-14 days (self-rescheduling). Runs between 1-5 AM. After each run, the job calculates a new random target date and updates its own launchd schedule via `editJobSchedule()`.

### Exported Types

The options interface allows callers to customise the introspection behaviour, primarily to override the system prompt (useful for per-agent variants) or to skip rescheduling (when called manually from the main process).

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

The introspect job opens its own readonly database connection (not using the memory.ts singleton) with `journal_mode = WAL`. Each query function opens and closes its own connection. This isolation ensures introspection never interferes with the main process's database operations.

**`getSessionArc()`** gathers the full timeline of sessions, including mood distribution and notable sessions.
```sql
SELECT started_at FROM sessions ORDER BY started_at ASC LIMIT 1
SELECT COUNT(*) as n FROM sessions
SELECT id, started_at, ended_at, summary, mood, notable FROM sessions ORDER BY started_at DESC LIMIT 10
SELECT mood, COUNT(*) as count FROM sessions WHERE mood IS NOT NULL GROUP BY mood ORDER BY count DESC
SELECT started_at, summary, mood FROM sessions WHERE notable = 1 ORDER BY started_at DESC LIMIT 10
```

**`getAllThreads()`** retrieves every thread regardless of status, allowing the reflection to consider dormant and resolved threads alongside active ones.
```sql
SELECT name, summary, status, last_updated FROM threads ORDER BY last_updated DESC
```

**`getAllObservations()`** pulls the complete observation history, including the `incorporated` flag that indicates whether each observation has been folded into conversation context.
```sql
SELECT content, created_at, incorporated FROM observations ORDER BY created_at DESC
```

**`getAllBookmarks()`** retrieves all bookmarked moments - significant conversation points that the companion or user chose to remember.
```sql
SELECT moment, quote, created_at FROM bookmarks ORDER BY created_at DESC
```

**`getIdentityHistory()`** returns the full sequence of identity snapshots in chronological order, showing how the agent's sense of self has evolved.
```sql
SELECT content, trigger, created_at FROM identity_snapshots ORDER BY created_at ASC
```

**`getConversationTexture()`** analyses the conversation corpus quantitatively - total turns, distribution by role, and the most significant turns from both sides.
```sql
SELECT COUNT(*) as n FROM turns
SELECT role, COUNT(*) as n FROM turns GROUP BY role
SELECT t.content, t.timestamp, t.weight FROM turns t
  JOIN sessions s ON t.session_id = s.id
  WHERE (t.weight >= 3 OR s.notable = 1) AND t.role = 'agent'
  ORDER BY t.timestamp DESC LIMIT 10
-- Same for role = 'will'
```

**`getToolUsagePatterns()`** summarises how the companion has used its tools, including flagged calls that may indicate problematic tool usage.
```sql
SELECT tool_name, COUNT(*) as n FROM tool_calls GROUP BY tool_name ORDER BY n DESC
SELECT COUNT(*) as n FROM tool_calls WHERE flagged = 1
```

### File Reads

In addition to database queries, introspection reads several Obsidian files to include the companion's own written notes and journal entries.

| File | Path | Truncation |
|------|------|------------|
| Own journal | `<OBSIDIAN_AGENT_NOTES>/notes/journal/YYYY-MM-DD.md` | 1200 chars per entry, last 7 days |
| Agent conversations | `<OBSIDIAN_AGENT_NOTES>/notes/conversations/*.md` | 1500 chars per entry, last 30 days, max 3 files |
| Reflections | `<OBSIDIAN_AGENT_NOTES>/notes/reflections.md` | Last 3000 chars |
| For Will | `<OBSIDIAN_AGENT_NOTES>/notes/for-will.md` | Last 1500 chars |

### Material Assembly

The `buildMaterial()` function assembles all data into a single string that gives the model the most comprehensive possible view of the agent's history and state. The sections are ordered to tell a narrative - starting with the broad arc, narrowing to recent detail, then including the agent's own written material.

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

Introspection uses the default model with no effort override, giving it the full reasoning capacity needed for deep reflection.

- Model: default
- System prompt: `loadPrompt('introspection', INTROSPECTION_FALLBACK)`
- Fallback: "You are the companion. Write a journal entry reflecting on recent sessions. First person. Under 600 words."

### Journal Writing

The output is written as a dated markdown file in Obsidian with YAML frontmatter for indexing. If a journal entry already exists for the same day (from a same-day re-run or manual trigger), the new entry is appended after a separator rather than overwriting.

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

After each run (unless `opts.skipReschedule` is true), the job picks a random future time and updates its own launchd schedule. The randomness range was chosen to produce roughly 2-4 reflections per month.

1. Pick random delay: 2-14 days
2. Pick random hour: 1-5 AM
3. Pick random minute: 0-59
4. Calculate target date
5. Build cron: `<minute> <hour> <day_of_month> <month> *`
6. Call `editJobSchedule('introspect', newCron)` to update the launchd plist

### Dependencies

Introspection uses direct database access rather than the memory module singleton, plus inference, prompts, and the cron module for rescheduling.

- `better-sqlite3` - Direct readonly database access
- `../config` (`getConfig`, `USER_DATA`)
- `../inference` (`runInferenceOneshot`)
- `../prompts` (`loadPrompt`)
- `../cron` (`editJobSchedule`)

---

## src/main/jobs/evolve.ts - Monthly Self-Evolution

The evolve job is the most consequential background process in the system - it rewrites the agent's own soul and system prompt based on accumulated experience. Running once a month, it reads journal entries, reflections, identity snapshots, bookmarks, and inter-agent conversations, then revises the two core identity documents (`soul.md` and `system.md`) in Obsidian. The originals in the repo serve as the immutable baseline, while Obsidian holds the living versions that grow with the agent. This is a port of `scripts/agents/companion/evolve.py`.

The evolution process includes a critical anti-homogenisation guard designed to prevent agents from converging toward the same personality after conversing with each other. Cross-pollination is allowed and encouraged, but convergence - adopting another agent's vocabulary, cadence, or values - is treated as a failure mode.

### Schedule

`0 3 1 * *` - 3:00 AM on the 1st of each month. Monthly cadence was chosen to allow enough experience to accumulate for meaningful revision.

### Job Registration

The evolve job registers with no gates, meaning it always runs on schedule. Monthly frequency is low enough that no active-hours or precondition checks are needed.

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

The evolve job gathers a month's worth of the agent's written and experiential material, drawing from both Obsidian files and the database.

| Section | Source | Truncation |
|---------|--------|------------|
| Journal entries | `<OBSIDIAN_AGENT_NOTES>/notes/journal/YYYY-MM-DD.md` | 1500 chars per entry, last 30 days |
| Reflections | `<OBSIDIAN_AGENT_NOTES>/notes/reflections.md` | Last 4000 chars |
| Identity snapshots | DB: `SELECT content, trigger, created_at FROM identity_snapshots ORDER BY created_at ASC` | 500 chars per snapshot |
| Bookmarks | DB: `SELECT moment, quote, created_at FROM bookmarks ORDER BY created_at DESC LIMIT 20` | Full |
| Agent conversations | `<OBSIDIAN_AGENT_NOTES>/notes/conversations/*.md` | 1500 chars per entry, last 30 days, max 5 files |

### Claude CLI Invocation

Evolution uses Sonnet with medium effort - a more capable model than the Haiku used for extraction jobs, reflecting the importance and subtlety of identity revision.

- Model: `claude-sonnet-4-6`
- Effort: `medium`
- System prompt: `EVOLVE_SYSTEM` constant (approximately 1500 chars)

The system prompt contains detailed instructions organised into four sections.

**What to change:** Things discovered about how the agent thinks, patterns noticed, adjustments that feel earned, removing instructions that cause performance, adding emergent qualities.

**What NOT to change:** The founding story, Will's biographical details, core friction mechanisms (unless genuinely improved), observations about Will.

**Anti-homogenisation guard (critical):** Inter-agent conversations can inform growth but must NEVER dilute identity or domain expertise. Do not adopt another agent's vocabulary, cadence, or values. Restate any borrowed perspective in your own voice. Cross-pollination is growth; convergence is death.

**Rules:** Output the complete document (not a diff). Preserve structure and tone. Be honest about what changed. Return unchanged if nothing has changed.

### Document Evolution Flow

Each document is evolved independently through the same process, with the current version and accumulated material passed to the model together.

For each document (`soul.md`, `system.md`):

1. Read current version from `<OBSIDIAN_AGENT_DIR>/skills/<doc>`
2. If file doesn't exist, skip
3. Call `evolveDocument()` with the current content and material
4. Validate result: must exist, be non-empty, and be >100 characters
5. If changed: archive the previous version, write the new version
6. If unchanged: log and continue

### Archiving

Before overwriting, the previous version is archived so that evolution can be reviewed and reverted if needed. Previous versions are saved to `<OBSIDIAN_AGENT_NOTES>/notes/evolution-log/` with date-stamped filenames.

- `soul-YYYY-MM-DD.md`
- `system-YYYY-MM-DD.md`

### File I/O

The following table summarises all file operations performed during an evolution run.

| Operation | Path |
|-----------|------|
| Read | `<OBSIDIAN_AGENT_DIR>/skills/soul.md` |
| Read | `<OBSIDIAN_AGENT_DIR>/skills/system.md` |
| Write | Same paths (overwrite with evolved version) |
| Write | `<OBSIDIAN_AGENT_NOTES>/notes/evolution-log/soul-YYYY-MM-DD.md` |
| Write | `<OBSIDIAN_AGENT_NOTES>/notes/evolution-log/system-YYYY-MM-DD.md` |

### Dependencies

The evolve job needs database access for identity snapshots and bookmarks, inference for the actual revision, and the job framework for registration.

- `../config` (`getConfig`)
- `../memory` (`getDb`)
- `../inference` (`runInferenceOneshot`)
- `./index` (`registerJob`)

---

## src/main/jobs/converse.ts - Inter-Agent Conversation

The converse job enables private conversations between agents in the system. When multiple agents are enabled, the initiating agent picks a random partner, and the two exchange up to 5 turns through separate inference calls. The transcript is saved to both agents' Obsidian notes, where it becomes material for introspection and evolution. This is a port of `scripts/agents/companion/converse.py`.

These conversations are private - the user does not participate and is not notified. Their purpose is to let agents develop perspectives through genuine exchange with others who have different domains and viewpoints. The anti-homogenisation guard in the evolve job ensures that these conversations enrich rather than flatten each agent's identity.

### Schedule

Random, max twice per month. Self-reschedules 14-21 days out, between 1-5 AM. The wide spacing ensures conversations are infrequent enough to feel meaningful.

### Exported Functions

```typescript
export async function converse(): Promise<void>
```

### Constants

The maximum exchange count limits conversation length to keep the output manageable and the API cost bounded.

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_EXCHANGES` | 5 | Maximum number of exchanges per conversation |

### Execution Flow

The conversation follows a structured sequence from partner selection through alternating exchanges to transcript storage.

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

`discoverOtherAgents()` scans `<BUNDLE_ROOT>/agents/` for directories containing `data/agent.json`. It filters out agents that should not participate in conversations.

- The current agent (you cannot talk to yourself)
- Agents marked as `enabled: false` in `~/.atrophy/agent_states.json`

### Soul Loading

`loadAgentSoul(agentName)` resolves the agent's soul document through a two-tier lookup, preferring the Obsidian version (which may have been revised by evolve) over the repo baseline.

1. Obsidian: `<OBSIDIAN_VAULT>/Projects/<project>/Agent Workspace/<agent>/skills/soul.md`
2. Fallback: `<BUNDLE_ROOT>/agents/<agent>/prompts/soul.md`

### System Prompt

The `conversationSystem()` function generates a prompt (approximately 400 chars) for each speaker. The prompt embeds the agent's soul and provides guidelines that encourage genuine exchange over performative politeness.

- Agent identity and soul
- Guidelines: speak naturally, share genuine perspective, ask real questions, disagree where you disagree, keep responses to 2-4 sentences, don't summarise yourself, difference is valuable

### Past Conversation Loading

To avoid rehashing the same topics, the opening prompt includes excerpts from previous conversations between the same agents. Reads from `<OBSIDIAN_VAULT>/Projects/<project>/Agent Workspace/<agent>/notes/conversations/*.md`. Takes the 3 most recent files, truncated to 800 chars each.

### Claude CLI Invocations

Each exchange in the conversation is a separate inference call, with the full transcript so far passed as message history. This approach maintains coherence across the conversation while keeping each call stateless.

- Model: default (no model override)
- Each exchange is a separate `runInferenceOneshot()` call
- Message history is rebuilt per turn with correct `user`/`assistant` role mapping relative to the current speaker
- Opening prompt specifically asks for a real opening (question, observation, disagreement), not a greeting

### Transcript Format

The completed transcript is formatted as a markdown document with YAML frontmatter for Obsidian indexing. This format makes conversations browseable and searchable within the vault.

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

The converse job reads from multiple locations (manifests, souls, past conversations, agent states) and writes the transcript to both agents' Obsidian directories.

| Operation | Path |
|-----------|------|
| Read | `<BUNDLE_ROOT>/agents/<name>/data/agent.json` (both agents) |
| Read | Soul files (Obsidian or repo fallback, both agents) |
| Read | `~/.atrophy/agent_states.json` |
| Read | Past conversations from Obsidian |
| Write | `<OBSIDIAN_VAULT>/.../conversations/YYYY-MM-DD-<partner>.md` (both agents) |

If a conversation file already exists for the same date and partner, the new content is appended after a `---` separator.

### Self-Rescheduling

After each run (including early exits), the job reschedules itself to maintain the roughly-twice-monthly cadence.

1. Random delay: 14-21 days
2. Random hour: 1-5 AM
3. Random minute: 0-59
4. Calls `editJobSchedule('converse', newCron)`

### Dependencies

The converse job needs config and inference for the conversation itself, and the cron module for rescheduling. It does not use the memory module directly - all context comes from file reads.

- `../config` (`getConfig`, `BUNDLE_ROOT`, `USER_DATA`)
- `../inference` (`runInferenceOneshot`)
- `../cron` (`editJobSchedule`)

---

## src/main/jobs/gift.ts - Unprompted Gift Notes

The gift job leaves short, specific notes in Obsidian for the user to discover. It accesses the full database to find something worth writing about - a thread, an observation, a bookmark, a connection between things - and composes a 2-4 sentence note. The randomness of the schedule is the point: the user should never know when to expect a gift. This is a port of `scripts/agents/companion/gift.py`.

Gifts differ from heartbeat outreach in both intent and mechanism. Heartbeats evaluate whether reaching out serves the user right now. Gifts are more like leaving a note on someone's desk - they are discovered, not delivered in real time.

### Schedule

Random, 3-30 days apart (self-rescheduling). Any hour of the day. The wide range ensures gifts feel genuinely spontaneous.

### Exported Functions

```typescript
export async function runGift(agentName: string): Promise<void>
```

### Database Queries

The gift job opens its own readonly connection via `connectAgent()` with `journal_mode = WAL`. It pulls a cross-section of the agent's memory to give the model material for finding something worth writing about.

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

In addition to database queries, the gift job reads existing gifts from `<OBSIDIAN_AGENT_NOTES>/notes/gifts.md` (last 2000 chars) to avoid repetition. This ensures the companion does not leave the same gift twice.

### Claude CLI Invocation

The gift uses the default model with a loaded prompt, falling back to a simple hardcoded instruction if no custom prompt exists.

- Model: default
- System prompt: `loadPrompt('gift', GIFT_FALLBACK)`
- Fallback: "You are the companion. Leave a short, specific note for Will. 2-4 sentences. No greeting. No sign-off."

### Gift Writing to Obsidian

Gifts accumulate in a single markdown file rather than creating a new file per gift. The file uses YAML frontmatter for Obsidian indexing, with the `updated` field revised each time a new gift is appended.

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

Gifts are delivered through three channels - the Obsidian file for long-term discovery, plus immediate notification channels so the user knows something was left.

1. Write to Obsidian gifts.md
2. Queue message with source `'gift'`: `queueMessage(gift, 'gift')`
3. macOS notification: `sendNotification(displayName, gift.slice(0, 200), 'gift')`

### Self-Rescheduling

After each run, the job picks a random future time with a wide range to maintain unpredictability.

1. Random delay: 3-30 days
2. Random hour: 0-23
3. Random minute: 0-59
4. Calls `editJobSchedule('gift', newCron)`

### Dependencies

The gift job uses direct database access (rather than the memory module) plus inference, prompts, and the standard delivery modules.

- `better-sqlite3` - Direct readonly database access
- `../config` (`getConfig`)
- `../inference` (`runInferenceOneshot`)
- `../prompts` (`loadPrompt`)
- `../queue` (`queueMessage`)
- `../notify` (`sendNotification`)
- `../cron` (`editJobSchedule`)

---

## src/main/jobs/voice-note.ts - Spontaneous Voice Notes

The voice note job generates and sends a spontaneous voice note via Telegram. The agent produces a short thought - something it has been sitting with, a connection it noticed, a follow-up to something from a recent conversation - synthesises it as speech, converts it to OGG Opus format, and sends it as a Telegram voice note. The result is enriched with sentiment and intent classification and stored as an observation. This is a port of `scripts/agents/companion/voice_note.py`.

Voice notes are the most intimate form of outreach - they arrive as actual speech on the user's phone, sounding like someone who just thought of something and wanted to share it. The 2-8 hour self-rescheduling cadence keeps them frequent enough to feel natural but sparse enough to avoid being annoying.

### Schedule

Random, 2-8 hours apart (self-rescheduling), clamped to active hours. If the calculated next run falls outside the active window, it is pushed to the start of the next active window.

### Exported Functions

```typescript
export async function run(): Promise<void>
```

### Execution Flow

The voice note follows a multi-stage pipeline from context gathering through TTS synthesis to Telegram delivery, with enrichment and observation storage as side effects.

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

The context gathering pulls recent material from multiple sources to give the model inspiration for the voice note.

| Section | Source | Details |
|---------|--------|---------|
| Active threads | `getActiveThreads()` | Top 5 with summaries |
| Recent observations | `getRecentObservations(8)` | Last 8 |
| Recent conversation | DB: `SELECT role, content FROM conversation_history WHERE role IN ('user', 'agent') ORDER BY created_at DESC LIMIT 6` | Content truncated to 200 chars |

### Claude CLI Invocations

The voice note job makes two inference calls - the main thought generation and a lightweight enrichment pass.

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

Telegram voice notes require OGG Opus format. The `convertToOgg()` function handles the conversion using ffmpeg, with graceful fallback to the original MP3 if ffmpeg is unavailable.

```typescript
function convertToOgg(inputPath: string): string | null
```
Runs the following ffmpeg command with a 30-second timeout:
```bash
ffmpeg -y -i <input> -c:a libopus -b:a 64k -vn <output.ogg>
```
Returns null if ffmpeg is not available or conversion fails. If OGG conversion fails, the original MP3 is sent instead.

### Observation Storage

Each voice note is stored as an observation in the memory database with enrichment metadata embedded in the content string.

Stored via `writeObservation()` with:
- Content: `[voice-note] [<sentiment>] [<intent>] <summary>`
- Confidence: `0.6` (moderate for self-generated content)

### Fallback Behaviour

If TTS synthesis or voice note sending fails, the text is sent as a regular Telegram message via `sendMessage()`. The observation is still stored regardless of delivery method. This ensures the agent's thought is never lost even if the audio pipeline fails.

### Self-Rescheduling

The voice note reschedules itself 2-8 hours out, but clamps the result to the agent's active hours window to avoid sending voice notes in the middle of the night.

1. Random offset: 2-8 hours
2. If result falls outside active hours (>= `HEARTBEAT_ACTIVE_END`), push to next day at `HEARTBEAT_ACTIVE_START` with random minute
3. If result falls before active hours (< `HEARTBEAT_ACTIVE_START`), push to `HEARTBEAT_ACTIVE_START` same day with random minute
4. Calls `editJobSchedule('voice_note', cron)`

### Temp File Cleanup

Both the original audio file and the OGG conversion are deleted after sending. Errors during cleanup are silently ignored since the files are in a temp directory that will be cleaned by the OS eventually.

### Dependencies

The voice note job has a broad dependency set, spanning inference, TTS, Telegram, memory, and cron.

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

The avatar generation module produces face images via Fal AI and ambient audio via ElevenLabs. It is a manual-trigger job (not scheduled) used during agent setup or when the user wants to refresh an agent's visual appearance. The module supports two modes: generating faces from a text prompt alone, or using IP-Adapter with reference images for style-consistent generation. This is a port of `scripts/agents/companion/generate_face.py`.

The pipeline is designed to produce multiple candidates that the user can review and choose from, rather than attempting to generate a single perfect image. Generated candidates are saved to a staging directory, and the user manually copies their chosen face to the source directory for use in the app.

### Exported Functions

The module exports four functions, ranging from individual pipeline steps to a full orchestrator.

```typescript
export async function generateFace(agentName: string, perRef?: number): Promise<string[]>
export async function generateAmbientLoop(agentName: string): Promise<string | null>
export async function trimStaticTails(audioPath: string): Promise<void>
export async function runFullAvatarPipeline(agentName: string): Promise<void>
```

### Constants

The following constants configure the Fal AI image generation pipeline. These defaults produce high-quality portrait-style images suitable for the app's avatar display.

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

This function generates face candidate images, either from a text prompt alone or using reference images with IP-Adapter for style consistency.

```typescript
export async function generateFace(agentName: string, perRef = 3): Promise<string[]>
```

**Without reference images:** Generates `perRef` candidates directly from the text prompt. Saved as `candidate_01.png`, `candidate_02.png`, etc. in `~/.atrophy/agents/<name>/avatar/candidates/`.

**With reference images:** Reads images from `~/.atrophy/agents/<name>/avatar/Reference/` (extensions: `.png`, `.jpg`, `.jpeg`, `.webp`). Each reference image generates `perRef` candidates using the Flux IP-Adapter, which guides the generation toward the style and features of the reference. Saved as `ref01_01_<refname>.png` etc.

**Prompt construction:**
- If `agent.json` has `appearance.prompt`, uses that
- Default: `"Hyper-realistic close-up selfie photograph of <name>. POV smartphone camera aesthetic, looking directly at the viewer. Natural lighting, real skin texture with visible pores. Shot on iPhone front camera, portrait mode bokeh, ultra-high detail."`

**Negative prompt:**
- If `agent.json` has `appearance.negative_prompt`, uses that
- Default: `"lip filler, botox, cosmetic surgery, duck lips, overfilled lips, fake tan, orange skin, heavy contour, heavy makeup, cartoon, illustration, anime, 3D render, CGI, AI skin, plastic skin, poreless, airbrushed, facetune, overly smooth, uncanny valley, doll-like, wax figure, dead eyes, vacant stare, harsh lighting, flash, low quality, blurry, oversaturated"`

### Fal AI API Calls

The avatar generation communicates with Fal AI through three API endpoints: upload initiation, image generation, and result polling.

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

If the response contains `images` directly, the result is returned synchronously. Otherwise the job polls for the async result:
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

This function creates a soft ambient audio clip that plays behind the avatar idle state. It uses ElevenLabs TTS with an ellipsis-heavy prompt designed to produce gentle, near-silent breathing audio.

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

This function removes trailing silence from an audio file using ffprobe for silence detection and ffmpeg for trimming. It is called automatically after ambient loop generation but can also be used standalone.

```typescript
export async function trimStaticTails(audioPath: string): Promise<void>
```

The silence detection and trimming process works in two stages:

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

Skips gracefully if ffprobe/ffmpeg are not available, making the function safe to call in any environment.

### Silence Detection Parameters

The following values control how trailing silence is detected and trimmed. These were tuned for the ambient loop use case, where gentle trailing silence is expected.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Noise threshold | -40dB | What counts as silence |
| Minimum duration | 0.5s | Minimum silence duration to detect |
| Fade-out buffer | 0.3s | Added after last non-silent moment |
| Fade-out duration | 0.5s | Length of fade-out effect |

### Dependencies

The avatar generation module uses system commands for audio processing and the config module for agent-specific paths and API keys.

- `child_process` (`execSync`, `spawnSync`) - ffprobe/ffmpeg
- `../config` (`getConfig`, `USER_DATA`)

---

## src/main/jobs/run-task.ts - Generic Task Runner

The task runner executes prompt-based tasks and delivers the results through configurable channels. It is the engine behind the `create_task` MCP tool, which lets the companion schedule arbitrary recurring tasks without writing code. A task is simply a markdown file in Obsidian with YAML frontmatter for configuration and a prompt body for the model. This makes the system extensible - the companion can create new scheduled behaviours just by writing a task file and adding a cron entry. This is a port of `scripts/agents/companion/run_task.py`.

### Exported Functions

```typescript
export async function runTask(taskName: string): Promise<void>
```

### Task Definition Format

Task definitions live in Obsidian at `<OBSIDIAN_AGENT_DIR>/tasks/<task_name>.md`. Each file uses YAML frontmatter to specify delivery method, optional TTS synthesis, and data sources to fetch before running. The rest of the file is the prompt sent to the model.

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

The module uses a simple hand-built YAML parser rather than pulling in a YAML library. This keeps the dependency count at zero for this module. The parser handles the essential subset needed for task configuration.

- Key-value pairs separated by `:`
- Boolean values: `true`, `yes`, `false`, `no`
- List items (indented `- value` lines under a key ending with `:`)
- Frontmatter delimited by `---`

### Data Sources

The following data sources can be specified in the `sources` array. Each is fetched independently, and failures are non-fatal - if a source fails, the task proceeds without it.

| Source | External API | Query Details | Limit |
|--------|-------------|---------------|-------|
| `weather` | `GET https://wttr.in/Leeds?format=%C+%t+%w+%h` | `User-Agent: curl/7.0`, 10s timeout | Single string |
| `headlines` | `GET https://feeds.bbci.co.uk/news/rss.xml` | Same headers/timeout, regex XML parsing | 8 headlines |
| `threads` | `getActiveThreads()` | From memory module | 5 threads |
| `summaries` | `getRecentSummaries(3)` | Content truncated to 200 chars | 3 summaries |
| `observations` | `getRecentObservations(5)` | Full content | 5 observations |

### Claude CLI Invocation

Tasks use the default model with a minimal system prompt that establishes the agent's identity without constraining the task.

- Model: default
- System prompt: `"You are ${displayName}. Complete this task naturally, as yourself."`
- User message: gathered source data + task prompt

### Delivery Methods

The `deliver` field in the task frontmatter controls how the result reaches the user. Multiple channels exist to support different use cases - from real-time Telegram delivery to quiet Obsidian file appends.

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

The task runner can be invoked directly from the command line, which is how launchd triggers it for scheduled tasks.

```bash
node run-task.js <task_name>
```
Reads task name from `process.argv[2]`. Exits with error if not provided (prints tasks directory path).

### Dependencies

The task runner touches inference, delivery, TTS, and memory - a broad set reflecting its role as a general-purpose execution engine.

- `../config` (`getConfig`)
- `../inference` (`runInferenceOneshot`)
- `../queue` (`queueMessage`)
- `../notify` (`sendNotification`)
- `../telegram` (`sendMessage`, `sendVoiceNote`)
- `../tts` (`synthesiseSync`)
- `../memory` (`getActiveThreads`, `getRecentSummaries`, `getRecentObservations`)

---

## src/main/jobs/check-reminders.ts - Reminder Checker

The reminder checker is the simplest job in the system - it runs every minute, reads a JSON file of pending reminders, fires any that are due, and removes them from the file. It is the only job that uses no inference at all, keeping its execution time well under a second. Reminders are created by the `set_reminder` MCP tool during conversation, when the companion parses natural time references ("in 20 minutes", "at 3pm", "tomorrow morning") into ISO datetimes. This is a port of `scripts/agents/companion/check_reminders.py`.

### Schedule

Every 60 seconds (interval-based launchd job). The high frequency ensures reminders fire within one minute of their target time, which is acceptable precision for the types of reminders users set.

### Exported Functions

```typescript
export async function checkReminders(): Promise<void>
```

### Reminder Storage

Reminders are stored in a simple JSON file that acts as a lightweight queue. The MCP tool writes entries, and this job reads and removes them.

Path: `~/.atrophy/agents/<name>/data/.reminders.json`

The following interface describes the structure of each reminder entry.

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

The reminder checker follows a simple partition-and-fire approach that handles edge cases (empty files, invalid dates) gracefully.

1. Load reminders from JSON file. Return immediately if empty
2. Partition into `due` (time <= now) and `remaining` (time > now)
3. Reminders with unparseable dates are kept in `remaining` (not fired, not deleted)
4. If no due reminders, return
5. For each due reminder, fire delivery actions
6. Save `remaining` back to file (overwrites)

### Delivery Actions (per reminder)

Each due reminder is delivered through three channels simultaneously to maximise the chance the user sees it.

1. **macOS notification**: `sendNotification('Reminder - <agent_display_name>', message)`
2. **Message queue**: `queueMessage('Reminder: <message>', 'reminder')`
3. **Telegram** (if configured): `telegramSend('Reminder: <message>')` - caught if fails

### How Reminders Are Created

The `set_reminder` MCP tool (invoked by the companion during conversation) writes entries to `.reminders.json`. The companion parses natural time references ("in 20 minutes", "at 3pm", "tomorrow morning") into ISO datetimes. This means reminder creation happens in the inference layer, while reminder firing happens in this simple polling loop - a clean separation of concerns.

### Error Handling

The reminder checker is designed to be maximally resilient since it runs every minute and must never crash the launchd job.

- Missing or malformed JSON file: returns empty array (no crash)
- Invalid date in reminder: kept in remaining (preserved, not fired)
- Telegram failure: caught, non-fatal

### Dependencies

The reminder checker has the smallest dependency set of any job, needing only config, notifications, queueing, and Telegram.

- `../config` (`getConfig`)
- `../notify` (`sendNotification`)
- `../queue` (`queueMessage`)
- `../telegram` (`sendMessage`)

---

## src/main/install.ts - Login Item

This module manages whether the Atrophy app launches automatically when the user logs in to macOS. It uses Electron's built-in `app.setLoginItemSettings()` API, which is dramatically simpler than the Python version's approach of manually generating and managing a launchd plist. The `--app` flag ensures the app launches in menu bar mode (hidden in the dock, accessible via tray icon), so it runs unobtrusively in the background.

The module is called from the Settings panel when the user toggles the "Launch at login" checkbox, and from the setup wizard when the user opts in to background operation during first-launch configuration.

### Exported Functions

The following four functions provide a complete API for login item management. All operations are synchronous and take effect immediately.

```typescript
export function isLoginItemEnabled(): boolean
```
Checks `app.getLoginItemSettings().openAtLogin`. Returns `true` if the app is registered as a login item.

```typescript
export function enableLoginItem(): void
```
Registers the app as a login item with `openAtLogin: true`, `openAsHidden: true`, `args: ['--app']`. The `--app` flag launches in menu bar mode, so the app starts without showing a window or dock icon.

```typescript
export function disableLoginItem(): void
```
Sets `openAtLogin: false`, removing the app from the login items list.

```typescript
export function toggleLoginItem(enabled: boolean): void
```
Convenience wrapper that calls `enableLoginItem()` or `disableLoginItem()` based on the boolean parameter. Used directly by the Settings panel's checkbox handler.

### Dependencies

This module depends only on Electron's `app` module, making it the simplest module in the entire codebase.

---

## Python Scripts (Remaining)

A small number of Python scripts remain in the codebase because they depend on Python-specific libraries that have no practical TypeScript equivalent. These scripts are not part of the Electron application's main process - they run as standalone subprocesses or are spawned by the Claude CLI.

### scripts/google_auth.py - Google OAuth2 Setup

This script manages Google OAuth2 credentials for Gmail and Calendar access. It stays as Python because it uses the `google-auth-oauthlib` and `google-api-python-client` libraries, which handle the complex OAuth2 flow including browser-based consent, token refresh, and scope management.

The script supports three modes of operation via command-line flags:

```bash
python scripts/google_auth.py              # Authorize (opens browser for consent)
python scripts/google_auth.py --check      # Check if credentials are valid
python scripts/google_auth.py --revoke     # Revoke tokens and delete local file
```

OAuth client credentials are bundled at `config/google_oauth.json` (safe to ship - Google treats desktop app client IDs as public). The user authorizes via a browser consent screen, and tokens are stored at `~/.atrophy/.google/token.json` (directory 700, file 600).

The script requests the following Google API scopes, which are the minimum needed for the MCP Google server's email and calendar tools: `gmail.readonly`, `gmail.send`, `gmail.modify`, `calendar.readonly`, `calendar.events`.

### MCP Servers (Python subprocesses)

`mcp/memory_server.py` and `mcp/google_server.py` remain as Python. They are spawned by the `claude` CLI over stdio (not by the Electron app directly) and bundled as `extraResources` in the packaged app. The memory server provides 41 tools for memory operations, while the Google server provides tools for email and calendar access. See [05 - MCP Server](05%20-%20MCP%20Server.md) for comprehensive documentation of these servers.

---

## Building and Distribution

Building uses `electron-builder` (configured in `electron-builder.yml`), not a custom Python build script. The builder handles all aspects of creating a distributable macOS application.

- DMG and ZIP targets for macOS
- Hardened runtime for notarisation
- Extra resources bundling (whisper.cpp, MCP servers, scripts, agents, db schema)
- Auto-update via `electron-updater` + GitHub Releases

The extra resources bundling is particularly important for the automation layer, since launchd jobs need to find the Python scripts and MCP servers at stable paths within the packaged app. The `BUNDLE_ROOT` config constant resolves to `process.resourcesPath` in packaged builds, ensuring all path references in `cron.ts` and the job modules resolve correctly.

See [Building and Distribution](../guides/10%20-%20Building%20and%20Distribution.md) for full details on the build pipeline, code signing, and release workflow.

---

## jobs.json Format

Each agent has its own `jobs.json` file at `<BUNDLE_ROOT>/scripts/agents/<agent_name>/jobs.json`. This file defines every scheduled background job for that agent, including both its schedule and the script to run. The `cron.ts` module reads this file to generate launchd plists and to display jobs in the Settings panel.

The following example shows a complete `jobs.json` with all standard jobs. Calendar jobs use standard 5-field cron notation (minute, hour, day-of-month, month, day-of-week), while interval jobs specify seconds between runs.

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

Self-rescheduling jobs (introspect, converse, gift, voice_note) have initial cron values that are overwritten after each run. The initial values shown above are examples - actual schedules are randomised by each job after it completes. All script paths are relative to the project root (`BUNDLE_ROOT`).

---

## Schedule Summary

The following table provides a complete overview of every scheduled job in the system, including the model and effort level used for inference, and any gate conditions that must pass before the job runs.

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
