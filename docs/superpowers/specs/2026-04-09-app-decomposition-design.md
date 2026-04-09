# App.ts Decomposition - Domain-Based Extraction

**Date**: 2026-04-09
**Status**: Design
**Goal**: Decompose the 1,478-line `src/main/app.ts` god object into focused domain modules, reducing it to ~150 lines of pure Electron lifecycle plumbing.

---

## Problem

`app.ts` is the boot orchestrator, runtime manager, and lifecycle owner for the entire Electron main process. It manages:

- ~30 module-level state variables
- 9 interval timers + 1 timeout (journal nudge)
- Window creation and global shortcuts
- Tray menu creation and state updates
- A 650-line `whenReady()` callback covering config init, DB setup, stale session cleanup, MCP discovery, agent wiring, tmux pool init, cron scheduling, Telegram daemon, federation, switchboard polling, Meridian bridge/tunnel, voice agent provisioning, avatar downloads, and auto-updater init
- Shutdown sequencing in `will-quit`
- Crash rate detection and loop breaking

Any change to one subsystem requires navigating the entire file. Timer additions risk forgetting cleanup in `will-quit`. Session state is accessed by multiple subsystems through module-level variables with no encapsulation.

## Approach

Domain-based extraction. Each responsibility gets its own module. Shared state flows through a single `AppContext` object (extending the existing `IpcContext` pattern). No behavioral changes - same boot order, timer intervals, and shutdown sequence.

## New Modules

### 1. `src/main/app-context.ts` (~80 lines)

Single mutable context object passed by reference to all extracted modules. Replaces the 30 module-level variables in `app.ts` and subsumes `IpcContext`.

```typescript
export interface AppContext {
  // Window
  mainWindow: BrowserWindow | null;
  isMenuBarMode: boolean;
  forceQuit: boolean;

  // Session
  currentSession: Session | null;
  systemPrompt: string | null;
  currentAgentName: string | null;

  // Ask-user state
  pendingAskId: string | null;
  pendingAskDestination: string | null;
  pendingAskAgent: string | null;

  // Bundle
  hotBundle: HotBundlePaths | null;
  pendingBundleVersion: string | null;

  // Managers (set during boot)
  timers: TimerManager;
  tray: TrayManager;

  // Helpers
  switchAgent(name: string): Promise<SwitchAgentResult>;
  rebuildTrayMenu(): void;
  updateTrayState(state: TrayState): void;
  isKeepAwakeActive(): boolean;
  toggleKeepAwake(): void;
  resetJournalNudge(): void;
}

export function createAppContext(hotBundle: HotBundlePaths | null): AppContext { ... }
```

**IpcContext migration**: `IpcContext` in `ipc-handlers.ts` becomes a type alias or thin adapter over `AppContext`. The getter/setter proxy pattern used in `initIpcHandlers()` is no longer needed since `AppContext` is the single source of truth passed directly. `registerIpcHandlers` takes `AppContext` instead.

### 2. `src/main/timers.ts` (~350 lines)

Class that owns all 9 interval timers, the journal nudge timeout, and the keep-awake power saver blocker.

```typescript
export class TimerManager {
  private intervals: Map<string, ReturnType<typeof setInterval>> = new Map();
  private timeouts: Map<string, ReturnType<typeof setTimeout>> = new Map();
  private keepAwakeBlockerId: number | null = null;

  // Journal nudge state
  private journalNudgeSent = false;
  private lastUserInputTime = Date.now();

  constructor(private ctx: AppContext) {}

  startAll(): void;
  stopAll(): void;
  resetJournalNudge(): void;
  recordUserInput(): void;

  // Keep-awake
  isKeepAwakeActive(): boolean;
  enableKeepAwake(): void;
  disableKeepAwake(): void;
  toggleKeepAwake(): void;

  // Private timer callbacks
  private pollSentinel(): void;
  private pollQueue(): Promise<void>;
  private pollDeferral(): void;
  private pollAskUser(): void;
  private pollArtefact(): void;
  private pollCanvas(): void;
  private pollStatus(): Promise<void>;
  private pollSessionIdle(): Promise<void>;
  private writeMcpState(): void;
}
```

Timer intervals (from current code):
- `sentinel`: 5 min (300,000ms) - coherence check
- `queue`: 10s - drain all agent queues
- `mcpState`: 5s - write switchboard state for MCP
- `deferral`: 5s - check agent handoff requests
- `askUser`: 3s - check MCP ask_user requests
- `artefact`: 5s - check artefact display file
- `canvas`: 2s - poll canvas content file
- `status`: 60s - macOS idle detection
- `sessionIdle`: 60s - rotate idle sessions after 30min
- `journalNudge`: 5min timeout, 10% probability, once per session

Keep-awake (power save blocker) moves here because it's a timer-adjacent system concern - toggled from tray menu, cleaned up on quit.

### 3. `src/main/tray-manager.ts` (~180 lines)

Class that owns tray creation, menu building, and icon state.

```typescript
export class TrayManager {
  private tray: Tray | null = null;
  private usesBrainIcon = false;

  constructor(private ctx: AppContext) {}

  create(): void;
  rebuildMenu(): void;
  updateState(state: TrayState): void;
  destroy(): void;
}
```

Extracted from: `createTray()` (lines 416-463), `rebuildTrayMenu()` (lines 304-415), `updateTrayState()` (lines 465-478).

