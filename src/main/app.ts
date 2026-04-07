/**
 * Electron main process app code.
 * Loaded by bootstrap.ts - either from the frozen asar or a hot bundle.
 * Port of main.py - two modes: menu bar (--app) and GUI (--gui).
 */

import { app, BrowserWindow, Tray, Menu, globalShortcut, nativeImage, ipcMain, powerSaveBlocker, shell } from 'electron';
import * as path from 'path';
import * as fs from 'fs';

// Boot-phase logging uses the main logger (writes to ~/.atrophy/logs/app.log).
// The old separate boot.log is replaced by a 'boot' tag in the unified log.
const bootLogger = createLogger('boot');

// Performance: increase V8 heap limit and enable concurrent GC
app.commandLine.appendSwitch('js-flags', '--max-old-space-size=4096');
app.commandLine.appendSwitch('enable-features', 'V8ConcurrentSparkplug');
import { ensureUserData, getConfig, isValidAgentName, BUNDLE_ROOT, USER_DATA } from './config';
import { initDb, closeAll as closeAllDbs, closeForPath, closeStaleOpenSessions, endSession } from './memory';
import { stopAllInference, stopInference, resetMcpConfig, prefetchContext, invalidateContextCache } from './inference';
import { loadSystemPrompt } from './context';
import { Session } from './session';
import { setActive, setAway, isAway, isMacIdle, getStatus, IDLE_TIMEOUT_SECS } from './status';
import { setPlaybackCallbacks, clearAudioQueue, synthesise, playAudio } from './tts';
import { sendCronNotification } from './notify';
import { cronOutputEmitter } from './channels/telegram/daemon';
import { registerAudioHandlers } from './audio';
import { registerWakeWordHandlers, pauseWakeWord, resumeWakeWord, stopWakeWordListener } from './wake-word';
import { discoverAgents, syncBundledPrompts, cycleAgent, setLastActiveAgent, getLastActiveAgent, checkDeferralRequest, validateDeferralRequest, checkAskRequest, cleanupAskFiles } from './agent-manager';
import { runCoherenceCheck } from './sentinel';
import { drainAllAgentQueues } from './queue';
import { startServer, stopServer, startMeridianServer, stopMeridianServer } from './server';
import { startDaemon, stopDaemonSync, setMainWindowAccessor } from './channels/telegram';
import { startFederation, stopFederation } from './channels/federation';
import { cronScheduler, stopAllJobs } from './channels/cron';
import { mcpRegistry } from './mcp-registry';
import { wireAgent, markBootComplete } from './create-agent';
import { backupAgentData } from './backup';
import { registerCallHandlers } from './call';
import { getAppIcon, getTrayIcon, TrayState } from './icon';
import { initAutoUpdater } from './updater';
import { ensureAvatarAssets, ensureAmbientVideo } from './avatar-downloader';
import { isMirrorSetupComplete } from './jobs/generate-mirror-avatar';
import { getHotBundlePaths } from './bundle-updater';
import type { HotBundlePaths } from './bundle-updater';
import { createLogger } from './logger';
import { switchboard } from './channels/switchboard';
import { registerIpcHandlers, type IpcContext, type SwitchAgentResult } from './ipc-handlers';

const log = createLogger('main');

// ---------------------------------------------------------------------------
// Hot bundle detection
// Bootstrap sets ATROPHY_HOT_BOOT=1 when loading from hot bundle.
// We still call getHotBundlePaths() to get preload/renderer paths.
// ---------------------------------------------------------------------------

const _hotBundle: HotBundlePaths | null = (() => {
  if (process.env.ATROPHY_HOT_BOOT !== '1') return null;
  try {
    return getHotBundlePaths();
  } catch (err) {
    console.error('Hot bundle paths failed, using frozen bundle:', err);
    return null;
  }
})();

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let mainWindow: BrowserWindow | null = null;
let _forceQuit = false;
let tray: Tray | null = null;
let trayUsesBrainIcon = false;
let isMenuBarMode = false;
let currentSession: Session | null = null;
let systemPrompt: string | null = null;
let sentinelTimer: ReturnType<typeof setInterval> | null = null;
let queueTimer: ReturnType<typeof setInterval> | null = null;
let mcpStateTimer: ReturnType<typeof setInterval> | null = null;
let deferralTimer: ReturnType<typeof setInterval> | null = null;
let askUserTimer: ReturnType<typeof setInterval> | null = null;
let pendingAskId: string | null = null; // track which ask is currently shown in UI
let pendingAskDestination: string | null = null; // destination for secure_input auto-save
let pendingAskAgent: string | null = null; // source agent for background ask requests
let artefactTimer: ReturnType<typeof setInterval> | null = null;
let canvasTimer: ReturnType<typeof setInterval> | null = null;
let canvasLastMtime = 0;
let currentAgentName: string | null = null;
let keepAwakeBlockerId: number | null = null;
let statusTimer: ReturnType<typeof setInterval> | null = null;
let pendingBundleVersion: string | null = null;

// Journal nudge - silence-based, once per session
let journalNudgeTimer: ReturnType<typeof setTimeout> | null = null;
let journalNudgeSent = false;
let lastUserInputTime = Date.now();
const JOURNAL_NUDGE_DELAY_MS = 5 * 60 * 1000; // 5 minutes
const JOURNAL_NUDGE_PROBABILITY = 0.10; // 10% chance

// Session idle rotation - gives sessions clean arcs with summaries
let sessionIdleTimer: ReturnType<typeof setInterval> | null = null;
const SESSION_IDLE_THRESHOLD_MS = 30 * 60 * 1000; // 30 minutes

// ---------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------

