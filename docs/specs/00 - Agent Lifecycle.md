# Agent Lifecycle

This specification describes the end-to-end lifecycle of a companion agent session, from startup through shutdown and inter-session autonomous activity.

---

## 1. Startup

Entry point: `main.py`. Three modes: `--cli` (voice+text), `--text` (text-only), `--gui` (PyQt5 window).

### Sequence

1. **Load environment**: `.env` file loaded via `python-dotenv`. Agent name resolved from `--agent` flag or `AGENT` environment variable (default: `xan`).

2. **Load configuration**: `config.py` creates `~/.atrophy/` on first run, reads `~/.atrophy/config.json` for user settings, then loads the agent manifest from `agents/<name>/data/agent.json` (checking user-installed agents in `~/.atrophy/agents/` first, then bundled agents). Runtime state paths resolve to `~/.atrophy/agents/<name>/data/`.

3. **Initialise database**: `memory.init_db()` executes `db/schema.sql` to create tables (idempotent via `IF NOT EXISTS`), then runs migrations for schema evolution on existing databases.

4. **Start session**: `Session.start()` creates a new row in the `sessions` table and looks up the previous CLI session ID from the most recent session that has one. This allows inference to resume the same Claude CLI conversation thread across companion restarts.

5. **Load system prompt**: `context.load_system_prompt()` reads from Obsidian first (`<agent_dir>/skills/system.md`), falling back to the local file (`agents/<name>/prompts/system_prompt.md`), then to a minimal default. The Obsidian-first approach allows the companion to edit its own system prompt via the self-evolution daemon.

6. **Generate opening**: Behaviour depends on whether a CLI session ID exists:
   - **New session** (no prior CLI session): Display the static opening line from `agent.json`.
   - **Resuming session** (has CLI session ID): Send a proactive memory-check prompt through inference. The companion checks threads and recent memory, surfacing anything worth mentioning.
   - **GUI mode**: Generate a dynamic opening via `run_inference_oneshot` with a randomly selected style directive (from 12 options: question, observation, tease, admission, etc.) and time-of-day context.

---

## 2. Turn Cycle

Each user turn follows this pipeline:

### Input

1. **Get input**: Voice (push-to-talk with Ctrl), text (stdin), or dual mode (type or press Enter then hold Ctrl). Voice input is transcribed locally via whisper.cpp.

2. **Classify effort**: If adaptive effort is enabled and base effort is `medium`, `classify_effort()` in `core/thinking.py` analyses the message to determine inference effort level. Short greetings get `low`; complex questions get `high`.

### Context Assembly

3. **Build agency context**: `_agency_context()` in `core/inference.py` assembles a dynamic context block:
   - Time-of-day register (late night: gentler; morning: practical; evening: reflective)
   - Emotional state from `core/inner_life.py` (six dimensions + four trust domains with descriptive labels)
   - User presence status (returned from away, etc.)
   - Session pattern analysis (frequency over last 7 days)
   - Mood shift detection on the current message
   - Validation-seeking detection
   - Compulsive modelling detection
   - Time gap since last session
   - Active thread names (up to 5)
   - Energy matching (message length/tone analysis)
   - Drift detection on recent companion turns (excessive agreeableness)
   - Journal prompting (probabilistic, contextual)
   - Morning digest nudge (5-10am)

4. **Auto-detect emotional signals**: The user's message is scanned for emotional signals. Detected signals update the emotional state and trust dimensions before inference.

### Inference

5. **Stream inference**: Claude CLI invoked as subprocess with `--output-format stream-json`. For new sessions, the system prompt and context are sent via `--system-prompt`. For resumed sessions, context is prepended to the user message via `[Current context: ...]`.

6. **Process events**: Events arrive as newline-delimited JSON. The main loop handles:
   - `TextDelta`: Accumulated in buffer, printed token-by-token.
   - `SentenceReady`: Dispatched to TTS queue (see Streaming Protocol spec).
   - `ToolUse`: Logged to `tool_calls` audit table.
   - `Compacting`: Flags the turn for pre-compaction memory flush.
   - `StreamDone`: Full text and session ID captured.
   - `StreamError`: Error displayed, turn continues.

### Post-Inference

7. **Persist**: CLI session ID saved if changed. Full response written to `turns` table. Embedding computed asynchronously in a background thread.

8. **Memory flush**: If compaction was detected, a silent inference turn fires to flush observations, thread updates, bookmarks, and notes before context is compressed.

9. **Coherence check**: SENTINEL runs periodically (GUI: timer-based; future: turn-count-based). Analyses last 5 companion turns for repetition, flatness, agreement drift, and vocabulary staleness. Fires a silent re-anchoring turn if degraded.

10. **Follow-up**: 15% chance of an unprompted second thought. Delayed 3-6 seconds, uses a follow-up prompt that instructs continuation without repeating.

---

## 3. Mid-Session Behaviour

### Silence Detection

No explicit silence timer in the current implementation. The GUI mode handles this through the event loop; CLI mode blocks on input.

### Unprompted Follow-Up

After each turn, `should_follow_up()` returns `True` with 15% probability. The follow-up uses the existing CLI session and adds a system prompt suffix instructing the companion to continue with a second thought, add a question, or shift register.

### Mood Shift Detection

`detect_mood_shift()` in `core/agency.py` scans user messages for emotional weight indicators. When detected, the session mood is updated to `heavy` and a system note is injected advising the companion to stay present and not reset to neutral.

### Soft Time Limit

At 60 minutes (`SESSION_SOFT_LIMIT_MINS`), the companion delivers a check-in message. The message is spoken via TTS, written to the turn history, and the warning flag is set so it only fires once per session.

---

## 4. Session End

Triggered by `KeyboardInterrupt` or `EOFError` (Ctrl+C or Ctrl+D).

### Sequence

1. **Generate summary**: If the session has 4+ turns, all turn text is sent to `run_inference_oneshot` with a summarisation prompt. The model is instructed to focus on what mattered, not what was said, and to note new threads, mood shifts, and observations.

2. **Write summary**: Summary stored in the `summaries` table with an async embedding. The session row is updated with `ended_at`, summary text, mood, and notable flag.

3. **Save emotional state**: The inner life state (emotions + trust) is written to `~/.atrophy/agents/<name>/data/.emotional_state.json` with the current timestamp.

4. **Update user status**: Presence tracking updated (if applicable).

---

## 5. Between Sessions

Autonomous daemons run on launchd schedules defined in `scripts/agents/<name>/jobs.json`. The companion can view and modify its own schedule via the `manage_schedule` MCP tool.

### Daemon Types

| Daemon | Purpose | Typical Schedule |
|---|---|---|
| **observer** | Reads recent turns, extracts factual observations with confidence scores | Every 15 minutes during active hours |
| **heartbeat** | Evaluates whether to reach out via Telegram based on time since last interaction, active threads, and emotional state | Every 30 minutes during active hours (configurable per agent) |
| **sleep_cycle** | End-of-day processing: decay observation activations, mark stale observations, generate daily reflection note | Once nightly |
| **introspect** | Reviews recent observations, checks which still hold, updates identity snapshot if warranted | Periodic (agent-configured) |
| **evolve** | Self-evolution: reviews conversation history and rewrites system prompt and soul document | Monthly |
| **gift** | Generates a small creative offering (poem, observation, question) and leaves it in Obsidian | Periodic (agent-configured) |

Daemons use `run_inference_oneshot` for inference (no MCP tools, no session persistence) and write results to the database or Obsidian vault.
