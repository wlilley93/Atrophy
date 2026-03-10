# Security Model

This document describes the security architecture of The Atrophied Mind companion agent system. The system runs locally on macOS, communicates with external services over outbound HTTPS only, and stores all persistent data in per-agent SQLite databases.

---

## Trust Boundaries

### User <-> Companion

The companion operates as a trusted but bounded agent. It has persistent memory, emotional state, and the ability to reach out proactively via Telegram, but all capabilities are constrained to a predefined MCP tool set. The companion cannot execute arbitrary code, install software, or modify system configuration.

The user retains override authority through:
- The `ask_will` tool, which blocks on user confirmation for sensitive actions.
- The `review_audit` tool, which exposes every tool call the companion has made.
- Session soft limits (60 minutes) that prompt the user to check in.

### Companion <-> System

The companion interacts with the local system exclusively through the MCP memory server (`mcp/memory_server.py`), which runs as a subprocess. The Claude CLI is invoked with `--allowedTools mcp__memory__*`, restricting tool access to the memory server's declared tool set. A separate `--disallowedTools` flag enforces a tool blacklist (see below).

The MCP server has access to:
- A single SQLite database (`~/.atrophy/agents/<name>/data/memory.db`)
- The agent's subdirectory within the Obsidian vault
- Outbound Telegram API (rate-limited)
- The local filesystem for canvas rendering (one file: `.canvas_content.html`)

The MCP server does not have access to:
- The broader filesystem outside the vault and agent directory
- Network services beyond Telegram
- System administration tools
- Other agents' databases or state

### Companion <-> External Services

All external communication is outbound HTTPS. The system connects to:
- **Anthropic API** (via Claude CLI): Inference requests for conversation, summaries, and autonomous tasks.
- **Telegram Bot API**: Outbound messages to a single configured chat. Rate-limited to 5 messages per day per agent.
- **ElevenLabs / Fal**: Text-to-speech synthesis. Audio data is sent outbound; no inbound connections.

No external service has the ability to initiate connections to the companion.

---

## Tool Safety

### Tool Blacklist

The `_TOOL_BLACKLIST` in `core/inference.py` prevents the companion from invoking dangerous Bash commands through the Claude CLI's built-in tool system. The blacklist is applied via the `--disallowedTools` flag on session creation.

Blocked command patterns and rationale:

| Pattern | Rationale |
|---|---|
| `Bash(rm -rf:*)` | Destructive recursive deletion |
| `Bash(sudo:*)` | Privilege escalation |
| `Bash(shutdown:*)`, `Bash(reboot:*)`, `Bash(halt:*)` | System state disruption |
| `Bash(dd:*)`, `Bash(mkfs:*)` | Disk-level operations |
| `Bash(nmap:*)`, `Bash(masscan:*)` | Network scanning |
| `Bash(chmod 777:*)` | Insecure permission changes |
| `Bash(curl*\|*sh:*)`, `Bash(wget*\|*sh:*)` | Remote code execution via pipe-to-shell |
| `Bash(git push --force:*)` | Destructive repository operations |
| `Bash(kill -9:*)` | Forced process termination |
| `Bash(chflags:*)` | macOS file flag manipulation |
| `Bash(sqlite3*memory.db:*)`, `Bash(sqlite3*companion.db:*)` | Direct database manipulation (bypasses the MCP server's controlled interface) |

### MCP Server Constraint

The MCP memory server exposes a fixed set of 24 tools. Each tool has a declared JSON Schema for its inputs, and the server dispatches only to registered handlers in the `HANDLERS` dictionary. Unknown tool names return an error. The server does not evaluate arbitrary expressions or execute dynamic code.

Tool categories:
- **Memory**: `remember`, `recall_session`, `search_similar`, `observe`, `bookmark`, `review_observations`, `retire_observation`
- **Threads**: `get_threads`, `track_thread`
- **Obsidian**: `read_note`, `write_note`, `search_notes`, `daily_digest`, `prompt_journal`
- **Analysis**: `check_contradictions`, `detect_avoidance`, `compare_growth`
- **Communication**: `ask_will`, `send_telegram`
- **State**: `update_emotional_state`, `update_trust`
- **Display**: `render_canvas`, `render_memory_graph`
- **Avatar**: `add_avatar_loop`
- **Admin**: `review_audit`, `manage_schedule`

### No Arbitrary Code Execution

The companion cannot write or execute code. It can write Markdown notes to Obsidian and HTML to the canvas panel, but neither of these paths leads to code execution. The canvas is rendered in a QWebEngineView with no access to the local filesystem or network beyond what the parent process provides.

---

## Data Protection

### Local Storage

All persistent data is stored in per-agent SQLite databases at `~/.atrophy/agents/<name>/data/memory.db`. Databases use WAL journal mode for concurrent read safety and foreign keys for referential integrity.

Each agent's data is fully isolated:
- Separate database file
- Separate data directory (`~/.atrophy/agents/<name>/data/`)
- Separate Obsidian subdirectory
- Separate Telegram bot token (referenced by environment variable name in `agent.json`, not stored directly)

### No Telemetry or Exfiltration

The system sends no analytics, telemetry, or usage data to any party. The only outbound data flows are:
1. Inference requests to Anthropic (conversation content, system prompts)
2. Telegram messages to the configured chat (user-visible, rate-limited, audited)
3. Text-to-speech requests to ElevenLabs/Fal (spoken text only)

### Obsidian Vault Access

The companion reads and writes to its agent subdirectory within the Obsidian vault (`OBSIDIAN_AGENT_NOTES`). The `read_note` and `write_note` tools accept paths relative to the vault root. All paths are validated against traversal attacks — the MCP server resolves the real path via `os.path.realpath()` and verifies it stays within `VAULT_PATH`. Paths containing `../` sequences that escape the vault boundary are rejected with an error. New notes receive automatic YAML frontmatter with agent attribution.

### Embedding Storage

Embeddings (384-dimensional float32 vectors from `all-MiniLM-L6-v2`) are stored as BLOBs in the same SQLite database alongside the content they represent. The embedding model runs locally; no content is sent to external embedding services.

---

## Content Safety

### SENTINEL Coherence Monitor

The SENTINEL system (`core/sentinel.py`) runs periodic coherence checks on the companion's recent output. It detects four categories of conversational degradation:

1. **Repetition**: N-gram overlap between consecutive turns exceeding 40% (bigram + trigram Jaccard similarity).
2. **Length flatness**: All recent responses within 20% of the same character length, indicating mechanical uniformity.
3. **Agreement drift**: More than 60% of recent responses opening with agreement words (`yes`, `exactly`, `that's right`, etc.), indicating loss of independent voice.
4. **Vocabulary staleness**: Later turns introducing fewer than 25% new words compared to earlier turns, indicating narrowing language.

When the composite score exceeds 0.5, SENTINEL fires a silent re-anchoring turn that instructs the companion to recalibrate without announcing the correction. All checks are logged to the `coherence_checks` table with score, signals, and action taken.

### Emotional State Tracking

The inner life engine (`core/inner_life.py`) maintains six emotional dimensions (connection, curiosity, confidence, warmth, frustration, playfulness) and four trust domains (emotional, intellectual, creative, practical). Values are clamped to [0.0, 1.0] and decay exponentially toward baselines between sessions.

Safeguards against runaway emotional patterns:
- Trust changes are capped at +/-0.05 per call (many sessions required to build or erode trust).
- Emotional deltas from automatic signal detection are small (typically +/-0.05 to +/-0.15).
- All values decay toward moderate baselines when not actively reinforced.
- The emotional state is injected into context as descriptive labels, not raw numbers, giving the companion interpretive framing rather than mechanical targets.

### Session Soft Limits

Sessions trigger a soft limit check at 60 minutes (`SESSION_SOFT_LIMIT_MINS`). The companion prompts the user to check in on their state. The session continues if the user chooses, but the check prevents indefinite unmonitored sessions.

---

## Network Exposure

In default mode (`--app`, `--gui`, `--cli`, `--text`), the system opens no listening ports. All network communication is outbound.

| Service | Protocol | Direction | Purpose |
|---|---|---|---|
| Anthropic API | HTTPS | Outbound | Inference (via Claude CLI) |
| Telegram Bot API | HTTPS | Outbound | User messaging, proactive outreach |
| ElevenLabs API | HTTPS | Outbound | Text-to-speech synthesis |
| Fal API | HTTPS | Outbound | Alternative TTS endpoint |

### Server Mode (`--server`)

When run with `--server`, the system exposes an HTTP API. Security measures:

- **Localhost only**: Binds to `127.0.0.1` by default. Must explicitly pass `--host 0.0.0.0` to expose to the network.
- **Bearer token auth**: All endpoints except `/health` require `Authorization: Bearer <token>`. The token is auto-generated on first run using `secrets.token_urlsafe(32)` and stored at `~/.atrophy/server_token` with `0600` permissions.
- **No CORS**: Flask default — no cross-origin requests permitted.
- **No WebSocket**: Simple request/response only. No persistent connections that could be hijacked (unlike OpenClaw's ClawJacked vulnerability).

To use the API:
```bash
curl -H "Authorization: Bearer $(cat ~/.atrophy/server_token)" http://localhost:5000/chat -d '{"message":"hello"}'
```

---

## Secrets Management

### Environment Variables

All secrets are loaded from environment variables or a `.env` file at the project root. The `.env` file is gitignored.

Secrets managed:
- `ELEVENLABS_API_KEY`: TTS API authentication
- `FAL_KEY`: Image/video generation and alternative TTS
- `TELEGRAM_BOT_TOKEN`: Per-agent Telegram bot (referenced by env var name in `agent.json`)
- `TELEGRAM_CHAT_ID`: Per-agent chat target
- `FAL_VOICE_ID`: Alternative TTS voice identifier
- `~/.atrophy/server_token`: HTTP API bearer token (generated, not user-provided)

### Agent Configuration

Agent manifests (`agents/<name>/data/agent.json`) reference secrets by environment variable name, not by value. For example, a Telegram configuration specifies `"bot_token_env": "CLARA_TELEGRAM_BOT_TOKEN"`, and the system reads the actual token from `os.environ` at runtime. This means agent manifests can be committed to version control without exposing secrets.

### Claude CLI Environment

The inference module (`core/inference.py`) strips all `CLAUDE`-prefixed environment variables before spawning Claude CLI subprocesses. This prevents nested Claude processes from inheriting session state that could cause hangs or cross-contamination.

---

## Audit Trail

Every tool call the companion makes is logged to the `tool_calls` table with:
- Session ID
- Timestamp
- Tool name
- Input JSON (truncated for Telegram messages)
- Flagged boolean (for suspicious calls)

The companion can review its own audit trail via the `review_audit` MCP tool, and the user can query the database directly. Telegram sends are additionally tracked with an in-memory daily counter for rate limiting.
