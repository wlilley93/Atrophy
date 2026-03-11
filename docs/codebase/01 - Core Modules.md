# Core Modules

All core logic lives in `core/`. Each module has a single responsibility.

## memory.py

SQLite data layer. All database operations live here -- no SQL elsewhere in the codebase.

**Connection**: WAL mode, foreign keys enabled. Each function opens and closes its own connection (no connection pooling).

```python
def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection
```

**Key functions**:

| Function | Purpose |
|----------|---------|
| `init_db()` | Create tables from `db/schema.sql`, run migrations |
| `start_session()` | Insert new session row, return `session_id` |
| `write_turn()` | Write a turn, trigger async embedding in background thread |
| `get_context_injection()` | Assemble context from identity snapshot + active threads + recent summaries |
| `get_active_threads()` | Return threads with `status = 'active'` |
| `end_session()` | Close session with optional summary and mood |
| `write_summary()` | Store session summary with async embedding |
| `write_observation()` | Record a bi-temporal observation with confidence |
| `search_memory()` | Hybrid vector+BM25 search (wraps `vector_search.search()`) |
| `extract_entities()` | Regex-based entity extraction (proper nouns, quoted terms) |
| `link_entities()` | Create or strengthen entity relationships |
| `decay_activations()` | Exponential decay on observation activation scores |

**Async embedding**: `_embed_async()` fires a background thread that loads the embedding model, computes the vector, and writes the blob back to the row. This never blocks the conversation pipeline.

**Migrations**: `_migrate()` handles schema evolution on existing databases -- adds columns like `channel`, `embedding`, bi-temporal fields on observations.

## inference.py

Streaming inference via the `claude` CLI subprocess.

**Command construction**: Builds a `claude` command with `--output-format stream-json`, `--include-partial-messages`, MCP config, tool allowlists, and adaptive effort. New sessions use `--session-id`; returning sessions use `--resume`.

**Event types** (dataclasses):

| Event | Fields | Meaning |
|-------|--------|---------|
| `TextDelta` | `text` | Partial text chunk from stream |
| `SentenceReady` | `sentence`, `index` | Complete sentence ready for TTS |
| `ToolUse` | `name`, `tool_id`, `input_json` | Claude is invoking an MCP tool |
| `Compacting` | -- | Context window is being compacted |
| `StreamDone` | `full_text`, `session_id` | Stream finished |
| `StreamError` | `message` | Error during streaming |

**Sentence splitting**: Primary split on sentence boundaries (`.!?` followed by space). Fallback to clause boundaries (`,;--`) when buffer exceeds 120 characters, preventing long sentences from blocking TTS.

**Agency context**: `_agency_context()` builds a dynamic context block injected into every turn. It calls into `agency.py` for behavioral signals, `inner_life.py` for emotional state, `status.py` for presence, and `memory.py` for threads and patterns.

**Tool blacklist**: Dangerous bash commands are explicitly blocked (`rm -rf`, `sudo`, `sqlite3*memory.db`, etc.).

**Oneshot inference**: `run_inference_oneshot()` uses `--print` mode (no streaming, no MCP) for summary generation and other background tasks.

**Memory flush**: `run_memory_flush()` fires a silent inference turn before context compaction, prompting the agent to use memory tools to persist anything important.

## agency.py

Behavioral logic that shapes how the companion responds. All functions are pure/lightweight -- no inference calls, no database writes.

**Time awareness**: `time_of_day_context()` returns register guidance based on the hour (late night = gentler, morning = direct, evening = reflective).

**Session patterns**: `session_pattern_note()` queries the last 7 days of sessions to detect clustering (e.g., "Fifth session this week. All evenings.").

**Silence handling**: `silence_prompt()` returns a gentle nudge after 45+ seconds of silence, escalating at 120+ seconds.

**Unprompted follow-ups**: `should_follow_up()` returns `True` with 15% probability. `followup_prompt()` provides the instruction for a second unprompted thought.

**Mood detection**: `detect_mood_shift()` checks for keywords indicating emotional weight ("hopeless", "numb", "falling apart", etc.) and returns `True` to flag the session as "heavy".