function createWindow(): BrowserWindow {
  const config = getConfig();

  const winWidth = config.WINDOW_WIDTH || 622;
  const winHeight = config.WINDOW_HEIGHT || 830;

  const win = new BrowserWindow({
    width: winWidth,
    height: winHeight,
    minWidth: 360,
    minHeight: 480,
    maxWidth: 900,
    maxHeight: 1200,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 14, y: 14 },
    vibrancy: 'under-window',
    visualEffectState: 'active',
    backgroundColor: '#00000000',
    show: false,
    fullscreenable: false,
    webPreferences: {
      preload: _hotBundle?.preload ?? path.join(__dirname, '..', 'preload', 'index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      // Dev mode loads renderer from http://localhost which blocks file:// video/image sources.
      // Disable web security in dev so file:// avatar videos load correctly.
      ...(process.env.ELECTRON_RENDERER_URL ? { webSecurity: false } : {}),
    },
  });

  // Lock aspect ratio so the window scales proportionally like a phone
  win.setAspectRatio(winWidth / winHeight);

  // Content Security Policy
  win.webContents.session.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: file:; media-src 'self' file:; font-src 'self' https://fonts.gstatic.com; connect-src 'self' https:; frame-src 'self' blob:; form-action 'none'; base-uri 'self'",
        ],
      },
    });
  });

  // Load renderer
  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl && /^https?:\/\/localhost[:/]/.test(devUrl)) {
    bootLogger.info(`loadURL: ${devUrl}`);
    win.loadURL(devUrl);
  } else {
    const rendererPath = _hotBundle?.renderer ?? path.join(__dirname, '..', 'renderer', 'index.html');
    bootLogger.info(`loadFile: ${rendererPath}`);
    win.loadFile(rendererPath);
  }

  // Log renderer load lifecycle events for diagnostics
  win.webContents.on('did-finish-load', () => {
    bootLogger.info('renderer did-finish-load');
  });
  win.webContents.on('did-fail-load', (_event, errorCode, errorDescription) => {
    bootLogger.error(`renderer did-fail-load: ${errorCode} ${errorDescription}`);
  });
  win.webContents.on('render-process-gone', (_event, details) => {
    bootLogger.error(`renderer process gone: ${details.reason} exitCode=${details.exitCode}`);
  });
  win.webContents.on('unresponsive', () => {
    bootLogger.warn('renderer unresponsive');
  });
  win.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    // Forward renderer console.error to the main log file for crash diagnostics
    if (level >= 2) { // 2 = warning, 3 = error
      const lvl = level >= 3 ? 'error' : 'warn';
      bootLogger.info(`renderer:console[${lvl}] ${message} (${sourceId}:${line})`);
    }
  });

  // Open external links in the system browser instead of in-app
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  // Prevent in-app navigation to external URLs
  win.webContents.on('will-navigate', (event, url) => {
    // Allow same-origin navigation (file:// for the renderer)
    if (!url.startsWith('file://') && !url.startsWith('devtools://')) {
      event.preventDefault();
      if (url.startsWith('https://') || url.startsWith('http://')) {
        shell.openExternal(url);
      }
    }
  });

  win.once('ready-to-show', () => {
    if (!isMenuBarMode) {
      win.show();
    }
  });

  // Close hides the window - app stays in tray. Only tray Quit actually exits.
  win.on('close', (e) => {
    if (!_forceQuit) {
      e.preventDefault();
      win.hide();
      if (process.platform === 'darwin') app.dock?.hide();
    }
  });

  win.on('closed', () => {
    mainWindow = null;
  });

  return win;
}

// ---------------------------------------------------------------------------
// Keep Awake (prevent system sleep, like Amphetamine)
// ---------------------------------------------------------------------------

function isKeepAwakeActive(): boolean {
  return keepAwakeBlockerId !== null && powerSaveBlocker.isStarted(keepAwakeBlockerId);
}

function enableKeepAwake(): void {
  if (isKeepAwakeActive()) return;
  // 'prevent-display-sleep' also prevents system sleep and keeps the display on
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

function toggleKeepAwake(): void {
  if (isKeepAwakeActive()) {
    disableKeepAwake();
  } else {
    enableKeepAwake();
  }
}

// ---------------------------------------------------------------------------
// Tray (menu bar mode)
// ---------------------------------------------------------------------------

// Cache agent list for tray menu - refreshed on agent switch, not every rebuild
let _cachedAgents: ReturnType<typeof discoverAgents> | null = null;
function getCachedAgents(): ReturnType<typeof discoverAgents> {
  if (!_cachedAgents) _cachedAgents = discoverAgents();
  return _cachedAgents;
}
function invalidateAgentCache(): void { _cachedAgents = null; }

/** Check if an agent needs custom setup (e.g. mirror wizard). */
function getCustomSetup(name: string): string | null {
  for (const base of [USER_DATA, BUNDLE_ROOT]) {
    const jsonPath = path.join(base, 'agents', name, 'data', 'agent.json');
    try {
      if (!fs.existsSync(jsonPath)) continue;
      const manifest = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));
      if (manifest.custom_setup && !isMirrorSetupComplete(name)) {
        return manifest.custom_setup;
      }
      break;
    } catch { continue; }
  }
  return null;
}

