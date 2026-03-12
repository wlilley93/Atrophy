# Code Conventions

Style guide for the Atrophy Electron codebase. These conventions apply to all TypeScript, Svelte, and CSS files in the project. They reflect the specific architectural choices of an Electron + Svelte 5 desktop application that manages multiple companion agents, each with their own databases, identity files, and behavioral configuration.

## TypeScript Style

The codebase uses TypeScript in strict mode with conventions that favor clarity and simplicity over abstraction. The following rules govern how TypeScript code is written across the main process, preload, and renderer.

- **TypeScript 5.x strict mode** - `strict: true` in `tsconfig.json`. Uses modern syntax: `string | null`, `Record<string, unknown>`, generics, utility types. Strict mode catches null reference errors, implicit any types, and other common bugs at compile time rather than runtime.
- **Functional over class-based** - Export plain functions. Classes are rare and reserved for stateful singletons (`Session`, `Config`) where the state needs to persist across calls and the methods need access to shared internal data. No class hierarchies, no abstract base classes, no inheritance chains.
- **Type annotations on all exports** - All exported functions have explicit parameter and return types so that consumers know exactly what they are getting without reading the implementation. Internal helpers may rely on inference where types are obvious from context.
- **Interfaces over type aliases** - Use `interface` for object shapes (`AgentInfo`, `QueuedMessage`, `InferenceEvent`) because interfaces support declaration merging and produce clearer error messages. Use `type` for unions and mapped types where `interface` syntax cannot express the shape.
- **JSDoc comments** - Brief one-liners on exported functions. If the function name is self-explanatory (e.g., `getConfig()`, `stopInference()`), skip the comment. Comments should explain why, not what.
- **Imports** - Node built-ins first, then third-party packages, then local modules, separated by blank lines. This ordering makes it immediately clear which imports come from which layer.
- **Constants** - `UPPER_SNAKE_CASE`, defined in `src/main/config.ts` or at module top. Constants are always `const` and never mutated after initialization.
- **Private helpers** - Unexported module-level functions. No underscore prefix convention because TypeScript module scope handles visibility - if a function is not exported, it is private to the module.
- **Config access** - `import { getConfig } from './config'` for the singleton. Access properties as `config.DB_PATH`, `config.AGENT_NAME`. Path constants `BUNDLE_ROOT` and `USER_DATA` are direct imports because they never change after initialization.

## Architecture Patterns

These patterns govern the high-level structure of the codebase and the relationships between modules. They exist to maintain consistency across the growing number of source files and to prevent common mistakes that would break agent isolation, security boundaries, or the streaming-first design.

- **Agent-aware** - All paths derive from `AGENT_NAME`. Config reads the agent manifest at startup from `BUNDLE_ROOT/agents/<name>/` or `USER_DATA/agents/<name>/`. Per-agent isolation means separate databases, data directories, and identity files. Runtime state lives in `~/.atrophy/agents/<name>/`, not in the bundle. This isolation is a security property - one agent's data should never leak into another's context.
- **Three-tier config** - Resolution order: env vars -> `~/.atrophy/config.json` -> agent manifest -> defaults. Env vars win outright, allowing any setting to be overridden from the shell. Agent manifest overrides voice, heartbeat, display, and Telegram settings because these define per-agent identity that should not be flattened by user config.
- **Obsidian optional** - Always check existence before reading Obsidian paths. Provide fallbacks for every Obsidian-dependent feature. The system must work without a vault connected because not all users will have Obsidian installed, and the vault may be temporarily unavailable (syncing, locked by another app).
- **Streaming-first** - Prefer event streams over blocking calls. Inference streams token-by-token via `EventEmitter`; TTS streams audio chunks. The renderer receives events over IPC. This architecture enables the companion to begin speaking before the full response is generated, reducing perceived latency.
- **Main process owns all I/O** - All file system access, SQLite, Claude CLI, TTS synthesis, STT, Telegram, HTTP server, launchd, and notifications live in the Electron main process. The renderer only handles UI rendering and audio capture. This is an Electron security best practice - the renderer runs untrusted content (HTML/CSS/JS) and should not have direct access to system resources.
- **IPC as the only bridge** - Renderer communicates with main exclusively through the preload API (`contextBridge.exposeInMainWorld`). No direct Node.js access from renderer. Every new feature that crosses the process boundary requires adding a new IPC channel to the preload API.
- **SQLite with WAL mode** - All database connections via `better-sqlite3` enable WAL journal mode and foreign keys. Synchronous API - no callback or promise wrappers needed. One database per agent. WAL mode allows concurrent reads while a write is in progress, which matters because the MCP server and main process may access the database simultaneously.
- **Per-agent isolation** - Separate DBs, data dirs, identity files. No shared mutable state between agents. When switching agents, the config is reloaded, the database connection is swapped, and the MCP config is regenerated. There is no global state that persists across agent switches.
- **Secure temp files** - Use `fs.mkdtempSync()` for temporary directories with mode `0o700`. Audio temp files are written to owner-only directories to prevent other system users from reading conversation audio.
- **Precompute hot-path data** - Lookup tables, scaled images, and cached computations should be initialized once, not recomputed per frame or per event. The MCP config path and system prompt are cached at the module level for this reason.

