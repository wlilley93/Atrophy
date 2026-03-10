# Code Conventions

Style guide for The Atrophied Mind codebase.

## Python Style

- **Python 3.12+** — Uses modern syntax: `list[dict]`, `str | None`, `dict[str, float]`.
- **No type annotations on most functions** — Lightweight style. Annotations appear only where they clarify intent (return types, complex signatures). Parameters are generally untyped.
- **Docstrings** — Brief one-liners. Not Google or numpy style. If the function name is self-explanatory, skip the docstring.
- **Imports** — stdlib, then third-party, then local, separated by blank lines.
- **Constants** — `UPPER_SNAKE_CASE`, defined in `config.py`.
- **Private helpers** — `_underscore` prefix for internal functions and module-level variables.
- **Config access** — Import constants directly from `config.py` (`from config import DB_PATH`). No config objects, no dependency injection.

## Architecture Patterns

- **Agent-aware** — All paths derive from `AGENT_NAME`, loaded from `agents/<name>/`. Config reads the agent manifest at import time. Per-agent isolation means separate databases, state directories, and identity files.
- **Env-var driven** — Every setting has an env var override. The agent manifest can also override voice, heartbeat, display, and Telegram settings. Env vars win over manifest values where both exist.
- **Obsidian optional** — Always check existence before reading Obsidian paths. Provide fallbacks. The system must work without a vault connected.
- **Streaming-first** — Prefer generators and event streams over blocking calls. Inference streams token-by-token; TTS streams audio chunks.
- **Async where it matters** — Background threads for I/O-bound work (embedding writes, TTS synthesis). Not forced everywhere. The main conversation loop is synchronous.
- **Background threads for I/O** — Embedding writes, TTS playback, and other non-blocking I/O use daemon threads. CPU-bound work stays on the main thread.
- **SQLite with WAL mode** — All database connections enable WAL journal mode and foreign keys. One database per agent.
- **Per-agent isolation** — Separate DBs, state dirs, identity files. No shared mutable state between agents.

## File Organization

```
core/               Pure logic, no I/O frameworks
voice/              Audio I/O only (STT, TTS, wake word)
display/            GUI only (PyQt5 window, HTML canvas overlay)
channels/           External communication (Telegram)
mcp/                MCP server (runs as subprocess, exposes memory tools)
scripts/            CLI tools and scheduled jobs
agents/<name>/      Per-agent identity, state, avatar assets
db/                 Schema only (databases live in agent dirs)
docs/               All documentation
```

### Where things go

- Database operations: `core/memory.py` — all SQL lives here, nowhere else.
- Prompt assembly: `core/prompts.py` — builds the system prompt from identity docs and context.
- Behavioral logic: `core/agency.py` — mood detection, silence handling, drift detection. Pure functions, no side effects.
- Inference: `core/inference.py` — Claude CLI integration, streaming, tool handling.
- Context assembly: `core/context.py` — builds the full context window from memory layers.
- Embeddings: `core/embeddings.py` — sentence-transformer model loading and vector operations.
- Vector search: `core/vector_search.py` — hybrid keyword + vector search across memory tables.

## Naming

- **Files** — `lowercase_with_underscores.py`
- **Classes** — `PascalCase` (rare; the codebase is mostly functional)
- **Functions** — `snake_case`
- **Config constants** — `UPPER_SNAKE_CASE`
- **Agent manifest fields** — `snake_case` in JSON (`display_name`, `wake_words`, `elevenlabs_voice_id`)
- **State files** — Dot-prefixed in the agent state dir (`.emotional_state.json`, `.dream_log.txt`)

## Database Conventions

- All SQL lives in `core/memory.py`. No raw SQL in other modules.
- Schema defined in `db/schema.sql`. Migrations handled in `_migrate()` with safe `ALTER TABLE ADD COLUMN` checks.
- Connections use `sqlite3.Row` row factory for dict-like access.
- WAL mode and foreign keys enabled on every connection.
- Async embedding: writes fire-and-forget in daemon threads via `_embed_async()`.

## Error Handling

- Fail silently for non-critical features (Obsidian reads, avatar loading).
- Print warnings for background failures (embedding errors).
- Let critical errors propagate (database initialization, inference failures).
- No custom exception hierarchy. Use built-in exceptions.

## Dependencies

- Keep the dependency surface small. Prefer stdlib where possible.
- Heavy dependencies (PyQt5, sentence-transformers) are optional — features degrade gracefully without them.
- External tools (whisper.cpp, LivePortrait) live in `vendor/` or user home, not bundled.