function rebuildTrayMenu(): void {
  if (!tray) return;

  const awake = isKeepAwakeActive();
  const config = getConfig();
  const status = getStatus();
  const agents = getCachedAgents();

  const statusLabel = status.status === 'active' ? 'Online' : 'Away';
  const statusIcon = status.status === 'active' ? '🟢' : '🟡';

  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: `${statusIcon} ${config.AGENT_DISPLAY_NAME} - ${statusLabel}`,
      enabled: false,
    },
    { type: 'separator' },
    {
      label: 'Show Window',
      accelerator: 'CommandOrControl+Shift+Space',
      click: () => {
        if (!mainWindow) {
          mainWindow = createWindow();
        }
        mainWindow.show();
        mainWindow.focus();
        if (process.platform === 'darwin') app.dock?.show();
      },
    },
    {
      label: 'Settings',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
          mainWindow.webContents.send('app:openSettings');
        }
      },
    },
    { type: 'separator' },
    // Status controls
    {
      label: 'Set Online',
      type: 'radio',
      checked: status.status === 'active',
      click: () => {
        setActive();
        updateTrayState('active');
        mainWindow?.webContents.send('status:changed', 'active');
        rebuildTrayMenu();
      },
    },
    {
      label: 'Set Away',
      type: 'radio',
      checked: status.status === 'away',
      click: () => {
        setAway('manual');
        updateTrayState('away');
        mainWindow?.webContents.send('status:changed', 'away');
        rebuildTrayMenu();
      },
    },
    { type: 'separator' },
    // Agent switching
    {
      label: 'Switch Agent',
      submenu: agents.map((agent) => ({
        label: agent.display_name || agent.name,
        type: 'radio' as const,
        checked: agent.name === config.AGENT_NAME,
        click: async () => {
          if (agent.name === config.AGENT_NAME) return;
          const result = await switchAgent(agent.name);
          if (mainWindow) {
            mainWindow.webContents.send('agent:switched', result);
          }
          rebuildTrayMenu();
        },
      })),
    },
    { type: 'separator' },
    {
      label: 'Keep Computer Awake',
      type: 'checkbox',
      checked: awake,
      click: () => {
        toggleKeepAwake();
        rebuildTrayMenu();
      },
    },
    { type: 'separator' },
    ...(pendingBundleVersion ? [{
      label: `Update Available (v${pendingBundleVersion})`,
      click: () => { app.relaunch(); app.exit(); },
    }] : []),
    {
      label: 'Quit',
      click: () => {
        _forceQuit = true;
        app.quit();
      },
    },
  ];

  const contextMenu = Menu.buildFromTemplate(template);
  tray.setContextMenu(contextMenu);

  // Update tray tooltip
  tray.setToolTip(`Atrophy - ${config.AGENT_DISPLAY_NAME} (${statusLabel})`);
}

function createTray(): void {
  try {
    // Prefer the hand-crafted menu bar brain icon (template image for macOS
    // light/dark auto-adaptation). Fall back to a procedural orb icon.
    const iconDir = app.isPackaged
      ? path.join(process.resourcesPath, 'icons')
      : path.join(__dirname, '..', '..', 'resources', 'icons');

    log.info(`[tray] iconDir=${iconDir} exists=${fs.existsSync(iconDir)}`);

    const icon2x = path.join(iconDir, 'menubar_brain@2x.png');
    const icon1x = path.join(iconDir, 'menubar_brain.png');
    const brainPath = fs.existsSync(icon2x) ? icon2x : fs.existsSync(icon1x) ? icon1x : '';

    log.info(`[tray] brainPath=${brainPath || 'NONE'}`);

    let trayIcon: Electron.NativeImage;
    if (brainPath) {
      trayIcon = nativeImage.createFromPath(brainPath);
      trayIcon.setTemplateImage(true);
      trayUsesBrainIcon = !trayIcon.isEmpty();
      log.info(`[tray] loaded brain icon: ${trayIcon.getSize().width}x${trayIcon.getSize().height} empty=${trayIcon.isEmpty()}`);
    } else {
      // Procedural orb fallback (44px for @2x tray)
      trayIcon = getTrayIcon('active');
      log.info(`[tray] using procedural fallback`);
    }

    tray = new Tray(trayIcon);
    rebuildTrayMenu();

    tray.on('click', () => {
      if (mainWindow) {
        mainWindow.show();
        mainWindow.focus();
      }
    });

    log.info('[tray] created successfully');
  } catch (err) {
    log.error('[tray] failed to create:', err);
  }
}

/**
 * Update the tray icon to reflect the current state (active, muted, idle, away).
 * Only updates if a tray exists and no hand-crafted brain icon is in use
 * (the brain icon is a template image and handles state differently).
 */
export function updateTrayState(state: TrayState): void {
  if (!tray) return;
  // Don't overwrite the hand-crafted brain template icon with the procedural orb -
  // the brain icon auto-adapts to macOS light/dark via template image rendering.
  if (!trayUsesBrainIcon) {
    tray.setImage(getTrayIcon(state));
  }
  // Always rebuild menu to update status dot text
  rebuildTrayMenu();
}

// ---------------------------------------------------------------------------
// Journal nudge - after 5+ minutes of silence, 10% chance, once per session
// ---------------------------------------------------------------------------

function resetJournalNudgeTimer(): void {
  lastUserInputTime = Date.now();
  if (journalNudgeTimer) clearTimeout(journalNudgeTimer);
  if (journalNudgeSent) return;

  journalNudgeTimer = setTimeout(() => {
    if (journalNudgeSent) return;
    if (Math.random() > JOURNAL_NUDGE_PROBABILITY) return;
    journalNudgeSent = true;
    if (mainWindow) {
      mainWindow.webContents.send('journal:nudge');
    }
  }, JOURNAL_NUDGE_DELAY_MS);
}

// ---------------------------------------------------------------------------
// Agent switching (single implementation, used by tray, IPC, and shortcuts)
// ---------------------------------------------------------------------------

let _switchInProgress = false;