## File Organization

The project follows a standard electron-vite layout with clear separation between process types. Each directory has a single responsibility, and cross-directory imports follow strict rules (renderer never imports from main, preload imports only types from main).

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

Each category of logic has a designated home module. Following these conventions prevents duplication and makes it easy to find where a particular feature is implemented.

- **Database operations**: `src/main/memory.ts` - all SQL lives here, nowhere else. Other modules import memory functions rather than writing SQL directly.
- **Prompt assembly**: `src/main/prompts.ts` - loads identity docs from Obsidian, agent dir, or fallbacks. Handles the tiered search across multiple directories.
- **Context assembly**: `src/main/context.ts` - builds the system prompt and memory context by combining prompts, skill files, and the agent roster.
- **Behavioral logic**: `src/main/agency.ts` - mood detection, silence handling, drift detection. Pure functions with no side effects, making them easy to test.
- **Inference**: `src/main/inference.ts` - Claude CLI integration, streaming JSON parsing, sentence splitting, agency context assembly. The most complex module.
- **Embeddings**: `src/main/embeddings.ts` - `@xenova/transformers` model loading and vector operations (WASM-based). Runs in worker threads.
- **Vector search**: `src/main/vector-search.ts` - hybrid keyword + vector search across memory tables. Combines SQLite FTS with cosine similarity.
- **IPC surface**: `src/preload/index.ts` - defines every channel the renderer can use. This is the security boundary between processes.
- **UI components**: `src/renderer/components/*.svelte` - one file per visual component. Components are self-contained with scoped styles.
- **Reactive state**: `src/renderer/stores/*.ts` - Svelte stores for session, agents, transcript, audio, settings, emotional state. These stores are the single source of truth for renderer-side state.

## Naming

Consistent naming across the codebase makes it possible to predict file locations, function names, and interface types without looking them up. The following conventions cover every naming context in the project.

- **Files** - `kebab-case.ts` (e.g., `agent-manager.ts`, `inner-life.ts`, `vector-search.ts`). Hyphens rather than underscores or camelCase.
- **Svelte components** - `PascalCase.svelte` (e.g., `Window.svelte`, `InputBar.svelte`, `OrbAvatar.svelte`). Matches the component tag name used in templates.
- **Functions** - `camelCase` (e.g., `buildAgencyContext`, `detectMoodShift`, `drainQueue`). Verbs for actions, nouns for getters.
- **Interfaces/Types** - `PascalCase` (e.g., `AgentInfo`, `InferenceEvent`, `QueuedMessage`). No `I` prefix.
- **Config constants** - `UPPER_SNAKE_CASE` (e.g., `BUNDLE_ROOT`, `USER_DATA`, `TOOL_BLACKLIST`). These are module-level constants that never change after initialization.
- **IPC channels** - `namespace:action` (e.g., `inference:send`, `agent:switch`, `config:get`). The namespace groups related channels for discoverability.
- **Agent manifest fields** - `snake_case` in JSON (`display_name`, `wake_words`, `elevenlabs_voice_id`). Matches the Python-origin format of the original codebase.
- **State files** - Dot-prefixed in the agent data dir (`.emotional_state.json`, `.message_queue.json`). The dot prefix hides them from casual directory listings since they are internal state, not user-facing data.

## Database Conventions

All database operations follow a consistent pattern designed for safety, performance, and maintainability. The synchronous API of `better-sqlite3` simplifies error handling and avoids callback/promise nesting.

