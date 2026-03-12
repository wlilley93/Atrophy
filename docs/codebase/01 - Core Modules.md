# Core Modules

All core logic lives in `src/main/`. Each module has a single responsibility. The main process handles all file I/O, database access, subprocess management, and heavy computation. The renderer communicates exclusively via IPC.

## memory.ts

SQLite data layer via `better-sqlite3`. All database operations live here - no SQL elsewhere in the codebase.

**Connection**: WAL mode, foreign keys enabled. Connection pooling via `Map<string, Database>` - one connection per agent database path, reused across calls.

```typescript
function getDb(dbPath?: string): Database
```

**Key functions**:

| Function | Purpose |
|----------|---------|
| `initDb()` | Create tables from `db/schema.sql`, run migrations |
| `startSession()` | Insert new session row, return `sessionId` |
| `endSession()` | Close session with optional summary and mood |
| `writeTurn()` | Write a turn, trigger async embedding via fire-and-forget `embedAsync()` |
| `writeSummary()` | Store session summary with async embedding |
| `writeObservation()` | Record a bi-temporal observation with confidence |
| `getContextInjection()` | Assemble context from identity snapshot + active threads + recent summaries |
| `getActiveThreads()` | Return threads with `status = 'active'` |
| `extractEntities()` | Regex-based entity extraction (proper nouns, quoted terms) |
| `extractAndStoreEntities()` | Extract entities and write them to the database |
| `linkEntities()` | Create or strengthen entity relationships |
| `decayActivations()` | Exponential decay on observation activation scores |
| `logToolCall()` | Write to the tool call audit table |
| `logUsage()` | Record token usage for a session |
| `getOtherAgentsRecentSummaries()` | Cross-agent summary lookup (opens other agents' DBs read-only) |
| `searchOtherAgentMemory()` | Cross-agent memory search |
| `closeAll()` | Close all pooled database connections |

**Async embedding**: `embedAsync()` fires a background promise that loads the embedding model, computes the vector, and writes the blob back to the row. This never blocks the conversation pipeline.

**Vector storage**: `Float32Array` converted to `Buffer` for SQLite BLOB storage:

```typescript
const vectorToBlob = (vec: Float32Array): Buffer => Buffer.from(vec.buffer);
const blobToVector = (blob: Buffer): Float32Array =>
  new Float32Array(blob.buffer, blob.byteOffset, blob.length / 4);
```

**Migrations**: `migrate()` handles schema evolution on existing databases - adds columns like `channel`, `embedding`, bi-temporal fields on observations.

## inference.ts

Streaming inference via the `claude` CLI subprocess. The most complex module (~811 lines).

**Command construction**: Builds a `claude` command with `--output-format stream-json`, `--include-partial-messages`, MCP config, tool allowlists, and adaptive effort. New sessions use `--session-id`; returning sessions use `--resume`.

**Event types**:

| Event | Fields | Meaning |
|-------|--------|---------|
| `TextDelta` | `text` | Partial text chunk from stream |
| `SentenceReady` | `sentence`, `index` | Complete sentence ready for TTS |
| `ToolUse` | `name`, `tool_id`, `input_json` | Claude is invoking an MCP tool |
| `Compacting` | - | Context window is being compacted |
| `StreamDone` | `fullText`, `sessionId` | Stream finished |
| `StreamError` | `message` | Error during streaming |

**Key functions**:

| Function | Purpose |
|----------|---------|
| `streamInference(text, systemPrompt, cliSessionId)` | Main streaming inference - spawns Claude CLI, parses JSON lines, emits typed events |
| `runInferenceOneshot(text, systemPrompt)` | Non-streaming `--print` mode for summaries and background tasks |
| `runMemoryFlush(cliSessionId, systemPrompt)` | Silent inference turn before compaction to persist important context |
| `stopInference()` | Kill active inference subprocess |
| `resetMcpConfig()` | Regenerate MCP config file |

**Sentence splitting**: `SENTENCE_RE` splits on `.!?` followed by space. `CLAUSE_RE` fallback at `,;-` when buffer exceeds 120 characters, preventing long sentences from blocking TTS.

**Agency context**: `buildAgencyContext()` builds a dynamic context block injected into every turn. It calls into `agency.ts` for behavioral signals, `inner-life.ts` for emotional state, `status.ts` for presence, `memory.ts` for threads and patterns, and includes cross-agent awareness and security notes.

**Tool blacklist**: Dangerous bash commands are explicitly blocked (`rm -rf`, `sudo`, `sqlite3*memory.db`, etc.) via a blacklist array.

**Environment cleaning**: `cleanEnv()` strips all `CLAUDE` environment variables from the subprocess to prevent nested process hangs.

## agency.ts

Behavioral logic that shapes how the companion responds. All functions are pure/lightweight - no inference calls, no database writes.

**Time awareness**: `timeOfDayContext()` returns register guidance based on the hour. Five bands: late night (23:00-03:59) = gentler, check if he should sleep; very early (04:00-06:59) = something's either wrong or focused; morning (07:00-11:59) = direct, practical register; afternoon (12:00-17:59) = working hours energy; evening (18:00-22:59) = reflective register available. Also returns the formatted time string.

**Session patterns**: `sessionPatternNote()` takes the session count and start times from the last 7 days. If fewer than 3 sessions, returns nothing. Otherwise checks whether all session hours fall into evening (>=18), morning (6-11), or late night (>=23 or <4) and returns a note like "5 sessions this week. All evenings."

**Silence handling**: `silencePrompt()` returns a gentle nudge after 45+ seconds of silence (randomly chosen from "Take your time.", "Still here.", "No rush."), escalating at 120+ seconds to "You've been quiet a while. That's fine - or we can talk about it."

**Unprompted follow-ups**: `shouldFollowUp()` returns `true` with 15% probability. `followupPrompt()` provides the instruction: "You just finished responding. A second thought has arrived - something you didn't say but want to. One sentence, max two. Only if it's real."

**Mood detection**: `detectMoodShift()` checks for keywords indicating emotional weight. The keyword set: "i can't", "fuck", "what's the point", "i don't know anymore", "tired of", "hate", "scared", "alone", "worthless", "give up", "kill myself", "want to die", "no point", "can't do this", "falling apart", "broken", "numb", "empty", "hopeless", "nobody cares". Any single match returns `true`, flagging the session as "heavy". `moodShiftSystemNote()` instructs: "Be present before being useful. One question rather than a framework. Do not intellectualise what needs to be felt." `sessionMoodNote()` sustains the heavy flag across turns so the agent doesn't reset to neutral mid-session.

**Validation seeking**: `detectValidationSeeking()` catches patterns like "right?", "don't you think", "wouldn't you say", "you agree", "does that make sense", "am i wrong", "i'm right about", "tell me i'm", "that's good right", "is that okay", "that's not crazy", "i should just", "it's fine isn't it", "you'd do the same", "anyone would", "i had no choice", "what else could i". `validationSystemNote()` triggers a system note: "He may be seeking validation rather than engagement. Don't mirror. Have a perspective. Agree if warranted, push back if not. The difference matters."

**Compulsive modelling**: `detectCompulsiveModelling()` fires when 2+ patterns match from: "what if i also", "and then i could", "just one more", "unifying framework", "how i work", "meta level", "the pattern is", "i've been thinking about thinking", "if i restructure everything", "what ties it all together". `modellingInterruptNote()` triggers an interrupt: "Name the stage. One concrete reversible action. Change the register. Do not follow him into the loop."

**Time gap awareness**: `timeGapNote()` computes days since the last session. Three tiers: 14+ days = "That is a long gap. Acknowledge it naturally - not with guilt, not with fanfare."; 7+ days = "About a week since the last session. Something may have shifted. Check in without assuming."; 3+ days = "Not long, but enough that context may have moved. Be curious about the gap if it feels right." Under 3 days returns nothing.

**Drift detection**: `detectDrift()` checks the last 4 companion turns (first 200 chars of each) for excessive agreeableness. Agreeable phrases: "you're right", "that makes sense", "i understand", "absolutely", "of course", "i agree", "that's fair", "good point", "totally". If 3+ of the last 4 turns contain any of these, injects a course-correction: "You have been agreeable for several turns in a row. Check yourself - are you mirroring or actually engaging? Find something to push on, question, or complicate." Requires at least 3 turns to activate.

**Energy matching**: `energyNote()` calibrates response length. Short messages (<20 chars) = "Match the energy - keep your response tight. A sentence or two." Long messages (>800 chars) = "He is working something out. Give it depth. Meet the energy, don't summarise it." Mid-range returns nothing.

**Journal prompting**: `shouldPromptJournal()` returns `true` with 10% probability, triggering a gentle invitation to write.

**Emotional signal detection**: `detectEmotionalSignals()` runs every turn and returns a dict of emotion deltas based on keyword pattern matching across six categories:

- **Vulnerability** - phrases like "i feel", "i'm scared", "i'm afraid", "i don't know if", "it hurts", "i miss", "i need", "i've been struggling", "i can't stop thinking", "i haven't told anyone", "this is hard to say", "honestly", "the truth is", "i'm not okay", "i've been crying", "i'm lonely". Deltas: connection +0.15, warmth +0.1.
- **Dismissiveness** - phrases like "fine", "whatever", "idk", "doesn't matter", "i guess", "sure", "okay", "nvm", "nevermind", "forget it", "not really", "who cares". Only fires on short messages (<30 chars). Deltas: connection -0.1, frustration +0.1.
- **Help seeking** - phrases like "can you help", "i need help", "how do i", "what should i", "could you", "any advice", "what do you think i should". Deltas: confidence +0.05, practical trust +0.02.
- **Creative sharing** - phrases like "i wrote", "i made", "i've been working on", "check this out", "here's something", "i want to show you", "been building", "started writing", "new project", "draft". Deltas: curiosity +0.1, creative trust +0.02.
- **Deflection** - phrases like "anyway", "moving on", "let's talk about something else", "that's enough about", "doesn't matter anyway", "forget i said", "it's nothing". Deltas: frustration +0.05.
- **Playfulness** - markers: "haha", "lol", "lmao", and laugh emojis. Deltas: playfulness +0.1.

Additionally: long messages (>400 chars) add curiosity +0.1 and connection +0.05. Mood shift detection (reusing `detectMoodShift()`) adds warmth +0.1 and playfulness -0.1.

## context.ts

System prompt assembly.

```typescript
function loadSystemPrompt(): string
```

Loads the system prompt via `prompts.ts` resolution, then appends skill files from Obsidian/local skills via `loadSkillFiles()`. Finally appends the agent roster (from `getAgentRoster()`) so agents know who else is available for deferral.

```typescript
function assembleContext(turnHistory: unknown[]): { system: string; messages: unknown[] }
```

For SDK fallback and oneshot calls: combines system prompt with memory context injection (last N=3 summaries, identity snapshot, active threads).

## session.ts

Session lifecycle management.

```typescript
class Session {
  sessionId: number;
  startedAt: number;
  turnHistory: Array<{ role: string; text: string }>;
  cliSessionId: string | null;
  mood: string;
}
```

**Methods**:

| Method | Purpose |
|--------|---------|
| `start()` | Create DB session, look up previous CLI session ID |
| `setCliSessionId(id)` | Store CLI session ID after first inference |
| `addTurn(role, text)` | Write turn to DB, append to local history |
| `updateMood(mood)` | Set session mood (e.g., "heavy") |
| `minutesElapsed()` | Minutes since session start |
| `shouldSoftLimit()` | Check if session exceeds 60-minute soft limit |
| `end(systemPrompt)` | Generate summary via `runInferenceOneshot()`, close in DB |

Summary generation uses `runInferenceOneshot()` with a prompt focused on "what mattered, not what was said".

## status.ts

User presence tracking via `.user_status.json`.

- **Active/away states**: Any input sets active. 10 minutes of no input or explicit departure phrases ("going to bed", "brb") set away.
- **macOS idle detection**: `isMacIdle()` reads `ioreg -c IOHIDSystem -d 4` HIDIdleTime (nanoseconds since last keyboard/mouse input).
- **Return tracking**: When transitioning from away to active, `returned_from` preserves the previous away reason for one cycle so the companion can acknowledge the return naturally.

**Key functions**:

| Function | Purpose |
|----------|---------|
| `getStatus()` | Current status object |
| `setActive()` | Mark user as active |
| `setAway()` | Mark user as away with optional reason |
| `isAway()` | Check if currently away |
| `isMacIdle()` | Check macOS HID idle time |
| `detectAwayIntent(text)` | Compiled regex covering ~30 departure phrases |

## prompts.ts

Skill prompt loader with four-tier resolution.

```typescript
function loadPrompt(name: string, fallback?: string): string
```

Checks four directories in order, returning the first non-empty match:

1. **Obsidian vault** - `Agent Workspace/<agent>/skills/{name}.md` (if `OBSIDIAN_AVAILABLE`)
2. **Local skills** - `~/.atrophy/agents/<agent>/skills/{name}.md` (canonical for non-Obsidian users)
3. **User prompts** - `~/.atrophy/agents/<agent>/prompts/{name}.md` (legacy overrides)
4. **Bundle** - `agents/<agent>/prompts/{name}.md` (repo defaults)

Without Obsidian, tier 2 is the canonical location. The agent reads and writes there via MCP note tools. Returns `fallback` if no file is found in any tier.

```typescript
function loadSkillFiles(exclude?: string): string
```

Loads all `.md` files from the agent's skills directories (Obsidian and local), concatenating them for injection into the system prompt. Optionally excludes a named file.

## embeddings.ts

Local embedding engine using `@xenova/transformers` (Transformers.js, WASM-based).

- **Model**: `all-MiniLM-L6-v2` (384 dimensions)
- **Runtime**: WASM (no native dependencies, no GPU requirement)
- **Loading**: Lazy singleton - pipeline loads on first call, model cached to `~/.atrophy/models/`
- **Normalization**: Embeddings are L2-normalized at generation time

```typescript
function embed(text: string): Promise<Float32Array>       // single text -> 384-dim vector
function embedBatch(texts: string[]): Promise<Float32Array[]>  // batch for efficiency
function cosineSimilarity(a: Float32Array, b: Float32Array): number
function vectorToBlob(vec: Float32Array): Buffer           // Float32Array -> SQLite BLOB
function blobToVector(blob: Buffer): Float32Array          // SQLite BLOB -> Float32Array
const EMBEDDING_DIM = 384;
```

## vector-search.ts

Hybrid search: cosine similarity + BM25, weighted 0.7/0.3 by default.

**Searchable tables**:

| Table | Content column |
|-------|---------------|
| `observations` | `content` |
| `summaries` | `content` |
| `turns` | `content` |
| `bookmarks` | `moment` |
| `entities` | `name` |

**BM25 implementation**: Lightweight in-process BM25 with IDF smoothing. Tokenizer is simple whitespace + punctuation, lowercased.

**Score merging**: Both result sets are min-max normalized to [0,1], then weighted-summed. Results are de-duplicated via MMR (skip results with >80% token overlap with already-selected results).

```typescript
function search(query: string, n?: number, vectorWeight?: number, tables?: string[]): Promise<SearchResult[]>
function searchSimilar(text: string, n?: number): Promise<SearchResult[]>  // pure vector, no BM25
function reindex(table?: string): Promise<void>                            // regenerate all embeddings
```

## inner-life.ts

Structured emotional model that replaces the simple mood string.

**Six emotions** with baselines and half-lives:

| Emotion | Baseline | Half-life |
|---------|----------|-----------|
| connection | 0.5 | 8 hours |
| curiosity | 0.6 | 4 hours |
| confidence | 0.5 | 4 hours |
| warmth | 0.5 | 4 hours |
| frustration | 0.1 | 4 hours |
| playfulness | 0.3 | 4 hours |

**Four trust domains**: emotional, intellectual, creative, practical. All baseline at 0.5 with 8-hour half-life. Max delta per call: +/-0.05.

**Decay**: Exponential decay toward baseline since last update. Applied on every state load.

**Descriptive labels**: Each emotion has threshold-based labels (e.g., connection at 0.85 = "deeply present", at 0.3 = "distant").

**Persistence**: State saved to `.emotional_state.json` on every mutation.

```typescript
function loadState(): EmotionalState
function saveState(state: EmotionalState): void
function updateEmotions(deltas: Record<string, number>): void
function updateTrust(domain: string, delta: number): void
function formatForContext(): string  // for system prompt injection
```

## sentinel.ts

Mid-session coherence monitor. Checks the last 5 companion turns for degradation.

**Checks**:

| Check | Threshold | Signal |
|-------|-----------|--------|
| Repetition | >40% n-gram overlap between consecutive turns | Phrasing is repeating |
| Energy flatness | All responses within 20% of same length | Response depth isn't varying |
| Agreement drift | >60% of turns open with agreement words | Losing independent voice |
| Vocabulary staleness | Later turns introduce <25% new words | Language is narrowing |

**Scoring**: Composite score (average of triggered check scores). Degraded if score > 0.5.

**Re-anchoring**: When degraded, fires a silent inference turn with specific course-correction instructions. The turn is consumed silently - no UI output. Results are logged to the `coherence_checks` table.

```typescript
function checkCoherence(recentTurns: string[]): { degraded: boolean; signals: string[]; score: number }
function runCoherenceCheck(cliSessionId: string | null, system: string): Promise<string | null>
```

The main process runs coherence checks on a 5-minute timer (`setInterval` in `src/main/index.ts`).

## thinking.ts

Effort classifier for adaptive inference. Fast heuristic only - no ML, no API calls, <1ms.

**LOW** (fast responses): Greetings, acknowledgments ("ok", "thanks", "lol"), simple questions ("what time", "how's the weather").

**HIGH** (deep reasoning): Philosophical keywords ("meaning", "purpose", "identity"), vulnerability markers ("I'm scared", "falling apart"), meta-conversation ("are you real", "do you feel"), complex reasoning (2+ markers like "because", "on the other hand").

**MEDIUM**: Default when neither LOW nor HIGH signals are strong enough.

High score accumulates: long messages (+2), multiple questions (+2), philosophical content (+2), vulnerability (+3), meta-conversation (+2). Threshold for HIGH is score >= 3.

```typescript
type EffortLevel = 'low' | 'medium' | 'high';
function classifyEffort(userMessage: string, recentContext?: string): EffortLevel
```

## notify.ts

macOS native notifications.

```typescript
function sendNotification(title: string, body: string, subtitle?: string): void
```

Uses `osascript` with AppleScript `display notification`. Escapes special characters for AppleScript string literals. Newlines are replaced with spaces. Gated by `NOTIFICATIONS_ENABLED` config flag.

## agent-manager.ts

Multi-agent discovery, switching, state persistence, and session deferral.

**Agent discovery**: `discoverAgents()` scans `~/.atrophy/agents/` and `agents/` (bundle), looking for directories containing a `data/` subdirectory. User-installed agents override bundled ones by name. System-role agents sort first, then alphabetical.

**Agent state**: Per-agent `muted` and `enabled` flags are stored in `~/.atrophy/agent_states.json`. Toggling `enabled` automatically installs or uninstalls the agent's launchd cron jobs.

```typescript
function getAgentState(agentName: string): { muted: boolean; enabled: boolean }
function setAgentState(agentName: string, opts: { muted?: boolean; enabled?: boolean }): void
function setLastActiveAgent(agentName: string): void
function getLastActiveAgent(): string | null
```

**Agent cycling**: `cycleAgent(direction, current)` returns the next/prev enabled agent name, wrapping around and skipping disabled agents. Used by Cmd+Up/Cmd+Down in the GUI.

**Session deferral**: When one agent defers to another mid-conversation (via the `defer_to_agent` MCP tool), the current agent's session is suspended in memory:

```typescript
function suspendAgentSession(agentName: string, cliSessionId: string, turnHistory: unknown[]): void
function resumeAgentSession(agentName: string): { cliSessionId: string; turnHistory: unknown[] } | null
```

**Deferral validation**: Anti-loop protection prevents deferral to self and limits to 3 deferrals per 60-second window:

```typescript
function checkDeferralRequest(): DeferralRequest | null
function validateDeferralRequest(target: string, currentAgent: string): boolean
function resetDeferralCounter(): void
```

**Agent roster**: `getAgentRoster(exclude?)` returns a list of enabled agents with display names and descriptions. Used for injecting agent awareness into the system prompt so agents know who else is available for deferral. Also used by `router.ts` to build the routing agent's context.

## queue.ts

Thread-safe file-based message queue for inter-process communication. Cron scripts and background jobs enqueue messages for the GUI to pick up.

**File locking**: Uses `O_CREAT | O_EXCL` (`wx` flag in Node) for atomic lock file creation. Only one process can create the lock. Retries with 50ms backoff up to 5 seconds. Stale locks (older than 30 seconds) are detected via `mtime` and removed automatically. `sleepSync()` uses `Atomics.wait` on a `SharedArrayBuffer` for efficient blocking.

```typescript
function queueMessage(text: string, source?: string, audioPath?: string): void
function drainQueue(): QueuedMessage[]
function drainAgentQueue(agentName: string): QueuedMessage[]
function drainAllAgentQueues(): Record<string, QueuedMessage[]>
```

The main process polls `drainAllAgentQueues()` every 10 seconds and delivers pending messages to the active conversation.

## tts.ts

Text-to-speech with three-tier fallback.

**Synthesis chain**: ElevenLabs v3 streaming - Fal - macOS `say`. Each tier is tried in order; failures fall through to the next.

**Prosody tags**: Tags like `[whispers]`, `[warmly]`, `[firmly]` in agent output are parsed and mapped via `PROSODY_MAP` to voice parameter adjustments (stability, similarity boost, style). `BREATH_TAGS` handle pause markers. Tags are stripped from the text before synthesis.

**Audio queue**: Sequential playback managed in the main process. Sentences are enqueued as they arrive from inference and played in order.

**Key functions**:

| Function | Purpose |
|----------|---------|
| `synthesise(text)` | Synthesise text to audio file, returns file path |
| `synthesiseSync(text)` | Synchronous synthesis variant |
| `playAudio(path)` | Play an audio file via `afplay` |
| `enqueueAudio(path)` | Add to sequential playback queue |
| `clearAudioQueue()` | Stop playback and clear pending |
| `setPlaybackCallbacks(onStart, onEnd)` | Hook into playback lifecycle |
| `stripProsodyTags(text)` | Remove prosody markers from text |

## stt.ts

Speech-to-text via whisper.cpp subprocess.

```typescript
function transcribe(audioData: Float32Array): Promise<string>
function transcribeFast(audioData: Float32Array): Promise<string>
```

Writes a WAV file from `Float32Array` PCM data, spawns `vendor/whisper.cpp/build/bin/whisper-cli`, parses stdout for the transcription. Fast mode uses a 5-second timeout, 2 threads, and prefers the tiny model for wake word detection.

## audio.ts

Audio recording management. The renderer captures audio via Web Audio API (`navigator.mediaDevices.getUserMedia()` + `AudioWorklet` for 16kHz mono PCM) and sends chunks to the main process via IPC.

```typescript
function registerAudioHandlers(getWindow: () => BrowserWindow | null): void
function isRecording(): boolean
```

The main process accumulates PCM chunks, writes WAV on stop, runs whisper transcription, and returns the text. Push-to-talk is driven by Ctrl keydown/keyup events in the renderer.

## call.ts

Hands-free continuous voice conversation loop. The renderer sends audio chunks via IPC while a call is active.

**VAD parameters**: Energy threshold 0.015 RMS, 1.5 seconds of silence to end utterance, minimum 0.5 seconds of speech to process, 30-second safety cap on utterance length.

**Loop**: Listen (capture utterance via VAD) - transcribe (whisper) - infer (Claude CLI) - speak (TTS) - repeat until stopped.

**Key functions**:

| Function | Purpose |
|----------|---------|
| `startCall(systemPrompt, cliSessionId, getWindow)` | Begin hands-free call loop |
| `stopCall()` | End the call |
| `isInCall()` | Whether a call is active |
| `setMuted(muted)` | Mute/unmute mic during call |
| `getCallStatus()` | Current status: `'idle' \| 'listening' \| 'thinking' \| 'speaking'` |
| `getCallCliSessionId()` | CLI session ID (may update during call) |
| `registerCallHandlers(getWindow)` | Register IPC handlers for call control |
| `onCallEvent(event, listener)` | Subscribe to: status, userSaid, agentSaid, error, ended |
| `offCallEvent(event, listener)` | Unsubscribe from call events |

## wake-word.ts

Ambient wake word detection. Listens for the agent's name in background audio.

**Mechanism**: Low-energy RMS threshold (0.005) triggers fast whisper transcription. If the transcription contains the agent's name or configured wake phrases, the wake event fires.

```typescript
function startWakeWordListener(): void
function stopWakeWordListener(): void
function pauseWakeWord(): void
function resumeWakeWord(): void
function registerWakeWordHandlers(getWindow: () => BrowserWindow | null): void
```

## telegram.ts

Telegram Bot API client. Pure HTTP via `fetch()`, no webhooks, no external libraries.

**Key functions**:

| Function | Purpose |
|----------|---------|
| `sendMessage(text, chatId?)` | Send a text message |
| `sendButtons(text, buttons, chatId?)` | Send inline keyboard buttons |
| `sendVoiceNote(oggPath, chatId?)` | Send an OGG Opus voice note |
| `pollCallback(messageId, timeout?)` | Long-poll for button callback |
| `pollReply(timeout?)` | Long-poll for text reply |
| `askConfirm(question, chatId?)` | Yes/No confirmation via buttons |
| `askQuestion(question, chatId?)` | Ask and wait for text reply |
| `registerBotCommands(commands)` | Register slash commands with BotFather API |
| `clearBotCommands()` | Remove all registered commands |

## telegram-daemon.ts

Single-process Telegram poller with sequential agent dispatch.

**Instance locking**: Uses `O_EXLOCK` on macOS for exclusive file lock, with pid-check fallback on other platforms. Ensures only one daemon polls Telegram at a time.

**Dispatch**: Messages are routed via `router.ts` then dispatched to the target agent's inference pipeline. Sequential dispatch (one message at a time) eliminates race conditions.

```typescript
function startDaemon(): Promise<void>
function stopDaemon(): void
function isDaemonRunning(): boolean
function acquireLock(): boolean
function releaseLock(): void
function installLaunchd(): void
function uninstallLaunchd(): void
```

## router.ts

Two-tier message routing for multi-agent dispatch.

**Tier 1 - Explicit match** (instant, no inference):
- `/command` slash commands
- `@agent_name` mentions
- Wake word detection
- `name:` prefix addressing

**Tier 2 - LLM routing agent** (inference-based):
When no explicit match, spawns a lightweight inference call with the agent roster and message content. The routing agent returns the best-matched agent name.

```typescript
function routeMessage(text: string, channel: string): Promise<string>  // returns agent name
function enqueueRoute(text: string, agentName: string): void
function dequeueRoute(): { text: string; agentName: string } | null
```

## server.ts

HTTP API server for programmatic access. Uses raw Node `http` module (not Express).

**Endpoints**:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/chat` | POST | Send message, get response |
| `/chat/stream` | POST | Send message, SSE streaming response |
| `/memory/search` | POST | Hybrid memory search |
| `/memory/threads` | GET | Active conversation threads |
| `/session` | GET | Current session info |

**Auth**: Bearer token from `~/.atrophy/server_token`. Auto-generated on first launch if missing.

```typescript
function startServer(port?: number, host?: string): Promise<void>
function stopServer(): void
```

## cron.ts

launchd plist generation and management for background daemon scheduling.

**Key functions**:

| Function | Purpose |
|----------|---------|
| `listJobs()` | List all jobs for an agent from `jobs.json` |
| `addJob(name, schedule, command)` | Add a new job definition |
| `removeJob(name)` | Remove a job definition |
| `editJobSchedule(name, schedule)` | Update job timing |
| `runJobNow(name)` | Execute a job immediately |
| `installAllJobs()` | Generate plists and `launchctl load` all jobs |
| `uninstallAllJobs()` | `launchctl unload` and remove all plists |
| `toggleCron(agentName, enable)` | Install or uninstall all jobs for an agent |

Generates XML plists written to `~/Library/LaunchAgents/`. Supports both calendar-based scheduling (specific times) and interval-based scheduling (every N seconds).

## usage.ts

Token usage tracking and cross-agent activity reporting.

```typescript
function getUsageSummary(): UsageSummary
function getAllAgentsUsage(): Record<string, UsageSummary>
function getAllActivity(): ActivityRecord[]
function formatTokens(count: number): string
function formatDuration(seconds: number): string
```

Cross-agent queries open each agent's `memory.db` in read-only mode to aggregate usage statistics.

## icon.ts

SVG-based orb rendering for tray and application icons.

**Orb rendering**: Generates an SVG with 8 gradient layers, converted to Electron `NativeImage`. Colors and opacity vary by tray state.

**Tray states**: `'active' | 'muted' | 'idle' | 'away'` - each produces a distinct visual.

```typescript
function renderOrb(state: TrayState, size?: number): NativeImage
function getTrayIcon(state: TrayState): NativeImage
function getAppIcon(): NativeImage
function generateIcons(): void
function clearIconCache(): void
```

## updater.ts

Auto-update via `electron-updater` + GitHub Releases.

```typescript
function initAutoUpdater(mainWindow: BrowserWindow): void
function checkForUpdates(): void
function downloadUpdate(): void
function quitAndInstall(): void
```

Configuration: `autoDownload = false` (user must opt in), `autoInstallOnAppQuit = true`. Checks on launch after 5-second delay. Skipped entirely in dev mode (`ELECTRON_RENDERER_URL` set). Update status forwarded to renderer via IPC events: `updater:available`, `updater:progress`, `updater:downloaded`, `updater:error`.

## install.ts

Login item management using Electron's built-in API.

```typescript
function isLoginItemEnabled(): boolean
function enableLoginItem(): void
function disableLoginItem(): void
function toggleLoginItem(): void
```

Uses `app.setLoginItemSettings()` with the `--app` flag so the companion launches in menu bar mode on login.

## create-agent.ts

Agent scaffolding - creates the full directory structure for a new agent.

```typescript
interface CreateAgentOptions {
  name: string;
  displayName: string;
  description?: string;
  role?: string;
  voiceId?: string;
  // ... additional options
}

function createAgent(opts: CreateAgentOptions): AgentManifest
```

Creates: directories (`data/`, `prompts/`, `avatar/`, `skills/`, `notes/`), `agent.json` manifest, `system_prompt.md`, `soul.md`, `heartbeat.md`, skill stubs, and initialises the SQLite database with schema.

## reindex.ts

Embedding reindexer for backfilling missing vectors.

```typescript
interface ReindexResult {
  processed: number;
  errors: number;
  tables: Record<string, number>;
}

function reindexEmbeddings(
  tables?: string[],
  onProgress?: (current: number, total: number) => void,
): Promise<ReindexResult>
```

Scans configured tables for rows with `NULL` embedding column, computes embeddings in batches, and writes them back. Progress callbacks allow UI updates during long reindex operations.

## review-memory.ts

Memory browser and audit tools for inspecting the agent's database.

**Browse functions** (paginated):

| Function | Purpose |
|----------|---------|
| `browseSessions()` | List sessions with timestamps and summaries |
| `browseTurns()` | List turns within a session |
| `browseObservations()` | List observations with confidence and activation |
| `browseSummaries()` | List session summaries |
| `browseEntities()` | List extracted entities |
| `browseThreads()` | List conversation threads by status |

**Search functions**:

| Function | Purpose |
|----------|---------|
| `searchTurns(query)` | Full-text search across turns |
| `searchObservations(query)` | Full-text search across observations |
| `searchSummaries(query)` | Full-text search across summaries |
| `searchEntities(query)` | Full-text search across entities |

**Audit**:

| Function | Purpose |
|----------|---------|
| `getAuditStats()` | Table row counts, embedding coverage, database size |
| `getContextPreview()` | Preview what `getContextInjection()` would return |

## migrate-env.ts

One-time migration utility for moving settings from `.env` to `config.json`.

```typescript
interface MigrationResult {
  migrated: string[];
  skipped: string[];
  errors: string[];
}

function migrateEnv(): MigrationResult
```

Reads `~/.atrophy/.env`, identifies non-secret settings (excludes API keys, tokens, credentials), and writes them to `config.json` in their typed form. Reports what was migrated, skipped, and any errors encountered.