async function switchAgent(name: string): Promise<SwitchAgentResult> {
  if (_switchInProgress) throw new Error('Agent switch already in progress');
  _switchInProgress = true;
  try {
    if (!isValidAgentName(name)) throw new Error('Invalid agent name');
    const knownAgents = discoverAgents();
    if (!knownAgents.some(a => a.name === name)) {
      throw new Error(`Agent "${name}" not found`);
    }

    // Stop only the current agent's inference (not background agents like Montgomery)
    stopInference(currentAgentName ?? undefined);
    clearAudioQueue();

    // End current session synchronously (just close it in the DB - fast).
    // Summary generation is deferred to background after the switch completes,
    // so the user isn't blocked waiting for Claude CLI.
    const oldSession = currentSession;
    const oldPrompt = systemPrompt;
    const oldAgentName = currentAgentName;
    if (oldSession?.sessionId != null) {
      // Close the session without summary - just set ended_at
      endSession(oldSession.sessionId, null, oldSession.mood);
      // Generate summary in background after the switch
      if (oldPrompt && oldSession.turnHistory.length >= 4) {
        const sid = oldSession.sessionId;
        const turnHistory = [...oldSession.turnHistory];
        setImmediate(() => {
          _generateDeferredSummary(sid, turnHistory, oldPrompt, oldAgentName || '').catch(() => {});
        });
      }
    }
    currentSession = null;
    systemPrompt = null;

    // Close the outgoing agent's DB - deferred slightly to let the
    // summary write complete if it's fast
    const oldDbPath = getConfig().DB_PATH;
    setTimeout(() => closeForPath(oldDbPath), 5000);

    // Switch config and reinitialise - happens immediately, no waiting
    getConfig().reloadForAgent(name);
    initDb();
    resetMcpConfig();
    invalidateContextCache();
    currentAgentName = name;
    setLastActiveAgent(name);
    invalidateAgentCache();

    // Prefetch context for the new agent during idle
    setImmediate(() => prefetchContext());

    // Re-provision ElevenLabs voice agent for the new agent so the
    // conversational voice matches the switched-to agent.
    if (getConfig().ELEVENLABS_API_KEY) {
      import('./voice-agent').then(({ provisionAgent }) => {
        provisionAgent(name).catch(() => { /* non-critical */ });
      });
    }

    const c = getConfig();
    return {
      agentName: c.AGENT_NAME,
      agentDisplayName: c.AGENT_DISPLAY_NAME,
      customSetup: getCustomSetup(name),
    };
  } finally {
    _switchInProgress = false;
  }
}

/** Generate a session summary in the background after an agent switch.
 *  Briefly swaps config to the old agent to write, then swaps back. */
async function _generateDeferredSummary(
  sessionId: number,
  turnHistory: { role: string; content: string; turnId: number }[],
  systemPrompt: string,
  oldAgentName: string,
): Promise<void> {
  const config = getConfig();
  const currentAgent = config.AGENT_NAME;

  const turnText = turnHistory
    .map((t) => {
      const label = t.role === 'will' ? 'Will' : oldAgentName;
      return `${label}: ${t.content}`;
    })
    .join('\n');

  const summaryPrompt =
    'Summarise this conversation in 2-4 sentences.\n\n' +
    'Capture what actually happened between these two people, not just the topic.\n' +
    'If something shifted - in the relationship, in understanding, in how they talk ' +
    'to each other - name it. Do not use em dashes - only hyphens.\n\n' +
    turnText;

  try {
    const { runInferenceOneshot } = await import('./inference');
    const summary = await runInferenceOneshot(
      [{ role: 'user', content: summaryPrompt }],
      `You are ${oldAgentName}, writing a memory of a conversation. Third person. 2-4 sentences.`,
    );

    if (summary && summary.trim()) {
      // Write directly to the old agent's DB by path - avoids swapping
      // the config singleton which would race with the Telegram daemon.
      const Database = (await import('better-sqlite3')).default;
      const dbPath = path.join(USER_DATA, 'agents', oldAgentName, 'data', 'memory.db');
      const db = new Database(dbPath);
      try {
        db.prepare(
          'UPDATE sessions SET ended_at = CURRENT_TIMESTAMP, summary = ? WHERE id = ?',
        ).run(summary.trim(), sessionId);
        db.prepare(
          'INSERT INTO summaries (session_id, content) VALUES (?, ?)',
        ).run(sessionId, summary.trim());
        log.info(`[deferred-summary] Written for ${oldAgentName} session ${sessionId}`);
      } finally {
        db.close();
      }
    }
  } catch (err) {
    log.warn(`[deferred-summary] Failed for ${oldAgentName}: ${err}`);
  }
}

// ---------------------------------------------------------------------------
// IPC handlers
// ---------------------------------------------------------------------------

function initIpcHandlers(): void {
  // Create context object with getter/setter pairs that bridge to module-level state.
  // This lets ipc-handlers.ts read/write the same variables without them being exported.
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
    get pendingAskAgent() { return pendingAskAgent; },
    set pendingAskAgent(v) { pendingAskAgent = v; },
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

  // Actual quit - called from tray menu or renderer
  ipcMain.handle('app:shutdown', () => {
    _forceQuit = true;
    app.quit();
  });
}

// ---------------------------------------------------------------------------
// Single instance lock - prevent multiple app windows from opening
// ---------------------------------------------------------------------------

