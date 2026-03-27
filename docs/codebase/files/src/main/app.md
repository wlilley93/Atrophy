# src/main/app.ts - Main Process Implementation

**Dependencies:** Electron, Node.js built-ins, internal modules  
**Purpose:** Complete Electron main process implementation - window management, IPC, lifecycle, agent switching, background services

## Overview

This is the heart of the Electron application. It handles everything from window creation and tray management to IPC handler registration, agent switching, background service orchestration, and lifecycle management. The module is structured as a stateful singleton that runs for the lifetime of the process.

The design follows a clear separation: `bootstrap.ts` handles hot bundle detection and loading, while `app.ts` contains all the actual application logic. This separation enables over-the-air updates without modifying the core application code.

## Module State

The module maintains extensive state at module level. These variables are accessed directly throughout the file and via getter/setter pairs exposed to IPC handlers.

### Window and UI State

```typescript
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let trayUsesBrainIcon = false;
let isMenuBarMode = false;
let _forceQuit = false;
let keepAwakeBlockerId: number | null = null;
```

| Variable | Purpose |
|----------|---------|
| `mainWindow` | Reference to the main BrowserWindow. Null when hidden or closed. |
| `tray` | System tray icon instance. Created in menu bar mode (`--app`). |
| `trayUsesBrainIcon` | Whether the tray uses the hand-crafted brain icon (template image) vs procedural orb. |
| `isMenuBarMode` | True when launched with `--app` flag (menu bar mode vs GUI mode). |
| `_forceQuit` | Set to true when user selects "Quit" from tray menu - allows actual exit instead of hide. |
| `keepAwakeBlockerId` | Power save blocker ID for "Keep Computer Awake" feature. |

### Session and Inference State

```typescript
let currentSession: Session | null = null;
let systemPrompt: string | null = null;
let currentAgentName: string | null = null;
```

| Variable | Purpose |
|----------|---------|
| `currentSession` | Current conversation session instance. Tracks turns, CLI session ID, mood. |
| `systemPrompt` | Loaded system prompt for current agent. Cached to avoid reloading on every inference. |
| `currentAgentName` | Name of the currently active agent. Used for deferral tracking and logging. |

### Timer State

```typescript
let sentinelTimer: ReturnType<typeof setInterval> | null = null;
let queueTimer: ReturnType<typeof setInterval> | null = null;
let deferralTimer: ReturnType<typeof setInterval> | null = null;
let askUserTimer: ReturnType<typeof setInterval> | null = null;
let artefactTimer: ReturnType<typeof setInterval> | null = null;
let statusTimer: ReturnType<typeof setInterval> | null = null;
let journalNudgeTimer: ReturnType<typeof setTimeout> | null = null;
let sessionIdleTimer: ReturnType<typeof setInterval> | null = null;
```

| Timer | Interval | Purpose |
|-------|----------|---------|
| `sentinelTimer` | 5 minutes | Runs coherence checks on active sessions |
| `queueTimer` | 10 seconds | Drains background message queues (cron, Telegram) |
| `deferralTimer` | 2 seconds | Checks for agent deferral requests |
| `askUserTimer` | 1 second | Polls for MCP ask_user requests |
| `artefactTimer` | 5 seconds | Cleans up stale artifact temp files |
| `statusTimer` | 30 seconds | Checks idle status, triggers away detection |
| `journalNudgeTimer` | 5 minutes after input | 10% chance to prompt journaling |
| `sessionIdleTimer` | 30 seconds | Rotates sessions to idle after 30 min inactivity |

### Deferral and Ask-User State

```typescript
let pendingAskId: string | null = null;
let pendingAskDestination: string | null = null;
let pendingBundleVersion: string | null = null;
```

| Variable | Purpose |
|----------|---------|
| `pendingAskId` | ID of current ask_user request being shown in UI |
| `pendingAskDestination` | Target agent for secure_input auto-save |
| `pendingBundleVersion` | Version of downloaded hot bundle awaiting restart |