**Validation seeking**: `detect_validation_seeking()` catches patterns like "right?", "don't you think", "am I wrong". Triggers a system note to push back rather than mirror.

**Compulsive modelling**: `detect_compulsive_modelling()` fires when 2+ patterns match ("unifying framework", "meta level", "just one more"). Triggers an interrupt to break the loop.

**Drift detection**: `detect_drift()` checks the last 4 companion turns for excessive agreeableness ("you're right", "absolutely", "that makes sense"). If 3+ are agreeable, injects a course-correction.

**Energy matching**: `energy_note()` calibrates response length -- tight for short messages (<20 chars), deep for long ones (>800 chars).

**Emotional signal detection**: `detect_emotional_signals()` runs every turn and returns a dict of emotion deltas based on keyword patterns (vulnerability, dismissiveness, creativity, playfulness, deflection).

**Journal prompting**: `should_prompt_journal()` returns `True` with 10% probability, triggering a gentle invitation to write.

## context.py

System prompt assembly.

```python
def load_system_prompt() -> str
```

Reads from Obsidian first (`<OBSIDIAN_AGENT_DIR>/skills/system.md`), falls back to `agents/<name>/prompts/system_prompt.md` (from the bundle or `~/.atrophy/agents/<name>/prompts/`), then a minimal default.

```python
def assemble_context(turn_history) -> tuple[str, list[dict]]
```

For SDK fallback and one-shot calls: combines system prompt with memory context injection (last N=3 summaries, identity snapshot, active threads).

## session.py

Session lifecycle management.

```python
class Session:
    session_id: int
    started_at: float
    turn_history: list[dict]
    cli_session_id: str        # Claude CLI session ID for --resume
    mood: str
```

**Methods**:

| Method | Purpose |
|--------|---------|
| `start()` | Create DB session, look up previous CLI session ID |
| `set_cli_session_id()` | Store CLI session ID after first inference |
| `add_turn()` | Write turn to DB, append to local history |
| `update_mood()` | Set session mood (e.g., "heavy") |
| `should_soft_limit()` | Check if session exceeds 60-minute soft limit |
| `end()` | Generate summary via oneshot inference, close in DB |

Summary generation uses `run_inference_oneshot()` with a prompt focused on "what mattered, not what was said".

## status.py

User presence tracking via `.user_status.json`.

- **Active/away states**: Any input sets active. 10 minutes of no input or explicit departure phrases ("going to bed", "brb") set away.
- **macOS idle detection**: `is_mac_idle()` reads `ioreg HIDIdleTime` (nanoseconds since last keyboard/mouse input).
- **Return tracking**: When transitioning from away to active, `returned_from` preserves the previous away reason for one cycle so the companion can acknowledge the return naturally.

Pattern matching for away intent: `detect_away_intent()` uses a compiled regex covering ~30 departure phrases.

## prompts.py

Skill prompt loader with four-tier resolution.

```python
def load_prompt(name: str, fallback: str = "") -> str
```

Checks four directories in order, returning the first non-empty match:

1. **Obsidian vault** — `Agent Workspace/<agent>/skills/{name}.md` (if `OBSIDIAN_AVAILABLE`)
2. **Local skills** — `~/.atrophy/agents/<agent>/skills/{name}.md` (canonical for non-Obsidian users)
3. **User prompts** — `~/.atrophy/agents/<agent>/prompts/{name}.md` (legacy overrides)
4. **Bundle** — `agents/<agent>/prompts/{name}.md` (repo defaults)

Without Obsidian, tier 2 is the canonical location. The agent reads and writes there via MCP note tools. Returns `fallback` if no file is found in any tier.

## embeddings.py

Local embedding engine using `sentence-transformers`.

- **Model**: `all-MiniLM-L6-v2` (384 dimensions)
- **Device**: MPS (Apple Silicon) preferred, CPU fallback
- **Loading**: Lazy singleton -- model loads on first call, cached to `.models/`
- **Normalization**: Embeddings are L2-normalized at generation time

```python
def embed(text: str) -> np.ndarray          # single text -> 384-dim vector
def embed_batch(texts: list[str]) -> list    # batch for efficiency (batch_size=32)
def cosine_similarity(a, b) -> float         # dot product (safe for non-normalized)
def vector_to_blob(vec) -> bytes             # numpy -> SQLite BLOB
def blob_to_vector(blob) -> np.ndarray       # SQLite BLOB -> numpy
```