const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    // Focus existing window when a second instance is launched
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(() => {
  bootLogger.info('app.whenReady() fired');

  // Parse args
  const args = process.argv.slice(2);
  isMenuBarMode = args.includes('--app');
  const isServerMode = args.includes('--server');

  if (isMenuBarMode || isServerMode) {
    app.dock?.hide();
  } else {
    // Set dock icon - prefers .icns brain icon, falls back to procedural orb
    // macOS Retina docks render up to 1024px; never downsample below 512
    const appIcon = getAppIcon();
    app.dock?.setIcon(appIcon);
  }

  // Initialize
  bootLogger.info('ensureUserData + config + db init');
  ensureUserData();
  syncBundledPrompts();
  const config = getConfig();
  initDb();

  // Close any sessions orphaned by previous crashes or forced quits - for ALL agents
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
    // Restore default agent config after the cleanup loop
    config.reloadForAgent(defaultAgent);
    initDb();
  }

  currentAgentName = config.AGENT_NAME;
  log.info(`v${config.VERSION} | agent: ${config.AGENT_NAME} | db: ${config.DB_PATH}`);

  // Register IPC
  bootLogger.info('registering IPC handlers');
  initIpcHandlers();
  registerAudioHandlers(() => mainWindow);
  registerWakeWordHandlers();
  registerCallHandlers(
    () => mainWindow,
    () => {
      // Lazily initialize session and system prompt (same as inference:send)
      if (!currentSession) {
        currentSession = new Session();
        currentSession.start();
        currentSession.inheritCliSessionId();
      }
      if (!systemPrompt) {
        systemPrompt = loadSystemPrompt();
      }
      return systemPrompt;
    },
    () => currentSession?.cliSessionId || null,
    (id: string) => { if (currentSession) currentSession.setCliSessionId(id); },
  );

  // TTS playback callbacks
  setPlaybackCallbacks({
    onStarted: (index) => {
      mainWindow?.webContents.send('tts:started', index);
      pauseWakeWord();
    },
    onDone: (index) => {
      mainWindow?.webContents.send('tts:done', index);
    },
    onQueueEmpty: () => {
      mainWindow?.webContents.send('tts:queueEmpty');
      resumeWakeWord();
    },
  });

  // Resume last active agent
  const lastAgent = getLastActiveAgent();
  if (lastAgent && lastAgent !== config.AGENT_NAME) {
    config.reloadForAgent(lastAgent);
    initDb();
    currentAgentName = config.AGENT_NAME;
    log.info(`resumed agent: ${config.AGENT_NAME}`);
  }

  // Prefetch context data during startup idle time
  setImmediate(() => prefetchContext());

  // Pre-cache opening lines for all agents in background.
  // Runs after a 10s delay to let boot settle, then generates openings
  // sequentially for any agent that doesn't have a valid cached one.
  setTimeout(() => {
    import('./opening').then(({ precacheAllOpenings }) => {
      precacheAllOpenings();
    }).catch(() => { /* non-fatal */ });
  }, 10_000);

  // ── Switchboard v2 boot sequence ──
  // 1. Initialize MCP registry - discover available servers
  try {
    mcpRegistry.discover();
    mcpRegistry.registerWithSwitchboard(switchboard);
    log.info(`MCP registry: ${mcpRegistry.getRegistry().length} server(s) discovered`);
  } catch (e) {
    log.warn(`MCP registry init failed (non-fatal): ${e}`);
  }

  // 2. Wire all discovered agents through switchboard
  {
    const agents = discoverAgents();
    for (const agent of agents) {
      try {
        const manifestPath = path.join(USER_DATA, 'agents', agent.name, 'data', 'agent.json');
        if (fs.existsSync(manifestPath)) {
          const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
          wireAgent(agent.name, manifest);
        }
      } catch (e) {
        log.warn(`Failed to wire agent "${agent.name}": ${e}`);
      }
    }
    log.info(`Switchboard: ${agents.length} agent(s) wired`);
    markBootComplete();
  }

  // 3. Crash rate check - if too many recent crashes, skip cron and daemon
  // to break crash loops. The subsystems can be re-enabled from the UI.
  const crashSafe = isCrashRateSafe();
  bootLogger.info(`crashSafe=${crashSafe}`);
  if (!crashSafe) {
    log.error('CRASH LOOP DETECTED - skipping cron scheduler and Telegram daemon. Fix the issue, then restart.');
  }

  // 4. Start cron scheduler (in-process, replaces launchd for job timing)
  if (crashSafe) {
    try {
      cronScheduler.start();
      cronScheduler.registerWithSwitchboard();
      const schedule = cronScheduler.getSchedule();
      log.info(`Cron scheduler: ${schedule.length} job(s) scheduled`);
    } catch (e) {
      log.warn(`Cron scheduler start failed (non-fatal): ${e}`);
    }

    // Listen for dispatched cron output - show notification with Play button
    cronOutputEmitter.on('output', async (data: { agentName: string; agentDisplayName: string; jobName: string; text: string }) => {
      if (isAway()) return;

      const jobLabel = data.jobName.charAt(0).toUpperCase() + data.jobName.slice(1);
      const played = await sendCronNotification(data.agentDisplayName, jobLabel, data.text);

      if (played) {
        log.info(`[cron-notify] Playing TTS for ${data.agentName}.${data.jobName}`);
        try {
          const cfg = getConfig();
          const prevAgent = cfg.AGENT_NAME;
          if (cfg.AGENT_NAME !== data.agentName) {
            cfg.reloadForAgent(data.agentName);
          }

          const audioPath = await synthesise(data.text);
          if (audioPath) {
            await playAudio(audioPath);
          }

          if (cfg.AGENT_NAME !== prevAgent) {
            cfg.reloadForAgent(prevAgent);
          }
        } catch (err) {
          log.error(`[cron-notify] TTS failed: ${err}`);
        }
      }
    });
  }

  // 4b. Reconcile launchd jobs - ensures scheduled jobs run even when the
  // app isn't open (e.g. 3am sleep_cycle, 7am morning_brief). Non-blocking.
  try {
    const { execFile } = require('child_process');
    const reconcileScript = path.join(BUNDLE_ROOT, 'scripts', 'reconcile_jobs.py');
    if (fs.existsSync(reconcileScript)) {
      execFile(
        'python3',
        [reconcileScript, '--quiet'],
        {
          cwd: BUNDLE_ROOT,
          env: { ...process.env, PYTHONPATH: BUNDLE_ROOT },
          timeout: 15000,
        },
        (err: Error | null, stdout: string, stderr: string) => {
          if (err) {
            log.debug(`Job reconciler: ${err.message}`);
          } else if (stdout.trim()) {
            log.info(`Job reconciler:\n${stdout.trim()}`);
          }
        },
      );
    }
  } catch (e) {
    log.debug(`Job reconciler failed (non-fatal): ${e}`);
  }

  // 5. Auto-start Telegram daemon. It discovers all agents with telegram
  // credentials and launches a poller per agent.
  if (crashSafe) {
    bootLogger.info('calling startDaemon()');
    const started = startDaemon();
    bootLogger.info(`startDaemon returned ${started}`);
    if (started) {
      log.info('Telegram daemon auto-started');
    } else {
      log.debug('Telegram daemon not started (no agents with credentials, or lock held)');
    }
  }

  // Give telegram daemon access to mainWindow for desktop delivery
  setMainWindowAccessor(() => mainWindow);

  // Start federation pollers
  startFederation().catch((e) => log.error(`Federation start failed: ${e}`));

  // 5. Start switchboard MCP queue polling - processes envelopes from
  // agent MCP tools (Python subprocess writes, TypeScript reads).
  switchboard.startQueuePolling();

  // 5b. Register meridian:web as a switchboard address for the web interface.
  // This is a send-only channel - the web interface sends questions via the
  // /meridian/chat HTTP endpoint, not via switchboard routing.
  if (!switchboard.hasHandler('meridian:web')) {
    switchboard.register('meridian:web', async () => {
      log.debug('meridian:web received envelope (send-only channel, ignored)');
    }, {
      type: 'channel',
      description: 'Meridian Eye web interface',
      capabilities: ['chat', 'query'],
    });
  }

  // 5c. Start Meridian bridge - HTTP server + Cloudflare Tunnel.
  // The HTTP server handles /meridian/chat on port 3847. The tunnel connects
  // bridge.atrophy.app to this port, allowing the Meridian Eye website to
  // route inference requests through the switchboard.
  const tunnelConfigPath = path.join(USER_DATA, 'services', 'cloudflared', 'config.yml');
  if (fs.existsSync(tunnelConfigPath)) {
    // Start the bridge HTTP server first so the tunnel has something to connect to
    startMeridianServer(3847, '127.0.0.1');

    try {
      const { execFileSync, spawn: spawnTunnel } = require('child_process');
      // Verify cloudflared is installed before attempting to spawn
      try { execFileSync('which', ['cloudflared'], { stdio: 'ignore' }); } catch {
        log.info('cloudflared not installed - skipping Meridian tunnel');
        throw new Error('cloudflared not found');
      }
      const tunnelProc = spawnTunnel('cloudflared', ['tunnel', 'run', '--config', tunnelConfigPath], {
        stdio: 'ignore',
        detached: true,
      });
      tunnelProc.unref();
      log.info('Cloudflare Tunnel started for Meridian bridge');
    } catch (e) {
      if (String(e) !== 'Error: cloudflared not found') {
        log.warn(`Failed to start Cloudflare Tunnel (non-fatal): ${e}`);
      }
    }
  }

  // 6. Periodically write switchboard state for MCP servers to read.
  mcpStateTimer = setInterval(() => switchboard.writeStateForMCP(), 5000);

  // 7. Daily agent backup - snapshot manifests, prompts, and org configs.
  // Keeps last 7 days. Memory.db is excluded (too large, has its own WAL).
  backupAgentData();

  // Configure voice agent window reference
  import('./voice-agent').then(({ configureVoiceAgent }) => {
    configureVoiceAgent({
      getWindow: () => mainWindow,
      setCliSessionId: (id: string) => { if (currentSession) currentSession.setCliSessionId(id); },
    });
  });

  // Pre-provision ElevenLabs agent (non-blocking, no cost until WebSocket connects)
  if (config.ELEVENLABS_API_KEY) {
    import('./voice-agent').then(({ provisionAgent }) => {
      provisionAgent(config.AGENT_NAME).catch(() => { /* non-critical */ });
    });
  }

  // Sentinel timer - coherence check every 5 minutes
  sentinelTimer = setInterval(() => {
    if (currentSession?.cliSessionId && systemPrompt) {
      runCoherenceCheck(currentSession.cliSessionId, systemPrompt).then((newId) => {
        if (newId && currentSession) {
          currentSession.setCliSessionId(newId);
        }
      }).catch((err) => { log.debug(`sentinel coherence check failed: ${err}`); });
    }
  }, 5 * 60 * 1000);

  // Queue poller - drain ALL agents' queues (not just the active one)
  queueTimer = setInterval(() => {
    (async () => {
      const allMessages = await drainAllAgentQueues();
      for (const [, messages] of Object.entries(allMessages)) {
        for (const msg of messages) {
          if (mainWindow) {
            mainWindow.webContents.send('queue:message', msg);
          }
        }
      }
    })().catch(err => log.error('queue poll error:', err));
  }, 10_000);

  // Deferral watcher - check for agent handoff requests every 5s
  deferralTimer = setInterval(() => {
    if (!mainWindow || !currentAgentName) return;
    const request = checkDeferralRequest();
    if (!request) return;

    // Validate against anti-loop protection
    if (!validateDeferralRequest(request.target, currentAgentName)) {
      return;
    }

    // Notify renderer to start deferral transition
    mainWindow.webContents.send('deferral:request', {
      target: request.target,
      context: request.context,
      user_question: request.user_question,
    });
  }, 5_000);

  // Status timer - check macOS idle state every 60s, set away if idle > 10min
  statusTimer = setInterval(async () => {
    const wasAway = isAway();
    if (await isMacIdle(IDLE_TIMEOUT_SECS)) {
      if (!wasAway) {
        setAway('idle');
        log.info('User idle - setting away');
        updateTrayState('away');
        mainWindow?.webContents.send('status:changed', 'away');
      }
    } else {
      if (wasAway) {
        setActive();
        log.info('User active - setting online');
        updateTrayState('active');
        mainWindow?.webContents.send('status:changed', 'active');
      }
    }
  }, 60_000);

  // Ask-user watcher - check for MCP ask_user requests every 3s
  cleanupAskFiles();
  askUserTimer = setInterval(() => {
    if (!mainWindow) return;
    if (pendingAskId) return; // already showing a dialog
    const request = checkAskRequest();
    if (!request) return;

    pendingAskId = request.request_id;
    pendingAskDestination = request.destination || null;
    pendingAskAgent = (request as any)._agent || null;
    mainWindow.webContents.send('ask:request', {
      question: request.question,
      action_type: request.action_type,
      request_id: request.request_id,
      input_type: request.input_type,
      label: request.label,
      destination: request.destination,
    });
  }, 3_000);

  // Artefact display watcher - check for MCP create_artefact output every 5s
  artefactTimer = setInterval(() => {
    if (!mainWindow) return;
    const config = getConfig();
    const displayFile = config.ARTEFACT_DISPLAY_FILE;
    if (!displayFile || !fs.existsSync(displayFile)) return;

    try {
      const raw = fs.readFileSync(displayFile, 'utf-8');
      const data = JSON.parse(raw) as {
        status?: string;
        type?: string;
        name?: string;
        path?: string;
        file?: string;
      };

      // Loading state - just notify renderer
      if (data.status === 'generating') {
        mainWindow.webContents.send('artefact:loading', { name: data.name, type: data.type });
        return; // don't delete - MCP will overwrite when done
      }

      // Final artefact ready
      fs.unlinkSync(displayFile);

      const artefactType = data.type || 'html';
      let content = '';
      let src = '';

      if (data.file) {
        // Validate file path is within the agent's artefacts directory
        const c = getConfig();
        const artefactsBase = path.resolve(path.join(USER_DATA, 'agents', c.AGENT_NAME, 'artefacts'));
        let resolvedFile: string;
        try {
          resolvedFile = fs.realpathSync(path.resolve(data.file));
        } catch {
          resolvedFile = ''; // path doesn't exist
        }
        if (!resolvedFile || (!resolvedFile.startsWith(artefactsBase + path.sep) && resolvedFile !== artefactsBase)) {
          log.warn(`Artefact watcher blocked path traversal: ${data.file}`);
          return;
        }

        if (artefactType === 'html') {
          try {
            content = fs.readFileSync(resolvedFile, 'utf-8');
          } catch { /* file missing */ }
        } else if (artefactType === 'image' || artefactType === 'video') {
          src = `file://${resolvedFile}`;
        }
      }

      mainWindow.webContents.send('artefact:updated', {
        type: artefactType,
        content,
        src,
        title: data.name || '',
      });
    } catch {
      // Malformed file - remove it
      try { fs.unlinkSync(displayFile); } catch { /* already gone */ }
    }
  }, 5_000);

  // Canvas content watcher - polls CANVAS_CONTENT_FILE for changes and emits
  // canvas:updated with a file:// URL so Canvas.svelte can display it.
  canvasTimer = setInterval(() => {
    if (!mainWindow) return;
    const config = getConfig();
    const canvasFile = config.CANVAS_CONTENT_FILE;
    if (!canvasFile || !fs.existsSync(canvasFile)) return;

    try {
      const stat = fs.statSync(canvasFile);
      const mtime = stat.mtimeMs;
      if (mtime <= canvasLastMtime) return; // unchanged
      canvasLastMtime = mtime;

      const fileUrl = `file://${canvasFile}`;
      mainWindow.webContents.send('canvas:updated', fileUrl);
    } catch { /* file gone mid-read */ }
  }, 2_000);

  // Session idle rotation - close and summarise desktop sessions after 30 min
  // of inactivity, giving them clean arcs (start, summary, end) rather than
  // accumulating turns indefinitely until shutdown.
  sessionIdleTimer = setInterval(() => {
    (async () => {
      if (!currentSession || currentSession.sessionId === null) return;
      if (currentSession.turnHistory.length === 0) return;

      // Use the session's own activity timestamp (updated on every turn from
      // any channel - GUI, Telegram, cron) rather than GUI-only lastUserInputTime.
      const lastActivity = currentSession.lastActivityAt ?? lastUserInputTime;
      const gap = Date.now() - lastActivity;
      if (gap < SESSION_IDLE_THRESHOLD_MS) return;

      const oldSession = currentSession;
      const sys = systemPrompt || loadSystemPrompt();
      try {
        await oldSession.end(sys);
        log.info(`rotated idle session (gap: ${Math.round(gap / 60000)}m, turns: ${oldSession.turnHistory.length})`);
      } catch (e) {
        log.error(`failed to end idle session: ${e}`);
      }
      // Only null if no new session was created during the async end()
      if (currentSession === oldSession) currentSession = null;
    })().catch(err => log.error('session idle rotation error:', err));
  }, 60_000); // check every minute

  // Server mode - no window
  if (isServerMode) {
    const portIdx = args.indexOf('--port');
    const port = portIdx !== -1 ? parseInt(args[portIdx + 1], 10) || 5000 : 5000;
    startServer(port);
    return;
  }

  // Register global shortcut for all modes (Cmd+Shift+Space toggles window)
  globalShortcut.register('CommandOrControl+Shift+Space', () => {
    if (!mainWindow) {
      mainWindow = createWindow();
      mainWindow.show();
      mainWindow.focus();
      if (process.platform === 'darwin') app.dock?.show();
    } else if (mainWindow.isVisible()) {
      mainWindow.hide();
      if (process.platform === 'darwin') app.dock?.hide();
    } else {
      mainWindow.show();
      mainWindow.focus();
      if (process.platform === 'darwin') app.dock?.show();
    }
  });

  // Menu bar mode - tray only, no window on launch.
  // Window created on demand via tray "Show" or global shortcut.
  if (isMenuBarMode) {
    createTray();
    return;
  }

  // GUI mode - create window immediately
  bootLogger.info('creating main window');
  mainWindow = createWindow();
  bootLogger.info('main window created, loading renderer');

  // Start journal nudge timer (silence-based, once per session)
  resetJournalNudgeTimer();

  // Initialise auto-updater
  if (mainWindow) {
    initAutoUpdater(mainWindow);
  }

  // Background bundle update check (downloads for next boot, non-blocking)
  if (_hotBundle) {
    log.info(`running on hot bundle v${_hotBundle.version}`);
  }
  // Bundle update check is now driven by the renderer during the boot update
  // check phase (via bundle:checkNow IPC). If an update is found, the renderer
  // triggers a restart automatically. No background check needed here.

  // Download avatar assets and ambient video on first launch (non-blocking)
  Promise.all([
    ensureAvatarAssets(config.AGENT_NAME, mainWindow),
    ensureAmbientVideo(mainWindow),
  ]).catch(() => {
    /* non-critical */
  });

  // Always create tray icon (brain in macOS menu bar)
  createTray();

  // Agent cycling via global shortcuts (switchAgent has its own mutex)
  async function doCycleAgent(direction: 1 | -1): Promise<void> {
    const cfg = getConfig();
    const target = cycleAgent(direction, cfg.AGENT_NAME);
    if (!target || target === cfg.AGENT_NAME) return;

    try {
      const result = await switchAgent(target);
      mainWindow?.webContents.send('agent:switched', result);
      rebuildTrayMenu();
    } catch {
      // switchAgent throws if already in progress - silently ignore for cycling
    }
  }

  // Cmd+Shift+] / [ - cycle agents
  // NOTE: Shift+Up/Down were removed - they are standard text selection
  // shortcuts and globalShortcut intercepts them system-wide in all apps.
  globalShortcut.register('CommandOrControl+Shift+]', () => { doCycleAgent(1); });
  globalShortcut.register('CommandOrControl+Shift+[', () => { doCycleAgent(-1); });
});