## Window Creation

The `createWindow()` function creates the main application window with specific styling for the dark, vibrancy-backed appearance.

```typescript
function createWindow(): BrowserWindow {
  const config = getConfig();

  const win = new BrowserWindow({
    width: config.WINDOW_WIDTH,           // default 622
    height: config.WINDOW_HEIGHT,         // default 830
    minWidth: 360, minHeight: 480,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 14, y: 14 },
    vibrancy: 'under-window',
    visualEffectState: 'active',
    backgroundColor: '#00000000',         // transparent
    show: false,
    webPreferences: {
      preload: _hotBundle?.preload ?? path.join(__dirname, '..', 'preload', 'index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  // ...
}
```

### Key Configuration Decisions

**`titleBarStyle: 'hiddenInset'`**: Hides the standard title bar while keeping native traffic light buttons (close, minimize, fullscreen) inset at position (14, 14). This creates the appearance of a borderless window with native controls.

**`vibrancy: 'under-window'`**: Applies macOS vibrancy effect that shows the desktop underneath the window. Combined with transparent background, this creates the distinctive glassy appearance.

**`backgroundColor: '#00000000'`**: Fully transparent background. The window starts invisible and shows only when renderer content is ready.

**`sandbox: true`**: Enables Electron sandbox for the renderer process. This is a security feature that restricts renderer capabilities. Combined with `contextIsolation: true` and `nodeIntegration: false`, the renderer cannot access Node.js APIs directly.

**Preload path resolution**: Uses hot bundle preload if available (`_hotBundle?.preload`), otherwise falls back to frozen bundle path. This enables hot bundle updates to include preload script changes.

### Content Security Policy

A strict CSP is applied to prevent XSS and unauthorized resource loading:

```typescript
win.webContents.session.webRequest.onHeadersReceived((details, callback) => {
  callback({
    responseHeaders: {
      ...details.responseHeaders,
      'Content-Security-Policy': [
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: file:; media-src 'self' file:; font-src 'self'; connect-src 'self' https:; frame-src 'self' blob:; form-action 'none'; base-uri 'self'",
      ],
    },
  });
});
```

| Directive | Value | Purpose |
|-----------|-------|---------|
| `default-src` | `'self'` | Only load resources from same origin |
| `script-src` | `'self'` | No inline scripts, no external scripts |
| `style-src` | `'self' 'unsafe-inline'` | Allow inline styles (needed for Svelte) |
| `img-src` | `'self' data: file:` | Allow local images and data URIs |
| `media-src` | `'self' file:` | Audio/video from local files only |
| `connect-src` | `'self' https:` | HTTPS connections allowed (APIs, TTS, etc.) |
| `frame-src` | `'self' blob:` | Allow blob: frames (for artifact previews) |
| `form-action` | `'none'` | No form submissions |
| `base-uri` | `'self'` | Prevent `<base>` tag hijacking |

### External Link Handling

External links are intercepted and opened in the system browser instead of navigating in-app:

```typescript
// Prevent new window creation for external links
win.webContents.setWindowOpenHandler(({ url }) => {
  if (url.startsWith('https://') || url.startsWith('http://')) {
    shell.openExternal(url);
  }
  return { action: 'deny' };
});

// Prevent in-app navigation to external URLs
win.webContents.on('will-navigate', (event, url) => {
  if (!url.startsWith('file://') && !url.startsWith('devtools://')) {
    event.preventDefault();
    if (url.startsWith('https://') || url.startsWith('http://')) {
      shell.openExternal(url);
    }
  }
});
```

This prevents the app from loading arbitrary web content, which could be a security risk or break the app's assumptions about its environment.

### Close Behavior

Window close hides instead of quitting (menu bar mode behavior):

```typescript
win.on('close', (e) => {
  if (!_forceQuit) {
    e.preventDefault();
    win.hide();
    if (process.platform === 'darwin') app.dock?.hide();
  }
});
```

