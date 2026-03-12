# Code Conventions

Style guide for The Atrophied Mind Electron codebase.

## TypeScript Style

- **TypeScript 5.x strict mode** - `strict: true` in `tsconfig.json`. Uses modern syntax: `string | null`, `Record<string, unknown>`, generics, utility types.
- **Functional over class-based** - Export plain functions. Classes are rare and reserved for stateful singletons (`Session`, `Config`). No class hierarchies.
- **Type annotations on all exports** - All exported functions have explicit parameter and return types. Internal helpers may rely on inference where types are obvious.
- **Interfaces over type aliases** - Use `interface` for object shapes (`AgentInfo`, `QueuedMessage`, `InferenceEvent`). Use `type` for unions and mapped types.
- **JSDoc comments** - Brief one-liners on exported functions. If the function name is self-explanatory, skip the comment.
- **Imports** - Node built-ins, then third-party packages, then local modules, separated by blank lines.
- **Constants** - `UPPER_SNAKE_CASE`, defined in `src/main/config.ts` or at module top.
- **Private helpers** - Unexported module-level functions. No underscore prefix convention (TypeScript module scope handles visibility).
- **Config access** - `import { getConfig } from './config'` for the singleton. Access properties as `config.DB_PATH`, `config.AGENT_NAME`. Path constants `BUNDLE_ROOT` and `USER_DATA` are direct imports.

## Architecture Patterns

- **Agent-aware** - All paths derive from `AGENT_NAME`. Config reads the agent manifest at startup from `BUNDLE_ROOT/agents/<name>/` or `USER_DATA/agents/<name>/`. Per-agent isolation means separate databases, data directories, and identity files. Runtime state lives in `~/.atrophy/agents/<name>/`, not in the bundle.
- **Three-tier config** - Resolution order: env vars -> `~/.atrophy/config.json` -> agent manifest -> defaults. Env vars win outright. Agent manifest overrides voice, heartbeat, display, and Telegram settings.
- **Obsidian optional** - Always check existence before reading Obsidian paths. Provide fallbacks. The system must work without a vault connected.
- **Streaming-first** - Prefer event streams over blocking calls. Inference streams token-by-token via `EventEmitter`; TTS streams audio chunks. The renderer receives events over IPC.
- **Main process owns all I/O** - All file system access, SQLite, Claude CLI, TTS synthesis, STT, Telegram, HTTP server, launchd, and notifications live in the Electron main process. The renderer only handles UI and audio capture.
- **IPC as the only bridge** - Renderer communicates with main exclusively through the preload API (`contextBridge.exposeInMainWorld`). No direct Node.js access from renderer.
- **SQLite with WAL mode** - All database connections via `better-sqlite3` enable WAL journal mode and foreign keys. Synchronous API - no callback or promise wrappers needed. One database per agent.
- **Per-agent isolation** - Separate DBs, data dirs, identity files. No shared mutable state between agents.
- **Secure temp files** - Use `fs.mkdtempSync()` for temporary directories with mode `0o700`. Audio temp files are written to owner-only directories.
- **Precompute hot-path data** - Lookup tables, scaled images, and cached computations should be initialized once, not recomputed per frame or per event.

## File Organization

```
src/
  main/                      Electron main process (all logic, I/O, inference)
  preload/                   contextBridge API (typed IPC surface)
  renderer/
    components/              Svelte 5 components (runes mode)
    stores/                  Reactive state (Svelte stores)
    styles/                  Global CSS
mcp/                         Python MCP servers (spawned by Claude CLI)
scripts/                     Python standalone launchd jobs
agents/<name>/               Per-agent identity (prompts/, data/, avatar/)
db/                          Schema only (databases live in agent dirs)
docs/                        All documentation
resources/                   Icons, sounds, assets
vendor/whisper.cpp/          Bundled whisper binary + model
```

### Where things go