// Cmd+Q hides the window instead of quitting. Only tray Quit sets _forceQuit.
app.on('before-quit', (e) => {
  if (!_forceQuit) {
    e.preventDefault();
    if (mainWindow) {
      mainWindow.hide();
      if (process.platform === 'darwin') app.dock?.hide();
    }
  }
});

app.on('window-all-closed', () => {
  // Never quit on window close - app lives in tray
});

app.on('activate', () => {
  if (mainWindow === null) {
    mainWindow = createWindow();
  } else {
    mainWindow.show();
  }
  if (process.platform === 'darwin') app.dock?.show();
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (sentinelTimer) clearInterval(sentinelTimer);
  if (queueTimer) clearInterval(queueTimer);
  if (mcpStateTimer) clearInterval(mcpStateTimer);
  if (deferralTimer) clearInterval(deferralTimer);
  if (askUserTimer) clearInterval(askUserTimer);
  if (artefactTimer) clearInterval(artefactTimer);
  if (canvasTimer) clearInterval(canvasTimer);
  if (statusTimer) clearInterval(statusTimer);
  if (sessionIdleTimer) clearInterval(sessionIdleTimer);
  if (journalNudgeTimer) clearTimeout(journalNudgeTimer);
  stopAllInference();
  stopAllJobs();
  stopWakeWordListener(() => mainWindow);
  disableKeepAwake();
  stopDaemonSync();
  stopFederation();
  stopServer();
  stopMeridianServer();

  // End the current desktop session synchronously (summary generation is
  // async and won't complete during shutdown - just close it in the DB
  // so ended_at is set). The stale-session cleanup on next startup will
  // catch anything we miss.
  if (currentSession?.sessionId != null) {
    try {
      endSession(currentSession.sessionId, null, currentSession.mood);
    } catch { /* DB may already be closing */ }
    currentSession = null;
  }

  closeAllDbs();

  // Force exit after 2s if lingering async work (e.g. Telegram long-poll) prevents clean shutdown
  setTimeout(() => {
    log.warn('Force exiting - async cleanup took too long');
    process.exit(0);
  }, 2000).unref();
});