The `_forceQuit` flag is only set when the user explicitly selects "Quit" from the tray menu. This creates the expected menu bar app behavior where the app runs in the background until explicitly quit.

## Tray Management

The tray system provides menu bar controls for the app when running in `--app` mode.

### Icon Loading

```typescript
function createTray(): void {
  const iconDir = app.isPackaged
    ? path.join(process.resourcesPath, 'icons')
    : path.join(__dirname, '..', '..', 'resources', 'icons');

  // Prefer hand-crafted brain icon (template image)
  const icon2x = path.join(iconDir, 'menubar_brain@2x.png');
  const icon1x = path.join(iconDir, 'menubar_brain.png');
  const brainPath = fs.existsSync(icon2x) ? icon2x : fs.existsSync(icon1x) ? icon1x : '';

  let trayIcon: Electron.NativeImage;
  if (brainPath) {
    trayIcon = nativeImage.createFromPath(brainPath);
    trayIcon.setTemplateImage(true);  // Auto-adapts to light/dark mode
    trayUsesBrainIcon = !trayIcon.isEmpty();
  } else {
    // Procedural orb fallback
    trayIcon = getTrayIcon('active');
  }

  tray = new Tray(trayIcon);
  rebuildTrayMenu();
}
```

**Template image behavior**: The brain icon is marked as a template image with `setTemplateImage(true)`. This tells macOS to automatically adapt the icon to the system appearance (dark in light mode, light in dark mode). The procedural orb fallback does not use template rendering - it has fixed colors.

### Menu Structure

The tray menu is rebuilt dynamically to reflect current state:

```typescript
function rebuildTrayMenu(): void {
  const status = getStatus();
  const agents = getCachedAgents();
  const awake = isKeepAwakeActive();

  const template: Electron.MenuItemConstructorOptions[] = [
    { label: `${statusIcon} ${config.AGENT_DISPLAY_NAME} - ${statusLabel}`, enabled: false },
    { type: 'separator' },
    { label: 'Show Window', accelerator: 'CommandOrControl+Shift+Space', click: ... },
    { label: 'Settings', click: ... },
    { type: 'separator' },
    // Status controls (radio buttons)
    { label: 'Set Online', type: 'radio', checked: status.status === 'active', ... },
    { label: 'Set Away', type: 'radio', checked: status.status === 'away', ... },
    { type: 'separator' },
    // Agent switching submenu
    { label: 'Switch Agent', submenu: agents.map(...) },
    { type: 'separator' },
    { label: 'Keep Computer Awake', type: 'checkbox', checked: awake, ... },
    { type: 'separator' },
    ...(pendingBundleVersion ? [{ label: `Update Available (v${pendingBundleVersion})`, ... }] : []),
    { label: 'Quit', click: () => { _forceQuit = true; app.quit(); } },
  ];

  tray.setContextMenu(Menu.buildFromTemplate(template));
}
```

### Agent Cache

Agent discovery is cached to avoid repeated filesystem scans:

```typescript
let _cachedAgents: ReturnType<typeof discoverAgents> | null = null;

function getCachedAgents(): ReturnType<typeof discoverAgents> {
  if (!_cachedAgents) _cachedAgents = discoverAgents();
  return _cachedAgents;
}

function invalidateAgentCache(): void {
  _cachedAgents = null;
}
```

The cache is invalidated after agent switching or when agents are created/deleted.

## Keep Awake Feature

The app can prevent system sleep (like Amphetamine) via Electron's power save blocker:

```typescript
function enableKeepAwake(): void {
  if (isKeepAwakeActive()) return;
  keepAwakeBlockerId = powerSaveBlocker.start('prevent-display-sleep');
  log.info(`Keep awake enabled (blocker id=${keepAwakeBlockerId})`);
  rebuildTrayMenu();
}

function disableKeepAwake(): void {
  if (keepAwakeBlockerId !== null) {
    try { powerSaveBlocker.stop(keepAwakeBlockerId); } catch { /* already stopped */ }
    log.info(`Keep awake disabled (blocker id=${keepAwakeBlockerId})`);
    keepAwakeBlockerId = null;
  }
  rebuildTrayMenu();
}
```