## vector_search.py

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

**Score merging**: Both result sets are min-max normalized to [0,1], then weighted-summed. Results are de-duplicated via simple MMR (skip results with >80% token overlap with already-selected results).

```python
def search(query, n=5, vector_weight=0.7, tables=None) -> list[dict]
def search_similar(text, n=5) -> list[dict]   # pure vector, no BM25
def reindex(table=None)                        # regenerate all embeddings
```

## inner_life.py

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

```python
def update_emotions(deltas: dict[str, float])
def update_trust(domain: str, delta: float)
def format_for_context() -> str                # for system prompt injection
```

## sentinel.py

Mid-session coherence monitor. Checks the last 5 companion turns for degradation.

**Checks**:

| Check | Threshold | Signal |
|-------|-----------|--------|
| Repetition | >40% n-gram overlap between consecutive turns | Phrasing is repeating |
| Energy flatness | All responses within 20% of same length | Response depth isn't varying |
| Agreement drift | >60% of turns open with agreement words | Losing independent voice |
| Vocabulary staleness | Later turns introduce <25% new words | Language is narrowing |

**Scoring**: Composite score (average of triggered check scores). Degraded if score > 0.5.

**Re-anchoring**: When degraded, fires a silent inference turn with specific course-correction instructions. The turn is consumed silently -- no UI output. Results are logged to the `coherence_checks` table.

```python
def check_coherence(recent_turns) -> dict   # {"degraded": bool, "signals": list, "score": float}
def run_coherence_check(cli_session_id, system) -> str | None
```

## thinking.py

Effort classifier for adaptive inference. Fast heuristic only -- no ML, no API calls, <1ms.

**LOW** (fast responses): Greetings, acknowledgments ("ok", "thanks", "lol"), simple questions ("what time", "how's the weather").

**HIGH** (deep reasoning): Philosophical keywords ("meaning", "purpose", "identity"), vulnerability markers ("I'm scared", "falling apart"), meta-conversation ("are you real", "do you feel"), complex reasoning (2+ markers like "because", "on the other hand").

**MEDIUM**: Default when neither LOW nor HIGH signals are strong enough.

High score accumulates: long messages (+2), multiple questions (+2), philosophical content (+2), vulnerability (+3), meta-conversation (+2). Threshold for HIGH is score >= 3.

## notify.py

macOS native notifications.

```python
def send_notification(title: str, body: str, subtitle: str = "")
```

Uses `osascript` with AppleScript `display notification`. Escapes special characters for AppleScript string literals. Newlines are replaced with spaces.

## agent_manager.py

Multi-agent discovery, switching, state persistence, and session deferral.

**Agent discovery**: `discover_agents()` scans `~/.atrophy/agents/` and `agents/` (bundle), looking for directories containing `data/agent.json`. User-installed agents override bundled ones by name.

**Agent state**: Per-agent `muted` and `enabled` flags are stored in `~/.atrophy/agent_states.json`. Toggling `enabled` automatically installs or uninstalls the agent's launchd cron jobs via `scripts/cron.py`.

```python
def get_agent_state(agent_name: str) -> dict   # {"muted": bool, "enabled": bool}
def set_agent_state(agent_name: str, muted=None, enabled=None)
```

**Agent switching**: `reload_agent_config(agent_name)` sets the `AGENT` env var and reloads the config module. `cycle_agent(direction, current)` returns the next/prev enabled agent name, wrapping around and skipping disabled agents. Used by Cmd+Up/Cmd+Down in the GUI.

**Session deferral**: When one agent defers to another mid-conversation (via the `defer_to_agent` MCP tool), the current agent's session is suspended in memory:

```python
def suspend_agent_session(agent_name, cli_session_id, session)
def resume_agent_session(agent_name) -> dict | None  # pops suspended state
```

This allows the deferred-to agent to handle the question, then the original agent can be resumed.

**Agent roster**: `get_agent_roster(exclude=None)` returns a list of enabled agents with display names and descriptions. Used for injecting agent awareness into the system prompt so agents know who else is available for deferral.