// ---------------------------------------------------------------------------
// Graceful shutdown on SIGTERM/SIGINT (e.g. launchctl stop, Ctrl+C)
// ---------------------------------------------------------------------------

function gracefulShutdown(signal: string): void {
  log.info(`received ${signal} - shutting down gracefully`);
  _forceQuit = true;
  app.quit();
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));

// ---------------------------------------------------------------------------
// Crash rate limiter - detects crash loops and disables subsystems
// ---------------------------------------------------------------------------

const CRASH_LOG_PATH = path.join(USER_DATA, 'crash-log.json');
const CRASH_WINDOW_MS = 10 * 60 * 1000; // 10 minutes
const MAX_CRASHES_IN_WINDOW = 5;

function readCrashTimestamps(): number[] {
  try {
    if (!fs.existsSync(CRASH_LOG_PATH)) return [];
    const raw = JSON.parse(fs.readFileSync(CRASH_LOG_PATH, 'utf-8'));
    if (Array.isArray(raw) && raw.every((v) => typeof v === 'number')) return raw;
    // File has unexpected shape - remove it so we self-heal
    fs.unlinkSync(CRASH_LOG_PATH);
    return [];
  } catch {
    // Corrupt file (partial write, bad JSON) - delete so future boots aren't blind
    try { fs.unlinkSync(CRASH_LOG_PATH); } catch { /* already gone */ }
    return [];
  }
}