The blocker uses `'prevent-display-sleep'` which also prevents system sleep on macOS. 

## Agent Switching

Agent switching is a core feature - changing agents changes the entire identity, database, prompts, and configuration:

```typescript
async function switchAgent(name: string): Promise<SwitchAgentResult> {
  // Validate agent name
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) throw new Error('Invalid agent name');
  const knownAgents = discoverAgents();
  if (!knownAgents.some(a => a.name === name)) {
    throw new Error(`Agent "${name}" not found`);
  }

  // Stop current agent's inference
  stopInference(currentAgentName ?? undefined);
  clearAudioQueue();

  // End current session (writes summary to old agent's DB)
  if (currentSession && systemPrompt) {
    try { await currentSession.end(systemPrompt); } catch { /* non-fatal */ }
  }
  currentSession = null;
  systemPrompt = null;

  // Close old agent's DB connection to prevent FD accumulation
  const oldDbPath = getConfig().DB_PATH;
  closeForPath(oldDbPath);

  // Switch config and reinitialise
  getConfig().reloadForAgent(name);
  initDb();
  resetMcpConfig();
  invalidateContextCache();
  currentAgentName = name;
  setLastActiveAgent(name);
  invalidateAgentCache();

  // Prefetch context for new agent
  setImmediate(() => prefetchContext());

  return {
    agentName: config.AGENT_NAME,
    agentDisplayName: config.AGENT_DISPLAY_NAME,
    customSetup: getCustomSetup(name),
  };
}
```

### Critical: Database Connection Cleanup

The `closeForPath(oldDbPath)` call is essential for preventing file descriptor exhaustion:

```typescript
// Close the outgoing agent's DB connection to prevent FD accumulation.
// Each agent has its own memory.db and connect() caches connections by path.
// Without this, repeated agent switches exhaust the 256 FD limit.
const oldDbPath = getConfig().DB_PATH;
closeForPath(oldDbPath);
```

Each agent has a separate SQLite database. The `memory.ts` module caches connections by path. Without explicitly closing the old connection, each agent switch would leak a file descriptor. After ~256 switches, the process would hit the macOS default FD limit and crash.

### MCP Config Reset

```typescript
resetMcpConfig();
```

MCP servers are configured per-agent. When switching agents, the MCP config cache is cleared so the next inference uses the new agent's server configuration.

### Context Prefetch

```typescript
setImmediate(() => prefetchContext());
```

After switching, the new agent's context (recent turns, summaries, threads, emotional state) is prefetched into cache during idle time. This reduces latency for the first inference with the new agent.

## IPC Handler Initialization

IPC handlers are registered with a context object that provides controlled access to module state:

```typescript
function initIpcHandlers(): void {
  const ctx: IpcContext = {
    get mainWindow() { return mainWindow; },
    set mainWindow(v) { mainWindow = v; },
    get currentSession() { return currentSession; },
    set currentSession(v) { currentSession = v; },
    get systemPrompt() { return systemPrompt; },
    set systemPrompt(v) { systemPrompt = v; },
    get currentAgentName() { return currentAgentName; },
    set currentAgentName(v) { currentAgentName = v; },
    get pendingAskId() { return pendingAskId; },
    set pendingAskId(v) { pendingAskId = v; },
    get pendingAskDestination() { return pendingAskDestination; },
    set pendingAskDestination(v) { pendingAskDestination = v; },
    get pendingBundleVersion() { return pendingBundleVersion; },
    set pendingBundleVersion(v) { pendingBundleVersion = v; },
    get hotBundle() { return _hotBundle; },
    get isMenuBarMode() { return isMenuBarMode; },
    switchAgent,
    rebuildTrayMenu,
    updateTrayState,
    isKeepAwakeActive,
    toggleKeepAwake,
    resetJournalNudgeTimer,
  };
  registerIpcHandlers(ctx);
}
```