- Database operations: `src/main/memory.ts` - all SQL lives here, nowhere else.
- Prompt assembly: `src/main/prompts.ts` - loads identity docs from Obsidian, agent dir, or fallbacks.
- Context assembly: `src/main/context.ts` - builds the system prompt and memory context.
- Behavioral logic: `src/main/agency.ts` - mood detection, silence handling, drift detection. Pure functions, no side effects.
- Inference: `src/main/inference.ts` - Claude CLI integration, streaming JSON parsing, sentence splitting, agency context.
- Embeddings: `src/main/embeddings.ts` - `@xenova/transformers` model loading and vector operations (WASM-based).
- Vector search: `src/main/vector-search.ts` - hybrid keyword + vector search across memory tables.
- IPC surface: `src/preload/index.ts` - defines every channel the renderer can use.
- UI components: `src/renderer/components/*.svelte` - one file per visual component.
- Reactive state: `src/renderer/stores/*.ts` - Svelte stores for session, agents, transcript, audio, settings, emotional state.

## Naming

- **Files** - `kebab-case.ts` (e.g., `agent-manager.ts`, `inner-life.ts`, `vector-search.ts`)
- **Svelte components** - `PascalCase.svelte` (e.g., `Window.svelte`, `InputBar.svelte`, `OrbAvatar.svelte`)
- **Functions** - `camelCase` (e.g., `buildAgencyContext`, `detectMoodShift`, `drainQueue`)
- **Interfaces/Types** - `PascalCase` (e.g., `AgentInfo`, `InferenceEvent`, `QueuedMessage`)
- **Config constants** - `UPPER_SNAKE_CASE` (e.g., `BUNDLE_ROOT`, `USER_DATA`, `TOOL_BLACKLIST`)
- **IPC channels** - `namespace:action` (e.g., `inference:send`, `agent:switch`, `config:get`)
- **Agent manifest fields** - `snake_case` in JSON (`display_name`, `wake_words`, `elevenlabs_voice_id`)
- **State files** - Dot-prefixed in the agent data dir (`.emotional_state.json`, `.message_queue.json`)

## Database Conventions

- All SQL lives in `src/main/memory.ts`. No raw SQL in other modules.
- Schema defined in `db/schema.sql`. Migrations handled with safe `ALTER TABLE ADD COLUMN` checks.
- Connections use `better-sqlite3` with synchronous API. Row results are plain objects.
- WAL mode and foreign keys enabled on every connection.
- Async embedding: writes fire-and-forget via `worker_threads` or `setImmediate`.

## Error Handling

- Fail silently for non-critical features (Obsidian reads, avatar loading, TTS synthesis).
- Log warnings via `console.log` for background failures (embedding errors, cron toggle failures).
- Let critical errors propagate (database initialization, inference subprocess spawn).
- No custom exception hierarchy. Use built-in `Error` and check error codes where needed.

## Dependencies

- Keep the dependency surface small. Prefer Node.js built-ins where possible.
- Heavy dependencies (`better-sqlite3`, `@xenova/transformers`) degrade gracefully when unavailable.
- External tools (whisper.cpp) live in `vendor/` or user home, not npm-installed.
- MCP servers and standalone scripts remain Python - they are spawned as subprocesses, not imported.
- Build system: `electron-vite` + `vite`. Package manager: `pnpm`.
- Native modules (`better-sqlite3`) require `electron-rebuild` after install.
- `@xenova/transformers` is WASM-based and needs no native rebuild.

## Svelte Conventions

- **Svelte 5 with runes** - Use `$state`, `$derived`, `$effect` instead of legacy `let`/`$:` reactivity.
- **No component library** - All UI is custom. No Tailwind, no Shadcn, no Material.
- **Props via `$props()`** - Destructure in the script block.
- **Events via callbacks** - Pass handler functions as props, not custom events.
- **Stores for cross-component state** - Svelte stores in `src/renderer/stores/` for session, agents, transcript, audio, settings.
- **CSS scoped by default** - Component-level `<style>` blocks. Global styles only in `styles/global.css`.