function recordCrash(): void {
  try {
    const cutoff = Date.now() - CRASH_WINDOW_MS;
    const timestamps = readCrashTimestamps().filter((t) => t > cutoff);
    timestamps.push(Date.now());
    fs.writeFileSync(CRASH_LOG_PATH, JSON.stringify(timestamps));
  } catch { /* best effort */ }
}

function isCrashRateSafe(): boolean {
  const cutoff = Date.now() - CRASH_WINDOW_MS;
  const recent = readCrashTimestamps().filter((t) => t > cutoff);
  return recent.length < MAX_CRASHES_IN_WINDOW;
}

// Record a boot timestamp so we can detect crash loops.
// On a healthy boot this entry ages out of the window naturally.
// Only record for the primary instance - second instances that quit
// immediately (single-instance lock) should not pollute the crash log.
if (gotTheLock) recordCrash();

// ---------------------------------------------------------------------------
// Global error handlers - catch unhandled rejections and exceptions
// ---------------------------------------------------------------------------

process.on('uncaughtException', (error) => {
  log.error(`uncaughtException: ${error.message}\n${error.stack}`);
  // Don't exit - Electron can often continue after non-fatal exceptions
});

process.on('unhandledRejection', (reason) => {
  const message = reason instanceof Error ? `${reason.message}\n${reason.stack}` : String(reason);
  log.error(`unhandledRejection: ${message}`);
});
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

// Keep BUNDLE_ROOT and USER_DATA referenced so they don't get tree-shaken
void BUNDLE_ROOT;
void USER_DATA;