This pattern avoids exporting all module-level variables while still giving IPC handlers the access they need. The getter/setter pattern ensures handlers read the current value, not a stale closure capture.

## Single Instance Lock

The app enforces single-instance behavior:

```typescript
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}
```

When a second instance is launched (e.g., user double-clicks the app icon while it's already running), the existing window is restored and focused instead of opening a new window.

## App Lifecycle

The `app.whenReady()` handler orchestrates the entire startup sequence:

### Step 1: Parse Arguments and Set Mode

```typescript
app.whenReady().then(() => {
  const args = process.argv.slice(2);
  isMenuBarMode = args.includes('--app');
  const isServerMode = args.includes('--server');

  if (isMenuBarMode || isServerMode) {
    app.dock?.hide();
  } else {
    const appIcon = getAppIcon();
    app.dock?.setIcon(appIcon);
  }
```

Three modes:
- **GUI mode** (default): Full window with dock icon
- **Menu bar mode** (`--app`): Hidden dock, tray icon only
- **Server mode** (`--server`): Headless API mode, no window

### Step 2: Initialize Core Systems

```typescript
ensureUserData();
syncBundledPrompts();
const config = getConfig();
initDb();
```

- `ensureUserData()`: Creates `~/.atrophy/` directory structure
- `syncBundledPrompts()`: Copies bundled prompts to user data (user can override)
- `getConfig()`: Loads configuration singleton
- `initDb()`: Opens/initializes SQLite database for current agent

### Step 3: Clean Up Stale Sessions

```typescript
{
  const defaultAgent = config.AGENT_NAME;
  const allAgents = discoverAgents();
  for (const agent of allAgents) {
    try {
      config.reloadForAgent(agent.name);
      initDb();
      const staleClosed = closeStaleOpenSessions();
      if (staleClosed > 0) {
        log.info(`Closed ${staleClosed} stale open session(s) for agent ${agent.name}`);
      }
    } catch (e) {
      log.warn(`Failed to clean stale sessions for ${agent.name}: ${e}`);
    }
  }
  config.reloadForAgent(defaultAgent);
  initDb();
}
```

Sessions marked as "open" from previous crashes are closed. This runs for ALL agents, not just the default, ensuring no orphaned sessions remain.

### Step 4: Register IPC and Audio Handlers

```typescript
initIpcHandlers();
registerAudioHandlers(() => mainWindow);
registerWakeWordHandlers();
registerCallHandlers(...);
```

### Step 5: TTS Playback Callbacks

```typescript
setPlaybackCallbacks({
  onStarted: (index) => {
    mainWindow?.webContents.send('tts:started', index);
    pauseWakeWord();  // Avoid detecting own speech
  },
  onDone: (index) => {
    mainWindow?.webContents.send('tts:done', index);
  },
  onQueueEmpty: () => {
    mainWindow?.webContents.send('tts:queueEmpty');
    resumeWakeWord();  // Resume listening when done speaking
  },
});
```

When TTS starts playing, wake word detection pauses to avoid the agent detecting its own speech. When the queue empties, wake word detection resumes.

### Step 6: Resume Last Active Agent

```typescript
const lastAgent = getLastActiveAgent();
if (lastAgent && lastAgent !== config.AGENT_NAME) {
  config.reloadForAgent(lastAgent);
  initDb();
  log.info(`resumed agent: ${config.AGENT_NAME}`);
}
```

The app remembers which agent was last used and resumes with that agent, even if it's different from the default.

### Step 7: Switchboard Initialization

```typescript
// 1. Initialize MCP registry
mcpRegistry.discover();
mcpRegistry.registerWithSwitchboard(switchboard);

// 2. Wire all discovered agents through switchboard
const agents = discoverAgents();
for (const agent of agents) {
  wireAgent(agent.name, manifest);
}
markBootComplete();
```

The switchboard is the central routing system for inter-agent communication. All agents are "wired" into the switchboard at boot.

### Step 8: Crash Rate Check

```typescript
const crashSafe = isCrashRateSafe();
if (!crashSafe) {
  log.error('CRASH LOOP DETECTED - skipping cron scheduler and Telegram daemon.');
}
```

If the app has crashed too many times recently, background services are skipped to break crash loops.

### Step 9: Start Background Services

```typescript
if (crashSafe) {
  cronScheduler.start();
  startDaemon();  // Telegram daemon
  startVoiceCallDaemon();
}
```

Cron scheduler and Telegram daemon start only if crash rate is acceptable.

### Step 10: Create Window and Start Timers

```typescript
if (!isServerMode) {
  mainWindow = createWindow();
  if (isMenuBarMode) {
    createTray();
    globalShortcut.register('CommandOrControl+Shift+Space', () => {
      mainWindow?.isVisible() ? mainWindow.hide() : mainWindow.show();
    });
  }
}

// Start periodic timers
sentinelTimer = setInterval(() => { ... }, 5 * 60 * 1000);  // 5 min
queueTimer = setInterval(() => { ... }, 10 * 1000);  // 10 sec
deferralTimer = setInterval(() => { ... }, 2 * 1000);  // 2 sec
askUserTimer = setInterval(() => { ... }, 1000);  // 1 sec
statusTimer = setInterval(() => { ... }, 30 * 1000);  // 30 sec
```

### Step 11: Initialize Auto-Updater

```typescript
initAutoUpdater(mainWindow);
```

Checks for updates after a 5-second delay.

## Journal Nudge Feature

After 5 minutes of silence, there's a 10% chance to prompt the user to journal:

```typescript
let journalNudgeSent = false;
const JOURNAL_NUDGE_DELAY_MS = 5 * 60 * 1000;  // 5 minutes
const JOURNAL_NUDGE_PROBABILITY = 0.10;  // 10%

function resetJournalNudgeTimer(): void {
  lastUserInputTime = Date.now();
  if (journalNudgeTimer) clearTimeout(journalNudgeTimer);
  if (journalNudgeSent) return;

  journalNudgeTimer = setTimeout(() => {
    if (journalNudgeSent) return;
    if (Math.random() > JOURNAL_NUDGE_PROBABILITY) return;
    journalNudgeSent = true;
    mainWindow?.webContents.send('journal:nudge');
  }, JOURNAL_NUDGE_DELAY_MS);
}
```

The nudge only fires once per session (`journalNudgeSent = true`). User input resets the timer.

## Boot Log (Debugging)

A boot log file is written for diagnosing packaged app issues:

```typescript
const BOOT_LOG = path.join(process.env.HOME || '/tmp', '.atrophy', 'logs', 'boot.log');

function bootLog(msg: string): void {
  try {
    const line = `${new Date().toISOString()} ${msg}\n`;
    fs.appendFileSync(BOOT_LOG, line);
  } catch { /* best effort */ }
}
```

Electron suppresses console output when launched from Finder on macOS. The boot log provides a persistent record for debugging startup issues.

## V8 Performance Tuning

The app increases V8's heap limit and enables concurrent GC:

```typescript
app.commandLine.appendSwitch('js-flags', '--max-old-space-size=4096');
app.commandLine.appendSwitch('enable-features', 'V8ConcurrentSparkplug');
```

- **4GB heap limit**: Prevents OOM during large context assembly or embedding operations
- **Concurrent Sparkplug**: Enables parallel compilation for faster JIT

## See Also

- `src/main/bootstrap.ts` - Production entry point with hot bundle detection
- `src/main/index.ts` - Development entry point
- `src/main/ipc-handlers.ts` - IPC handler registration
- `src/main/config.ts` - Configuration system
- `src/main/memory.ts` - SQLite data layer