The tray menu references agent switching, keep-awake toggle, and quit. These come through `AppContext`.

### 4. `src/main/window-manager.ts` (~160 lines)

Plain module for window creation and global shortcuts.

```typescript
export function createMainWindow(hotBundle: HotBundlePaths | null): BrowserWindow;
export function registerGlobalShortcuts(ctx: AppContext): void;
export function unregisterGlobalShortcuts(): void;
```

Extracted from: `createWindow()` (lines 111-241), global shortcut registration (lines 1263-1337).

Includes CSP header setup, renderer loading (dev URL vs file), lifecycle event logging, and external link handling. The function is already self-contained - this is a clean lift.

### 5. `src/main/boot.ts` (~350 lines)

Sequential boot orchestration. The 650-line `whenReady()` body is reorganized into labeled phases with helper functions.

```typescript
export async function boot(ctx: AppContext): Promise<void>;
```

**Boot phases** (same order as current code):

1. **Config + DB**: `ensureUserData()`, `syncBundledPrompts()`, `initDb()`, close stale sessions for all agents
2. **IPC**: Register IPC handlers, audio handlers, wake word handlers, call handlers, TTS callbacks
3. **Agent resume**: Restore last active agent
4. **Agent wiring**: MCP registry discover, wire all agents through switchboard, init tmux pool, mark boot complete
5. **Crash safety**: Check crash rate, skip services if in crash loop
6. **Services**: Cron scheduler, Telegram daemon, federation, switchboard queue polling, Meridian bridge + Cloudflare tunnel, MCP state writing, daily backup
7. **Voice**: Configure voice agent, pre-provision ElevenLabs
8. **UI** (conditional): Window creation (GUI mode), tray creation (always), global shortcuts, auto-updater, avatar asset download
9. **Background warm-up**: Context prefetch, opening line pre-cache, Kokoro TTS model load

Private helpers within `boot.ts`:
- `closeStaleSessionsForAllAgents()`
- `discoverAndWireAgents(ctx)`
- `initTmuxPool(ctx)`
- `startServices(ctx, crashSafe)`
- `startMeridianBridge()`
- `scheduleBackgroundWarmup()`

### 6. `src/main/app.ts` (after) (~150 lines)

Reduced to Electron lifecycle hooks only:

```typescript
// Hot bundle detection (stays - needs to run at import time)
const hotBundle = detectHotBundle();

// Create shared context
const ctx = createAppContext(hotBundle);

// Single instance lock
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) { app.quit(); }
else { app.on('second-instance', () => { /* focus window */ }); }

// Boot
app.whenReady().then(() => boot(ctx));

// Lifecycle hooks
app.on('before-quit', ...);      // hide instead of quit
app.on('window-all-closed', ...); // no-op
app.on('activate', ...);          // show/create window
app.on('will-quit', () => {
  unregisterGlobalShortcuts();
  ctx.timers.stopAll();
  ctx.tray.destroy();
  // ... shutdown: stop inference, jobs, wake word, daemon, federation, servers
  // ... end current session, close DBs, force exit timeout
});

// Crash safety functions (stay - used by boot and lifecycle)
function readCrashTimestamps(): number[] { ... }
function recordCrash(): void { ... }
function isCrashRateSafe(): boolean { ... }
function gracefulShutdown(signal: string): void { ... }
```

## Migration Path

### IpcContext Transition

Current `IpcContext` (lines 634-660) uses getter/setter proxies over module-level variables. After extraction:

1. `IpcContext` type becomes an alias or subset of `AppContext`
2. `initIpcHandlers()` receives `AppContext` directly - no proxy needed
3. The `registerIpcHandlers(ctx)` call in `ipc-handlers.ts` works unchanged since `AppContext` is a superset of `IpcContext`

This is done in a single step - update `IpcContext` to extend `AppContext`, remove the proxy object.

### Agent Cache

The `getCachedAgents()` / `invalidateAgentCache()` / `getCustomSetup()` helper functions (lines 282-302) move to `boot.ts` or stay in `app.ts` depending on who calls them. If only tray menu uses them, they move to `tray-manager.ts`.

## What Does NOT Change

- Boot order (same sequential phases)
- Timer intervals and callback logic
- Shutdown sequence
- IPC handler registrations
- Any module outside `src/main/app.ts` (except `ipc-handlers.ts` for the context type change)
- The renderer, preload, MCP servers, Python scripts
- Tests (no existing tests for app.ts - new modules will be testable but tests are out of scope)

## Verification

Since this is a pure structural refactor with no behavioral changes:

1. **TypeScript typecheck** - `pnpm typecheck` must pass
2. **Build** - `pnpm build` must produce a working bundle
3. **Manual smoke test** - app launches, agent switching works, tray menu works, timers fire (check logs), shutdown is clean
4. **Existing tests** - `pnpm test` must pass unchanged

## Risk

**Low.** The extraction follows existing patterns (`IpcContext`, domain-split IPC handlers). Each extracted module is a clean lift of contiguous code with no logic changes. The main risk is threading state correctly through `AppContext` - mitigated by TypeScript's type checker catching missing properties.

The one subtle risk is timer callback closures that currently capture module-level variables via closure scope. After extraction, they access the same values through `this.ctx` instead. This is a mechanical transformation but needs care in each callback.