- All SQL lives in `src/main/memory.ts`. No raw SQL in other modules. This centralizes schema knowledge and makes it easy to audit all database operations.
- Schema is defined in `db/schema.sql`. Migrations are handled with safe `ALTER TABLE ADD COLUMN` checks that use `try/catch` to handle the case where the column already exists. This approach is simpler than a migration framework and works well for a single-user desktop app.
- Connections use `better-sqlite3` with synchronous API. Row results are plain objects, not class instances, keeping the data layer lightweight.
- WAL mode and foreign keys are enabled on every connection. WAL mode is set via `PRAGMA journal_mode=WAL` immediately after opening the database.
- Async embedding writes use fire-and-forget via `worker_threads` or `setImmediate` to avoid blocking the main thread during vector computation.

## Error Handling

Error handling follows a severity-based approach. Critical errors that prevent the app from functioning propagate and crash loudly. Non-critical errors are caught and logged without interrupting the user experience. The goal is that the user never sees an error dialog for something that does not actually prevent them from using the app.

- Fail silently for non-critical features (Obsidian reads, avatar loading, TTS synthesis). A missing avatar or failed TTS should not interrupt a conversation.
- Log via the leveled logger (`src/main/logger.ts`), never raw `console.log`. Use `createLogger('tag')` per module and pick the appropriate level: `log.error` for failures that need attention, `log.warn` for fallbacks and degraded paths, `log.info` for operational messages (startup, connected, loaded), `log.debug` for verbose/trace output. The `LOG_LEVEL` env var controls the threshold (defaults to `debug` in dev, `info` in production).
- Let critical errors propagate (database initialization, inference subprocess spawn). If the database cannot be opened or Claude CLI is not found, the app cannot function.
- No custom exception hierarchy. Use built-in `Error` and check error codes where needed. The codebase is not large enough to benefit from custom error classes.

## Dependencies

The project maintains a deliberately small dependency surface. Each dependency was chosen for a specific reason, and alternatives were considered. New dependencies should be justified by a clear need that cannot be met by Node.js built-ins or simple custom code.

- Keep the dependency surface small. Prefer Node.js built-ins (`http` over Express, `crypto` over external libraries) where the built-in API is sufficient.
- Heavy dependencies (`better-sqlite3`, `@xenova/transformers`) degrade gracefully when unavailable. The app should still launch even if the embedding model fails to load.
- External tools (whisper.cpp) live in `vendor/` or user home, not npm-installed. They are native binaries that do not fit the npm dependency model.
- MCP servers and standalone scripts remain Python - they are spawned as subprocesses, not imported. Rewriting them in TypeScript would provide marginal benefit at significant cost.
- Build system: `electron-vite` + `vite`. Package manager: `pnpm`. These choices are project-wide and should not change without strong justification.
- Native modules (`better-sqlite3`) require `electron-rebuild` after install or Electron version changes. This is documented in the Building guide.
- `@xenova/transformers` is WASM-based and needs no native rebuild, making it more portable than native embedding libraries.

## Svelte Conventions

The renderer uses Svelte 5 with runes mode, which replaces Svelte 4's reactive declarations with explicit reactivity primitives. The UI is entirely custom - no component libraries are used because the design language is specific to this application and would not benefit from generic component systems.

- **Svelte 5 with runes** - Use `$state`, `$derived`, `$effect` instead of legacy `let`/`$:` reactivity. Runes make reactivity explicit, which improves readability and prevents accidental reactive dependencies.
- **No component library** - All UI is custom. No Tailwind, no Shadcn, no Material. The dark, transparent-vibrancy design does not map to any existing component library.
- **Props via `$props()`** - Destructure in the script block. This is the Svelte 5 way of receiving props, replacing the Svelte 4 `export let` syntax.
- **Events via callbacks** - Pass handler functions as props, not custom events. This is simpler, more type-safe, and easier to trace through the component tree.
- **Stores for cross-component state** - Svelte stores in `src/renderer/stores/` for session, agents, transcript, audio, settings. Stores are the bridge between IPC events and component reactivity.
- **CSS scoped by default** - Component-level `<style>` blocks scope styles to the component automatically. Global styles that affect the entire app (scrollbars, typography, color variables) live only in `styles/global.css`.
