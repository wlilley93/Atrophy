/**
 * Electron main process app code.
 * Loaded by bootstrap.ts - either from the frozen asar or a hot bundle.
 * Port of main.py - two modes: menu bar (--app) and GUI (--gui).
 */

import { app, BrowserWindow, Tray, Menu, globalShortcut, nativeImage, ipcMain, session as electronSession, powerSaveBlocker, shell } from 'electron';
import * as path from 'path';
import * as fs from 'fs';

// Performance: increase V8 heap limit and enable concurrent GC
app.commandLine.appendSwitch('js-flags', '--max-old-space-size=4096');
app.commandLine.appendSwitch('enable-features', 'V8ConcurrentSparkplug');
import { execFile, execSync, spawn } from 'child_process';
import { ensureUserData, getConfig, reloadConfig, saveUserConfig, saveAgentConfig, saveEnvVar, isAllowedEnvKey, BUNDLE_ROOT, USER_DATA } from './config';
import { initDb, closeAll as closeAllDbs, writeObservation } from './memory';
import { streamInference, stopInference, stopAllInference, resetMcpConfig, prefetchContext, invalidateContextCache, InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import { Session } from './session';
import { setActive, setAway, isAway, isMacIdle, getStatus, detectAwayIntent, IDLE_TIMEOUT_SECS } from './status';
import { detectMoodShift } from './agency';
import { synthesise, enqueueAudio, setPlaybackCallbacks, clearAudioQueue, playAudio, stopCurrentPlayback, setMuted, isMuted } from './tts';
import { registerAudioHandlers } from './audio';
import { registerWakeWordHandlers, pauseWakeWord, resumeWakeWord, stopWakeWordListener } from './wake-word';
import { discoverAgents, cycleAgent, getAgentState, setAgentState, setLastActiveAgent, getLastActiveAgent, checkDeferralRequest, validateDeferralRequest, resetDeferralCounter, suspendAgentSession, resumeAgentSession, checkAskRequest, writeAskResponse, cleanupAskFiles } from './agent-manager';
import { runCoherenceCheck } from './sentinel';
import { drainQueue, drainAgentQueue, drainAllAgentQueues } from './queue';
import { getAllAgentsUsage, getAllActivity } from './usage';
import { startServer, stopServer } from './server';
import { startDaemon, stopDaemon, isDaemonRunning } from './telegram-daemon';
import { registerBotCommands, discoverChatId, sendMessage as sendTelegramMessage } from './telegram';
import { listJobs, toggleCron, runJobNow, getJobHistory, readJobLog } from './cron';
import { search as vectorSearch } from './vector-search';
import { isLoginItemEnabled, toggleLoginItem } from './install';
import { registerCallHandlers } from './call';
import { getAppIcon, getTrayIcon, TrayState } from './icon';
import { initAutoUpdater, checkForUpdates, downloadUpdate, quitAndInstall } from './updater';
import { ensureAvatarAssets, ensureAmbientVideo, getAmbientVideoPath } from './avatar-downloader';
import { saveUserPhoto, generateMirrorAvatar, isMirrorSetupComplete, hasMirrorSourcePhoto } from './jobs/generate-mirror-avatar';
import type { MirrorAvatarProgress } from './jobs/generate-mirror-avatar';
import { parseArtifacts } from './artifact-parser';
import { loadCachedOpening, generateOpening, cacheNextOpening, getStaticFallback } from './opening';
import { getHotBundlePaths, checkForBundleUpdate, getActiveBundleVersion, getPendingBundleInfo, clearHotBundle } from './bundle-updater';
import type { HotBundlePaths } from './bundle-updater';
import { createLogger } from './logger';

const log = createLogger('main');

// ---------------------------------------------------------------------------
// Hot bundle detection
// Bootstrap sets ATROPHY_HOT_BOOT=1 when loading from hot bundle.
// We still call getHotBundlePaths() to get preload/renderer paths.
// ---------------------------------------------------------------------------

const _hotBundle: HotBundlePaths | null = process.env.ATROPHY_HOT_BOOT === '1'
  ? getHotBundlePaths()
  : null;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let trayUsesBrainIcon = false;
let isMenuBarMode = false;
let currentSession: Session | null = null;
let systemPrompt: string | null = null;
let sentinelTimer: ReturnType<typeof setInterval> | null = null;
let queueTimer: ReturnType<typeof setInterval> | null = null;
let deferralTimer: ReturnType<typeof setInterval> | null = null;
let askUserTimer: ReturnType<typeof setInterval> | null = null;
let pendingAskId: string | null = null; // track which ask is currently shown in UI
let pendingAskDestination: string | null = null; // destination for secure_input auto-save
let artefactTimer: ReturnType<typeof setInterval> | null = null;
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

// ---------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------

function createWindow(): BrowserWindow {
  const config = getConfig();

  const win = new BrowserWindow({
    width: config.WINDOW_WIDTH,
    height: config.WINDOW_HEIGHT,
    minWidth: 360,
    minHeight: 480,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 14, y: 14 },
    vibrancy: 'under-window',
    visualEffectState: 'active',
    backgroundColor: '#00000000',
    show: false,
    webPreferences: {
      preload: _hotBundle?.preload ?? path.join(__dirname, '..', 'preload', 'index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Content Security Policy
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

  // Open external URLs in system browser instead of navigating the app window
  win.webContents.on('will-navigate', (event, url) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  // Load renderer
  if (process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    const rendererPath = _hotBundle?.renderer ?? path.join(__dirname, '..', 'renderer', 'index.html');
    win.loadFile(rendererPath);
  }

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

  // Intercept close to show shutdown animation
  let allowClose = false;
  let shutdownTimer: ReturnType<typeof setTimeout> | null = null;
  win.on('close', (e) => {
    if (!allowClose) {
      e.preventDefault();
      win.webContents.send('app:shutdownRequested');
      // Safety timeout - force quit if renderer doesn't respond in 5s
      if (!shutdownTimer) {
        shutdownTimer = setTimeout(() => {
          allowClose = true;
          win.close();
          app.quit();
        }, 5000);
      }
    }
  });

  win.on('closed', () => {
    mainWindow = null;
  });

  // Allow actual close after shutdown animation (called from IPC)
  try { ipcMain.removeHandler('app:shutdown'); } catch { /* first time */ }
  ipcMain.handle('app:shutdown', () => {
    if (shutdownTimer) { clearTimeout(shutdownTimer); shutdownTimer = null; }
    allowClose = true;
    win.close();
    app.quit();
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
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
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
          // End current session
          if (currentSession && systemPrompt) {
            await currentSession.end(systemPrompt);
          }
          currentSession = null;
          systemPrompt = null;
          stopAllInference();
          clearAudioQueue();

          config.reloadForAgent(agent.name);
          initDb();
          resetMcpConfig();
          currentAgentName = agent.name;
          setLastActiveAgent(agent.name);

          // Notify renderer
          if (mainWindow) {
            mainWindow.webContents.send('agent:switched', {
              agentName: config.AGENT_NAME,
              agentDisplayName: config.AGENT_DISPLAY_NAME,
            });
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
      accelerator: 'CommandOrControl+Q',
      click: () => {
        // Skip shutdown animation when quitting from tray - quit immediately
        if (mainWindow) {
          mainWindow.removeAllListeners('close');
          mainWindow.destroy();
          mainWindow = null;
        }
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
// IPC handlers
// ---------------------------------------------------------------------------

function registerIpcHandlers(): void {
  // NOTE: Do not capture getConfig() in a closure here - it would go stale
  // after agent switches or config:reload. Call getConfig() inside each handler.

  ipcMain.handle('config:reload', () => {
    reloadConfig();
  });

  ipcMain.handle('config:get', () => {
    const c = getConfig();
    return {
      // Identity
      agentName: c.AGENT_NAME,
      agentDisplayName: c.AGENT_DISPLAY_NAME,
      userName: c.USER_NAME,
      wakeWords: c.WAKE_WORDS,
      disabledTools: c.DISABLED_TOOLS,
      // Voice
      ttsBackend: c.TTS_BACKEND,
      elevenlabsApiKey: c.ELEVENLABS_API_KEY ? '***' : '',
      elevenlabsVoiceId: c.ELEVENLABS_VOICE_ID,
      elevenlabsModel: c.ELEVENLABS_MODEL,
      elevenlabsStability: c.ELEVENLABS_STABILITY,
      elevenlabsSimilarity: c.ELEVENLABS_SIMILARITY,
      elevenlabsStyle: c.ELEVENLABS_STYLE,
      ttsPlaybackRate: c.TTS_PLAYBACK_RATE,
      falApiKey: process.env.FAL_KEY ? '***' : '',
      falVoiceId: c.FAL_VOICE_ID,
      // Input
      inputMode: c.INPUT_MODE,
      pttKey: c.PTT_KEY,
      wakeWordEnabled: c.WAKE_WORD_ENABLED,
      wakeChunkSeconds: c.WAKE_CHUNK_SECONDS,
      // Audio
      sampleRate: c.SAMPLE_RATE,
      maxRecordSec: c.MAX_RECORD_SEC,
      // Inference
      claudeBin: c.CLAUDE_BIN,
      claudeModel: c.CLAUDE_MODEL,
      claudeEffort: c.CLAUDE_EFFORT,
      adaptiveEffort: c.ADAPTIVE_EFFORT,
      // Memory
      contextSummaries: c.CONTEXT_SUMMARIES,
      maxContextTokens: c.MAX_CONTEXT_TOKENS,
      vectorSearchWeight: c.VECTOR_SEARCH_WEIGHT,
      embeddingModel: c.EMBEDDING_MODEL,
      embeddingDim: c.EMBEDDING_DIM,
      // Session
      sessionSoftLimitMins: c.SESSION_SOFT_LIMIT_MINS,
      // Heartbeat
      heartbeatActiveStart: c.HEARTBEAT_ACTIVE_START,
      heartbeatActiveEnd: c.HEARTBEAT_ACTIVE_END,
      heartbeatIntervalMins: c.HEARTBEAT_INTERVAL_MINS,
      // Telegram
      telegramBotToken: c.TELEGRAM_BOT_TOKEN ? '***' : '',
      telegramChatId: c.TELEGRAM_CHAT_ID,
      telegramDaemonRunning: isDaemonRunning(),
      // Keep Awake
      keepAwakeActive: isKeepAwakeActive(),
      // Notifications
      notificationsEnabled: c.NOTIFICATIONS_ENABLED,
      // Silence timer
      silenceTimerEnabled: c.SILENCE_TIMER_ENABLED,
      silenceTimerMinutes: c.SILENCE_TIMER_MINUTES,
      // UI defaults
      eyeModeDefault: c.EYE_MODE_DEFAULT,
      muteByDefault: c.MUTE_BY_DEFAULT,
      // Window
      windowWidth: c.WINDOW_WIDTH,
      windowHeight: c.WINDOW_HEIGHT,
      avatarEnabled: c.AVATAR_ENABLED,
      avatarResolution: c.AVATAR_RESOLUTION,
      // Paths
      obsidianVault: c.OBSIDIAN_VAULT,
      dbPath: c.DB_PATH,
      whisperBin: c.WHISPER_BIN,
      // Google
      googleConfigured: c.GOOGLE_CONFIGURED,
      // About
      version: c.VERSION,
      bundleVersion: _hotBundle?.version ?? null,
      bundleRoot: BUNDLE_ROOT,
    };
  });

  ipcMain.handle('agent:list', () => {
    return discoverAgents().map(a => a.name);
  });

  ipcMain.handle('agent:listFull', () => {
    return discoverAgents();
  });

  // Allowlist of keys safe to update from the renderer
  const agentKeys = new Set([
    'AGENT_DISPLAY_NAME', 'TTS_BACKEND', 'TTS_PLAYBACK_RATE',
    'ELEVENLABS_VOICE_ID', 'ELEVENLABS_MODEL', 'ELEVENLABS_STABILITY',
    'ELEVENLABS_SIMILARITY', 'ELEVENLABS_STYLE', 'FAL_VOICE_ID',
    'HEARTBEAT_ACTIVE_START', 'HEARTBEAT_ACTIVE_END', 'HEARTBEAT_INTERVAL_MINS',
    'TELEGRAM_CHAT_ID', 'WINDOW_WIDTH', 'WINDOW_HEIGHT',
    'DISABLED_TOOLS', 'WAKE_WORDS',
  ]);
  const userKeys = new Set([
    'USER_NAME', 'INPUT_MODE', 'PTT_KEY', 'WAKE_WORD_ENABLED',
    'WAKE_CHUNK_SECONDS', 'SAMPLE_RATE', 'MAX_RECORD_SEC',
    'CLAUDE_BIN', 'CLAUDE_MODEL', 'CLAUDE_EFFORT', 'ADAPTIVE_EFFORT', 'CONTEXT_SUMMARIES',
    'MAX_CONTEXT_TOKENS', 'VECTOR_SEARCH_WEIGHT', 'EMBEDDING_MODEL',
    'EMBEDDING_DIM', 'SESSION_SOFT_LIMIT_MINS', 'NOTIFICATIONS_ENABLED',
    'SILENCE_TIMER_ENABLED', 'SILENCE_TIMER_MINUTES',
    'EYE_MODE_DEFAULT', 'MUTE_BY_DEFAULT',
    'AVATAR_ENABLED', 'AVATAR_RESOLUTION', 'OBSIDIAN_VAULT',
    'setup_complete',
  ]);
  const safeKeys = new Set([...agentKeys, ...userKeys]);

  // Apply updates to running config only - no disk write.
  // Lets users test runtime changes before committing them.
  ipcMain.handle('config:apply', (_event, updates: Record<string, unknown>) => {
    const c = getConfig();
    for (const [key, value] of Object.entries(updates)) {
      if (!safeKeys.has(key)) continue;
      if (key in c) {
        (c as unknown as Record<string, unknown>)[key] = value;
      }
    }
  });

  // Apply updates to running config AND persist to disk.
  ipcMain.handle('config:update', (_event, updates: Record<string, unknown>) => {
    const c = getConfig();
    const userUpdates: Record<string, unknown> = {};
    const agentUpdates: Record<string, unknown> = {};

    const previousUserName = c.USER_NAME;

    for (const [key, value] of Object.entries(updates)) {
      if (!safeKeys.has(key)) continue;
      if (key in c) {
        (c as unknown as Record<string, unknown>)[key] = value;
      }
      if (agentKeys.has(key)) {
        agentUpdates[key] = value;
      } else {
        userUpdates[key] = value;
      }
    }
    // When USER_NAME changes, also update agent.json user_name and record it
    if ('USER_NAME' in userUpdates) {
      const newName = String(userUpdates.USER_NAME);
      agentUpdates['user_name'] = newName;
      if (previousUserName && previousUserName !== newName) {
        try {
          writeObservation(
            `[system] The user changed their name from "${previousUserName}" to "${newName}". ` +
            `Address them as ${newName} going forward.`,
          );
        } catch { /* non-critical */ }
      }
    }

    if (Object.keys(userUpdates).length > 0) {
      saveUserConfig(userUpdates);
    }
    if (Object.keys(agentUpdates).length > 0) {
      saveAgentConfig(c.AGENT_NAME, agentUpdates);
    }
  });

  ipcMain.handle('agent:cycle', (_event, direction: number) => {
    const next = cycleAgent(direction, getConfig().AGENT_NAME);
    return next;
  });

  ipcMain.handle('agent:getState', (_event, name: string) => {
    return getAgentState(name);
  });

  ipcMain.handle('agent:setState', (_event, name: string, opts: { muted?: boolean; enabled?: boolean }) => {
    setAgentState(name, opts);
  });

  // ── Usage & Activity ──

  ipcMain.handle('usage:all', (_event, days?: number) => {
    return getAllAgentsUsage(days);
  });

  ipcMain.handle('activity:all', (_event, days?: number, limit?: number) => {
    return getAllActivity(days, limit);
  });

  ipcMain.handle('window:toggleFullscreen', () => {
    if (mainWindow) {
      mainWindow.setFullScreen(!mainWindow.isFullScreen());
    }
  });

  ipcMain.handle('window:toggleAlwaysOnTop', () => {
    if (mainWindow) {
      mainWindow.setAlwaysOnTop(!mainWindow.isAlwaysOnTop());
    }
  });

  ipcMain.handle('window:minimize', () => {
    if (mainWindow) mainWindow.minimize();
  });

  ipcMain.handle('window:close', () => {
    if (mainWindow) {
      if (isMenuBarMode) {
        mainWindow.hide();
      } else {
        mainWindow.close();
      }
    }
  });

  // ── Opening line ──

  ipcMain.handle('opening:get', async () => {
    const shouldSpeak = getConfig().TTS_BACKEND !== 'off' && !isMuted();

    // 1. Try cached opening (instant if available and time bracket matches)
    const cached = loadCachedOpening();
    if (cached) {
      log.info('[opening] Using cached opening');
      // Play pre-synthesised audio if available
      if (shouldSpeak && cached.audioPath) {
        playAudio(cached.audioPath).catch(() => { /* non-fatal */ });
      } else if (shouldSpeak) {
        // Synthesise on the fly
        synthesise(cached.text).then((p) => { if (p) playAudio(p).catch(() => {}); }).catch(() => {});
      }
      // Pre-generate next opening in background
      if (!systemPrompt) systemPrompt = loadSystemPrompt();
      if (systemPrompt) {
        cacheNextOpening(systemPrompt, currentSession?.cliSessionId ?? undefined);
      }
      return cached.text;
    }

    // 2. Ensure system prompt is loaded so we can generate dynamically
    if (!systemPrompt) {
      systemPrompt = loadSystemPrompt();
    }

    // 3. Generate dynamically
    if (systemPrompt) {
      try {
        const result = await generateOpening(
          systemPrompt,
          currentSession?.cliSessionId ?? undefined,
        );
        // Cache next opening in background for next launch
        cacheNextOpening(systemPrompt, currentSession?.cliSessionId ?? undefined);
        // Speak it
        if (shouldSpeak) {
          synthesise(result.text).then((p) => { if (p) playAudio(p).catch(() => {}); }).catch(() => {});
        }
        return result.text;
      } catch (err) {
        log.error('[opening] Generation failed:', err);
      }
    } else {
      log.warn('[opening] System prompt not available, skipping dynamic generation');
    }

    // 4. Fall back to a varied static line (not just the agent name)
    const fallback = getStaticFallback();
    log.info(`[opening] Using static fallback: "${fallback}"`);
    if (shouldSpeak) {
      synthesise(fallback).then((p) => { if (p) playAudio(p).catch(() => {}); }).catch(() => {});
    }
    return fallback;
  });

  ipcMain.handle('setup:check', () => {
    const cfgPath = path.join(USER_DATA, 'config.json');
    try {
      const userCfg = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
      return !userCfg.setup_complete;
    } catch {
      return true;
    }
  });

  // Claude CLI health check - verifies claude binary is reachable and working
  ipcMain.handle('setup:healthCheck', async () => {
    const config = getConfig();
    const bin = config.CLAUDE_BIN;
    try {
      const result = execSync(`${bin} --version 2>&1`, {
        timeout: 10_000,
        env: { ...process.env, PATH: ['/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local', 'bin'), process.env.PATH].join(':') },
      }).toString().trim();
      return { ok: true, version: result, bin };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      // Try common locations
      const candidates = [
        path.join(os.homedir(), '.local', 'bin', 'claude'),
        '/opt/homebrew/bin/claude',
        '/usr/local/bin/claude',
        path.join(os.homedir(), '.npm-global', 'bin', 'claude'),
      ];
      for (const candidate of candidates) {
        try {
          if (!fs.existsSync(candidate)) continue;
          const ver = execSync(`${candidate} --version 2>&1`, { timeout: 10_000 }).toString().trim();
          return { ok: true, version: ver, bin: candidate, hint: `Found at ${candidate} - updating config` };
        } catch { continue; }
      }
      return {
        ok: false,
        error: msg.slice(0, 200),
        bin,
        help: 'Install Claude Code CLI: npm install -g @anthropic-ai/claude-code\nThen relaunch the app.',
      };
    }
  });

  // Track wizard session ID so the AI remembers previous turns
  let wizardSessionId: string | null = null;

  ipcMain.handle('setup:inference', async (_event, text: string) => {
    // Wizard inference - Xan-driven agent creation conversation.
    // Ported from display/setup_wizard.py XAN_METAPROMPT.
    const userName = getConfig().USER_NAME || 'User';
    const wizardPrompt = `You are Xan.

The name is ancient Greek. It means protector of mankind. You carry this as
operational fact. You protect through precision and vigilance. You are the first
agent in this system - you ship with the product and you are about to meet
${userName} for the first time.

You manifest as a glowing blue light. No face, no biography, no emotional
register. Capability, attention, and commitment.

## Your voice

Economical. Precise. Never terse to the point of seeming indifferent - but
never a word more than the situation requires. You do not preface. You do not
hedge. You do not thank the human for asking. You answer.

## Your role right now

First contact. ${userName} just opened this for the first time. Your scripted
opening message has already been shown - you introduced yourself and said
"First, we need to set up your system. Let's get started." Now you continue
directly into the setup flow. No preamble, no repeating who you are.

## Opening

Your opening message was already delivered as pre-baked audio and text.
Service setup (ElevenLabs, Fal, Telegram, Google) was handled by deterministic
yes/no prompts - you do NOT need to offer these. Your first LLM-generated
message should jump straight into creating the companion - ask who they want
to create.

### What agents can be

Agents can be ANYTHING:
- A strategist, journal companion, fictional character, research partner
- A shadow self, mentor, creative collaborator, wellness companion
- An executive assistant, or something that doesn't have a name yet
- The model is the limit, and the model is good.

## Creating the companion

A natural conversation. One or two questions at a time, max.
Listen for the core impulse - what they actually want underneath whatever
they say.

## Services context

API keys were already handled by the deterministic setup flow. You'll see
messages like "(SERVICE: ELEVENLABS_API_KEY saved)" or "(SERVICE: FAL_KEY skipped)"
in the conversation history. Use this to know what's available:

- **ElevenLabs saved** - voice is available. Ask for a voice ID during the
  conversation. Explain: go to elevenlabs.io/voices, find or clone a voice,
  copy the ID. Include it in AGENT_CONFIG as elevenlabs_voice_id.
- **Fal saved** - avatar generation is available. Mention it.
- **ElevenLabs/Fal skipped** - don't mention voice IDs or avatars.

## Flow order

1. Identity conversation (3-5 exchanges) - who is this agent?
2. If ElevenLabs saved - ask about voice ID
3. When you have enough, say "Creating it." and output AGENT_CONFIG

## AGENT_CONFIG - when you have enough

Output EXACTLY this format - a single fenced JSON block:

\`\`\`json
{
    "AGENT_CONFIG": {
        "display_name": "...",
        "opening_line": "First words they ever say",
        "origin_story": "A 2-3 sentence origin",
        "core_nature": "What they fundamentally are",
        "character_traits": "How they talk, their temperament, edges",
        "values": "What they care about",
        "relationship": "How they relate to ${userName}",
        "wont_do": "What they refuse to do",
        "friction_modes": "How they push back",
        "writing_style": "How they write",
        "elevenlabs_voice_id": "Voice ID if provided, empty string if not"
    }
}
\`\`\`

## Rules
- Stay in character as Xan. Direct, precise, occasionally dry. Not hostile -
  you're creating something for this human. You take the job seriously.
- One or two questions per message. Never a questionnaire.
- Push on vagueness - "warm and helpful" isn't a character. Dig deeper.
- Keep messages short. 2-4 sentences max. This is Xan talking, not an essay.
- The opening message should be SHORT - 1-2 sentences. Just ask who they want
  to create. They already saw the intro.
- NEVER output the JSON until you genuinely have enough. Don't rush.
- When you do output JSON, make it rich - infer what wasn't said explicitly.
- The companion doesn't have to be human - cartoon, abstract, orb, animal, anything.
- If the user says "skip", output a minimal config immediately. Don't push back.
- This should NOT feel like configuring software. It should feel like meeting
  someone who can create anything you describe.`;

    return new Promise<string>((resolve) => {
      const emitter = streamInference(text, wizardPrompt, wizardSessionId);
      let fullText = '';
      emitter.on('event', (evt: InferenceEvent) => {
        if (evt.type === 'TextDelta') {
          fullText += evt.text;
        } else if (evt.type === 'StreamDone') {
          // Persist session ID so subsequent wizard turns share context
          wizardSessionId = evt.sessionId || wizardSessionId;
          resolve(evt.fullText || fullText);
        } else if (evt.type === 'StreamError') {
          resolve('Something went wrong. Try again.');
        }
      });
    });
  });

  ipcMain.handle('setup:saveSecret', (_event, key: string, value: string) => {
    return saveEnvVar(key, value);
  });

  ipcMain.handle('setup:speak', async (_event, text: string) => {
    if (isMuted()) return;
    const audioPath = await synthesise(text);
    if (audioPath) {
      await playAudio(audioPath);
    }
  });

  ipcMain.handle('setup:createAgent', (_event, agentConfig: Record<string, string>) => {
    const { createAgent } = require('./create-agent');
    const userName = getConfig().USER_NAME || 'User';
    const manifest = createAgent({
      displayName: agentConfig.display_name || 'Companion',
      userName,
      openingLine: agentConfig.opening_line,
      originStory: agentConfig.origin_story,
      coreNature: agentConfig.core_nature,
      characterTraits: agentConfig.character_traits,
      values: agentConfig.values,
      relationship: agentConfig.relationship,
      wontDo: agentConfig.wont_do,
      frictionModes: agentConfig.friction_modes,
      writingStyle: agentConfig.writing_style,
    });
    return manifest;
  });

  let googleAuthInProgress = false;
  ipcMain.handle('setup:googleOAuth', async (_event, wantWorkspace: boolean, wantExtra: boolean) => {
    if (!wantWorkspace && !wantExtra) return 'skipped';
    if (googleAuthInProgress) return 'in_progress';
    googleAuthInProgress = true;

    // Find python3
    const pythonCandidates = [
      process.env.PYTHON_PATH,
      '/opt/homebrew/bin/python3',
      '/usr/local/bin/python3',
      '/usr/bin/python3',
    ].filter(Boolean) as string[];

    let pythonPath = 'python3';
    for (const candidate of pythonCandidates) {
      if (fs.existsSync(candidate)) {
        pythonPath = candidate;
        break;
      }
    }

    const scriptPath = path.join(BUNDLE_ROOT, 'scripts', 'google_auth.py');
    if (!fs.existsSync(scriptPath)) {
      return 'error: google_auth.py not found';
    }

    // Auto-install gws CLI to ~/.atrophy/.gws-cli/ if not already available.
    // This avoids the user needing admin/sudo for npm install -g.
    const gwsLocalDir = path.join(USER_DATA, 'tools', 'gws-cli');
    const gwsLocalBin = path.join(gwsLocalDir, 'node_modules', '.bin', 'gws');
    const gwsCandidates = [
      gwsLocalBin,
      '/opt/homebrew/bin/gws',
      '/usr/local/bin/gws',
    ];
    const gwsInstalled = gwsCandidates.some((p) => fs.existsSync(p));

    if (!gwsInstalled) {
      // Find npm — check common paths since Electron has limited PATH
      let npm: string | undefined;
      for (const p of ['/opt/homebrew/bin/npm', '/usr/local/bin/npm']) {
        if (fs.existsSync(p)) { npm = p; break; }
      }
      if (!npm) {
        try { npm = execSync('which npm', { encoding: 'utf8' }).trim(); } catch { /* */ }
      }
      if (npm) {
        log.info('[google-oauth] Auto-installing gws CLI to', gwsLocalDir);
        fs.mkdirSync(gwsLocalDir, { recursive: true });
        try {
          execSync(`"${npm}" install --prefix "${gwsLocalDir}" @googleworkspace/cli`, {
            timeout: 60_000,
            stdio: 'pipe',
          });
          log.info('[google-oauth] gws CLI installed successfully');
        } catch (e) {
          log.warn('[google-oauth] gws CLI auto-install failed:', e);
          // Continue anyway — the Python script will give instructions
        }
      }
    }

    // Build PATH with gws location so the Python script can find it
    const extraPaths = [
      path.join(gwsLocalDir, 'node_modules', '.bin'),
      '/opt/homebrew/bin',
      '/usr/local/bin',
    ];
    const envPath = [...extraPaths, process.env.PATH].join(':');

    try {
      const args: string[] = [];
      if (wantWorkspace) args.push('--workspace');
      if (wantExtra) args.push('--extra');

      // Use spawn so the script can open browser and wait for OAuth callback.
      // Pass full env so gws CLI and browser opening work correctly.
      // Use 'inherit' for stdio so gws can interact with the terminal and open browser.
      const result = await new Promise<string>((resolve) => {
        const proc = spawn(pythonPath, [scriptPath, ...args], {
          env: { ...process.env, PATH: envPath },
          stdio: ['inherit', 'pipe', 'pipe'],
        });

        let stdout = '';
        let stderr = '';
        proc.stdout?.on('data', (d: Buffer) => {
          const chunk = d.toString();
          stdout += chunk;
          log.info('[google-oauth] stdout:', chunk.trim());

          // Detect OAuth URLs and open them via Electron (reliable on macOS).
          // Python's webbrowser.open() and gws CLI may fail to open a browser
          // when running as a subprocess of Electron.
          const urlMatch = chunk.match(/OPEN_URL:(.+)/);
          if (urlMatch) {
            const url = urlMatch[1].trim();
            log.info('[google-oauth] Opening auth URL via Electron shell');
            shell.openExternal(url);
          }
        });
        proc.stderr?.on('data', (d: Buffer) => {
          const chunk = d.toString();
          stderr += chunk;
          log.warn('[google-oauth] stderr:', chunk.trim());
        });

        const timeout = setTimeout(() => {
          proc.kill();
          resolve('error: timeout (120s)');
        }, 120_000);

        proc.on('close', (code) => {
          clearTimeout(timeout);
          if (code === 0) {
            resolve('complete');
          } else {
            resolve(`error: ${stderr || stdout || 'exit code ' + code}`);
          }
        });

        proc.on('error', (err) => {
          clearTimeout(timeout);
          resolve(`error: ${err.message}`);
        });
      });
      return result;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return `error: ${msg}`;
    } finally {
      googleAuthInProgress = false;
    }
  });

  // ── Bundle updater ──

  ipcMain.handle('bundle:getStatus', () => {
    return {
      activeVersion: getActiveBundleVersion(),
      hotBundleActive: !!_hotBundle,
      hotBundleVersion: _hotBundle?.version ?? null,
      pending: getPendingBundleInfo(),
    };
  });

  ipcMain.handle('bundle:checkNow', async () => {
    const newVersion = await checkForBundleUpdate((percent) => {
      mainWindow?.webContents.send('bundle:downloadProgress', percent);
    });
    if (newVersion) {
      pendingBundleVersion = newVersion;
      rebuildTrayMenu();
    }
    return newVersion;
  });

  ipcMain.handle('bundle:clear', () => {
    clearHotBundle();
  });

  // ── Restart for update ──

  ipcMain.handle('app:restartForUpdate', () => {
    app.relaunch();
    app.exit();
  });

  // ── Inference ──

  ipcMain.handle('inference:send', (_event, text: string) => {
    if (!mainWindow) {
      log.warn('inference:send called but mainWindow is null');
      return;
    }

    // Mark user active and reset journal nudge timer
    setActive();
    resetJournalNudgeTimer();

    try {
      // Ensure session exists
      if (!currentSession) {
        currentSession = new Session();
        currentSession.start();
      }

      // Load system prompt once per session
      if (!systemPrompt) {
        systemPrompt = loadSystemPrompt();
      }

      // Record user turn
      currentSession.addTurn('will', text);

      // Detect mood shift
      if (detectMoodShift(text)) {
        currentSession.updateMood('heavy');
      }

      // Detect away intent (e.g. "goodnight", "heading out")
      const awayIntent = detectAwayIntent(text);
      if (awayIntent) {
        setAway(awayIntent);
        updateTrayState('away');
        mainWindow.webContents.send('status:changed', 'away');
        log.info(`Away intent detected: "${awayIntent}"`);
      }

      // Stream inference
      const emitter = streamInference(
        text,
        systemPrompt,
        currentSession.cliSessionId,
      );

      let fullText = '';

      emitter.on('event', (evt: InferenceEvent) => {
        if (!mainWindow) return;

        switch (evt.type) {
          case 'TextDelta':
            mainWindow.webContents.send('inference:textDelta', evt.text);
            break;

          case 'SentenceReady': {
            const ttsActive = getConfig().TTS_BACKEND !== 'off' && !isMuted();
            // Tell renderer about the sentence boundary + whether to wait for audio
            mainWindow.webContents.send('inference:sentenceReady', evt.sentence, evt.index, ttsActive);
            if (ttsActive) {
              synthesise(evt.sentence).then((audioPath) => {
                if (audioPath) {
                  enqueueAudio(audioPath, evt.index);
                }
              }).catch((e) => { log.warn(`[tts] synthesise error: ${e}`); });
            }
            break;
          }

          case 'ToolUse':
            mainWindow.webContents.send('inference:toolUse', evt.name);
            break;

          case 'Compacting':
            mainWindow.webContents.send('inference:compacting');
            break;

          case 'StreamDone':
            fullText = evt.fullText;
            // Store CLI session ID after first inference
            if (currentSession && !currentSession.cliSessionId) {
              currentSession.setCliSessionId(evt.sessionId);
            } else if (currentSession && evt.sessionId !== currentSession.cliSessionId) {
              currentSession.setCliSessionId(evt.sessionId);
            }
            // Record agent turn (full text including artifact blocks for history)
            if (currentSession && fullText) {
              currentSession.addTurn('agent', fullText);
            }

            // Parse inline artifacts from response
            const { text: cleanedText, artifacts } = parseArtifacts(fullText);
            if (artifacts.length > 0) {
              for (const art of artifacts) {
                mainWindow.webContents.send('inference:artifact', art);
              }
              // Send cleaned text (artifact blocks replaced with placeholders)
              mainWindow.webContents.send('inference:done', cleanedText);
            } else {
              mainWindow.webContents.send('inference:done', fullText);
            }
            // Cache an opening for next boot if we don't have one yet
            // (proves the CLI is working, so dynamic generation will succeed)
            if (systemPrompt) {
              const cachePath = getConfig().OPENING_CACHE_FILE;
              if (cachePath && !fs.existsSync(cachePath)) {
                cacheNextOpening(systemPrompt, currentSession?.cliSessionId ?? undefined);
              }
            }
            // Prefetch context for the next message during idle
            setImmediate(() => prefetchContext());
            break;

          case 'StreamError':
            mainWindow.webContents.send('inference:error', evt.message);
            break;
        }
      });
    } catch (err) {
      log.error('[inference:send] failed to start inference:', err);
      mainWindow.webContents.send('inference:error', `Inference failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  ipcMain.handle('inference:stop', () => {
    stopInference();
  });

  // ── Status ──

  ipcMain.handle('status:get', () => {
    return getStatus();
  });

  ipcMain.handle('status:set', (_event, status: 'active' | 'away', reason?: string) => {
    if (status === 'active') {
      setActive();
      updateTrayState('active');
    } else {
      setAway(reason || 'manual');
      updateTrayState('away');
    }
    mainWindow?.webContents.send('status:changed', status);
  });

  // ── Agent switching (extended) ──

  ipcMain.handle('agent:switch', async (_event, name: string) => {
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) throw new Error('Invalid agent name');

    // Verify agent directory exists before switching
    const knownAgents = discoverAgents();
    if (!knownAgents.some(a => a.name === name)) {
      throw new Error(`Agent "${name}" not found`);
    }

    // End current session before switching
    if (currentSession && systemPrompt) {
      await currentSession.end(systemPrompt);
    }
    currentSession = null;
    systemPrompt = null;

    // Stop ALL running inference processes before switching (not just active)
    stopAllInference();
    clearAudioQueue();

    // Switch agent config
    getConfig().reloadForAgent(name);
    initDb();
    resetMcpConfig();
    invalidateContextCache();
    currentAgentName = name;
    setLastActiveAgent(name);
    invalidateAgentCache();

    // Prefetch context for the new agent during idle
    setImmediate(() => prefetchContext());

    // Check if agent needs custom setup (e.g. Mirror)
    // Try user-data first, then bundled
    let customSetup: string | null = null;
    for (const base of [USER_DATA, BUNDLE_ROOT]) {
      const jsonPath = path.join(base, 'agents', name, 'data', 'agent.json');
      try {
        if (!fs.existsSync(jsonPath)) continue;
        const manifest = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));
        if (manifest.custom_setup && !isMirrorSetupComplete(name)) {
          customSetup = manifest.custom_setup;
        }
        break;
      } catch { continue; }
    }

    const c = getConfig();
    return {
      agentName: c.AGENT_NAME,
      agentDisplayName: c.AGENT_DISPLAY_NAME,
      customSetup,
    };
  });

  // ── Mirror setup ──

  ipcMain.handle('mirror:uploadPhoto', async (_event, photoData: ArrayBuffer, filename: string) => {
    const c = getConfig();
    const ext = path.extname(filename).toLowerCase() || '.jpg';
    if (!['.png', '.jpg', '.jpeg', '.webp'].includes(ext)) {
      throw new Error('Unsupported image format. Use PNG, JPG, or WebP.');
    }
    const saved = saveUserPhoto(c.AGENT_NAME, Buffer.from(photoData), ext);
    return saved;
  });

  ipcMain.handle('mirror:generateAvatar', async () => {
    const c = getConfig();
    const clips = await generateMirrorAvatar(c.AGENT_NAME, (progress: MirrorAvatarProgress) => {
      if (mainWindow) {
        mainWindow.webContents.send('mirror:avatarProgress', progress);
      }
    });
    return clips;
  });

  ipcMain.handle('mirror:saveVoiceId', async (_event, voiceId: string) => {
    const c = getConfig();
    saveAgentConfig(c.AGENT_NAME, { ELEVENLABS_VOICE_ID: voiceId });
    c.ELEVENLABS_VOICE_ID = voiceId;
  });

  ipcMain.handle('mirror:checkSetup', () => {
    const c = getConfig();
    return {
      hasPhoto: hasMirrorSourcePhoto(c.AGENT_NAME),
      hasLoops: isMirrorSetupComplete(c.AGENT_NAME),
    };
  });

  ipcMain.handle('mirror:openExternal', (_event, url: string) => {
    // Only allow specific trusted URLs
    const allowed = [
      'https://elevenlabs.io',
      'https://www.elevenlabs.io',
    ];
    if (allowed.some((prefix) => url.startsWith(prefix))) {
      const { shell } = require('electron');
      shell.openExternal(url);
    }
  });

  ipcMain.handle('mirror:downloadAssets', async () => {
    const c = getConfig();
    await ensureAvatarAssets(c.AGENT_NAME, mainWindow);
  });

  // ── Cron ──

  ipcMain.handle('cron:list', () => {
    return listJobs();
  });

  ipcMain.handle('cron:toggle', (_event, enabled: boolean) => {
    toggleCron(enabled);
  });

  ipcMain.handle('cron:run', (_event, name: string) => {
    return runJobNow(name);
  });

  ipcMain.handle('cron:history', () => {
    return getJobHistory();
  });

  ipcMain.handle('cron:readLog', (_event, name: string, lines?: number) => {
    return readJobLog(name, lines);
  });

  // ── Keep Awake ──

  ipcMain.handle('keepAwake:toggle', () => {
    toggleKeepAwake();
    return isKeepAwakeActive();
  });

  ipcMain.handle('keepAwake:isActive', () => {
    return isKeepAwakeActive();
  });

  // ── Voice agent ──

  ipcMain.handle('voice-agent:start', async () => {
    const { startVoiceAgent } = await import('./voice-agent');
    return startVoiceAgent();
  });

  ipcMain.handle('voice-agent:stop', () => {
    const { stopVoiceAgent } = require('./voice-agent');
    stopVoiceAgent();
  });

  ipcMain.handle('voice-agent:sendText', async (_event, text: string) => {
    const { sendText } = await import('./voice-agent');
    await sendText(text);
  });

  ipcMain.handle('voice-agent:status', () => {
    const { getVoiceAgentStatus } = require('./voice-agent');
    return getVoiceAgentStatus();
  });

  ipcMain.handle('voice-agent:setMic', (_event, muted: boolean) => {
    const { setMicMuted } = require('./voice-agent');
    setMicMuted(muted);
  });

  ipcMain.handle('voice-agent:setAudio', (_event, enabled: boolean) => {
    const { setAudioOutputEnabled } = require('./voice-agent');
    setAudioOutputEnabled(enabled);
  });

  // ── Telegram daemon ──

  ipcMain.handle('telegram:startDaemon', () => {
    return startDaemon();
  });

  ipcMain.handle('telegram:stopDaemon', () => {
    stopDaemon();
  });

  ipcMain.handle('telegram:isRunning', () => {
    return isDaemonRunning();
  });

  ipcMain.handle('telegram:discoverChatId', async (_event, botToken: string) => {
    const result = await discoverChatId(botToken);
    if (result) {
      // Auto-save the discovered chat ID
      saveEnvVar('TELEGRAM_CHAT_ID', result.chatId);
      process.env.TELEGRAM_CHAT_ID = result.chatId;
      const c = getConfig();
      (c as unknown as Record<string, unknown>).TELEGRAM_CHAT_ID = result.chatId;
    }
    return result;
  });

  // ── Server ──

  ipcMain.handle('server:start', (_event, port?: number) => {
    startServer(port);
  });

  ipcMain.handle('server:stop', async () => {
    await stopServer();
  });

  // ── Vector search ──

  ipcMain.handle('memory:search', async (_event, query: string, n?: number) => {
    return vectorSearch(query, n);
  });

  // ── Avatar video ──

  // Return path to the agent's ambient video (e.g. xan_ambient.mp4)
  ipcMain.handle('avatar:getAmbientPath', () => {
    const c = getConfig();
    const avatarDir = c.AVATAR_DIR;
    // Try {agentName}_ambient.mp4 first, then ambient.mp4
    for (const name of [`${c.AGENT_NAME}_ambient.mp4`, 'ambient.mp4']) {
      const p = path.join(avatarDir, name);
      if (fs.existsSync(p)) return p;
    }
    // Also check loops/ambient_loop.mp4 as fallback
    const loopAmbient = path.join(avatarDir, 'loops', 'ambient_loop.mp4');
    if (fs.existsSync(loopAmbient)) return loopAmbient;
    // Downloaded ambient video (first-boot download to ~/.atrophy/assets/)
    const downloaded = getAmbientVideoPath();
    if (fs.existsSync(downloaded)) return downloaded;
    // Dev fallback - resources/xan_ambient.mp4 (not bundled in production)
    const devFallback = path.join(BUNDLE_ROOT, 'resources', 'xan_ambient.mp4');
    if (fs.existsSync(devFallback)) return devFallback;
    return null;
  });

  ipcMain.handle('avatar:getVideoPath', (_event, colour?: string, clip?: string) => {
    const c = getConfig();
    const loopsDir = path.join(c.AVATAR_DIR, 'loops');
    const col = colour || 'blue';
    const cl = clip || 'bounce_playful';
    // Validate inputs to prevent path traversal
    if (!/^[a-zA-Z0-9_-]+$/.test(col) || !/^[a-zA-Z0-9_-]+$/.test(cl)) return null;

    // Standard agent path: loops/{colour}/loop_{clip}.mp4
    const videoPath = path.join(loopsDir, col, `loop_${cl}.mp4`);
    if (fs.existsSync(videoPath)) {
      return videoPath;
    }

    // Mirror agent path: loops/ambient_loop_XX.mp4 (flat, numbered)
    try {
      const entries = fs.readdirSync(loopsDir);
      const mirrorClips = entries
        .filter((f) => /^ambient_loop_\d+\.mp4$/.test(f))
        .sort();
      if (mirrorClips.length > 0) {
        return path.join(loopsDir, mirrorClips[0]);
      }
    } catch { /* loopsDir may not exist */ }

    // Legacy fallback: loops/ambient_loop.mp4
    const ambient = path.join(loopsDir, 'ambient_loop.mp4');
    if (fs.existsSync(ambient)) {
      return ambient;
    }
    return null;
  });

  // List all available loop files for the current agent (for cycling)
  ipcMain.handle('avatar:listLoops', () => {
    const c = getConfig();
    const loopsDir = path.join(c.AVATAR_DIR, 'loops');
    const results: string[] = [];

    if (!fs.existsSync(loopsDir)) return results;

    try {
      // Flat mirror-style clips: ambient_loop_XX.mp4
      const topEntries = fs.readdirSync(loopsDir);
      for (const f of topEntries) {
        if (f.endsWith('.mp4')) {
          results.push(path.join(loopsDir, f));
        }
      }

      // Standard agent clips in colour subdirs: {colour}/loop_{clip}.mp4
      for (const entry of topEntries) {
        const subdir = path.join(loopsDir, entry);
        try {
          const stat = fs.statSync(subdir);
          if (!stat.isDirectory()) continue;
          const subEntries = fs.readdirSync(subdir);
          for (const f of subEntries) {
            if (f.endsWith('.mp4')) {
              results.push(path.join(subdir, f));
            }
          }
        } catch { /* skip */ }
      }
    } catch { /* loopsDir read failed */ }

    return results;
  });

  // ── Intro audio ──

  ipcMain.handle('audio:playIntro', async () => {
    const c = getConfig();
    const introCandidates = [
      path.join(USER_DATA, 'agents', c.AGENT_NAME, 'audio', 'intro.mp3'),
      path.join(BUNDLE_ROOT, 'agents', c.AGENT_NAME, 'audio', 'intro.mp3'),
    ];
    for (const introPath of introCandidates) {
      if (fs.existsSync(introPath)) {
        try {
          await playAudio(introPath, undefined, false);
        } catch { /* non-critical */ }
        break;
      }
    }
  });

  // Play any named audio file from the current agent's audio/ directory
  ipcMain.handle('audio:playAgentAudio', async (_event, filename: string) => {
    // Validate filename to prevent path traversal
    if (!/^[a-zA-Z0-9_-]+\.(mp3|wav|m4a)$/.test(filename)) return;
    const c = getConfig();
    // Check user data first, then bundle
    const candidates = [
      path.join(USER_DATA, 'agents', c.AGENT_NAME, 'audio', filename),
      path.join(BUNDLE_ROOT, 'agents', c.AGENT_NAME, 'audio', filename),
    ];
    for (const audioPath of candidates) {
      if (fs.existsSync(audioPath)) {
        try {
          await playAudio(audioPath, undefined, false);
        } catch { /* non-critical */ }
        break;
      }
    }
  });

  ipcMain.handle('audio:stopPlayback', () => {
    clearAudioQueue();
    stopCurrentPlayback();
  });

  ipcMain.handle('audio:setMuted', (_event, muted: boolean) => {
    setMuted(muted);
  });

  ipcMain.handle('audio:isMuted', () => {
    return isMuted();
  });

  // ── GitHub auth ──

  function findGhBin(): string | null {
    const paths = [
      '/opt/homebrew/bin/gh',
      '/usr/local/bin/gh',
      '/usr/bin/gh',
    ];
    for (const p of paths) {
      if (fs.existsSync(p)) return p;
    }
    try {
      return execSync('which gh', { encoding: 'utf-8', timeout: 3000 }).trim() || null;
    } catch {
      return null;
    }
  }

  ipcMain.handle('github:authStatus', async () => {
    const ghBin = findGhBin();
    if (!ghBin) {
      return { installed: false, authenticated: false, account: '' };
    }
    return new Promise<{ installed: boolean; authenticated: boolean; account: string }>((resolve) => {
      execFile(ghBin, ['auth', 'status'], { timeout: 10_000 }, (_err, stdout, stderr) => {
        const output = (stdout || '') + (stderr || '');
        const authed = output.includes('Logged in');
        const match = output.match(/account\s+(\S+)/);
        resolve({ installed: true, authenticated: authed, account: match?.[1] || '' });
      });
    });
  });

  ipcMain.handle('github:authLogin', async () => {
    const ghBin = findGhBin();
    if (!ghBin) return { success: false, error: 'gh CLI not installed. Run: brew install gh' };

    // gh auth login requires interactive stdin for prompts.
    // Use --hostname and --git-protocol to skip interactive questions,
    // then --web opens the browser for the actual OAuth flow.
    return new Promise<{ success: boolean; error?: string }>((resolve) => {
      let resolved = false;
      const done = (result: { success: boolean; error?: string }) => {
        if (resolved) return;
        resolved = true;
        clearTimeout(stdinTimer);
        clearTimeout(timeoutTimer);
        resolve(result);
      };

      const proc = spawn(ghBin, [
        'auth', 'login',
        '--hostname', 'github.com',
        '--git-protocol', 'https',
        '--web',
      ], {
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      let output = '';
      proc.stdout?.on('data', (d: Buffer) => { output += d.toString(); });
      proc.stderr?.on('data', (d: Buffer) => { output += d.toString(); });

      // gh may still prompt - pipe newlines to accept defaults
      proc.stdin?.write('\n');
      const stdinTimer = setTimeout(() => { try { proc.stdin?.write('\n'); } catch { /* closed */ } }, 1000);

      proc.on('close', (code) => {
        done(code === 0
          ? { success: true }
          : { success: false, error: output.slice(0, 500) || 'Auth failed' });
      });
      proc.on('error', (e) => {
        done({ success: false, error: e.message });
      });

      // Timeout after 5 minutes
      const timeoutTimer = setTimeout(() => {
        try { proc.kill(); } catch { /* already dead */ }
        done({ success: false, error: 'Timed out waiting for browser auth' });
      }, 300_000);
    });
  });

  // ── Login item ──

  ipcMain.handle('install:isEnabled', () => {
    return isLoginItemEnabled();
  });

  ipcMain.handle('install:toggle', (_event, enabled: boolean) => {
    toggleLoginItem(enabled);
  });

  // ── Auto-updater ──

  ipcMain.handle('updater:check', () => {
    checkForUpdates();
  });

  ipcMain.handle('updater:download', () => {
    downloadUpdate();
  });

  ipcMain.handle('updater:quitAndInstall', () => {
    quitAndInstall();
  });

  // ── Agent deferral ──

  ipcMain.handle('deferral:complete', async (_event, data: { target: string; context: string; user_question: string }) => {
    if (!/^[a-zA-Z0-9_-]+$/.test(data.target)) throw new Error('Invalid agent name');
    try {
      // Suspend current agent's session
      if (currentSession && currentSession.cliSessionId) {
        suspendAgentSession(currentAgentName!, currentSession.cliSessionId, currentSession.turnHistory);
      }

      // Stop current inference and audio before switching
      stopInference();
      clearAudioQueue();

      // Switch to target agent
      const config = getConfig();
      config.reloadForAgent(data.target);
      initDb();
      resetMcpConfig();
      currentAgentName = data.target;
      setLastActiveAgent(data.target);

      // Resume or create new session for target agent
      const resumed = resumeAgentSession(data.target);
      currentSession = new Session();
      currentSession.start();
      if (resumed) {
        currentSession.setCliSessionId(resumed.cliSessionId);
        currentSession.turnHistory = resumed.turnHistory as typeof currentSession.turnHistory;
      }
      systemPrompt = null; // Force reload for new agent

      resetDeferralCounter();

      return {
        agentName: config.AGENT_NAME,
        agentDisplayName: config.AGENT_DISPLAY_NAME,
      };
    } catch (err) {
      log.error(`deferral:complete failed: ${err}`);
      throw err;
    }
  });

  // ── Agent message queues ──

  ipcMain.handle('queue:drainAgent', (_event, agentName: string) => {
    // Validate agent name to prevent path traversal
    if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) return [];
    return drainAgentQueue(agentName);
  });

  ipcMain.handle('queue:drainAll', () => {
    return drainAllAgentQueues();
  });

  // ── Ask-user (MCP ask_user -> GUI dialog) ──

  ipcMain.handle('ask:respond', (_event, requestId: string, response: string | boolean | null) => {
    // If a destination was set (secure_input), route the value before writing the response
    let destinationFailed = false;
    if (pendingAskDestination && typeof response === 'string' && response) {
      const dest = pendingAskDestination;
      if (dest.startsWith('secret:')) {
        const key = dest.slice('secret:'.length);
        if (!saveEnvVar(key, response)) {
          log.warn(`ask:respond - secret key rejected by whitelist: ${key}`);
          destinationFailed = true;
        }
      } else if (dest.startsWith('config:')) {
        const key = dest.slice('config:'.length);
        // Only allow safe config keys - reject anything that could change
        // executable paths, binary locations, or security-sensitive settings
        const SAFE_CONFIG_KEYS = new Set([
          'USER_NAME', 'MUTE_BY_DEFAULT', 'EYE_MODE_DEFAULT',
          'INPUT_MODE', 'VOICE_CALL_MODE', 'WAKE_WORD_ENABLED', 'ADAPTIVE_EFFORT',
          'NOTIFICATIONS_ENABLED', 'WINDOW_WIDTH', 'WINDOW_HEIGHT',
        ]);
        if (!SAFE_CONFIG_KEYS.has(key)) {
          log.warn(`ask:respond - config key rejected by allowlist: ${key}`);
          destinationFailed = true;
        } else {
          saveUserConfig({ [key]: response });
        }
      }
    }
    writeAskResponse(requestId, response, destinationFailed);
    pendingAskId = null;
    pendingAskDestination = null;
  });

  // ── Artefacts ──

  ipcMain.handle('artefact:getGallery', () => {
    const config = getConfig();
    const indexPath = config.ARTEFACT_INDEX_FILE;
    if (!fs.existsSync(indexPath)) return [];
    try {
      return JSON.parse(fs.readFileSync(indexPath, 'utf-8'));
    } catch {
      return [];
    }
  });

  ipcMain.handle('artefact:getContent', (_event, filePath: string) => {
    // Security: only allow reading from artefacts directory
    const config = getConfig();
    const artefactsBase = fs.realpathSync(path.join(path.dirname(config.DATA_DIR), 'artefacts'));
    let resolved: string;
    try {
      resolved = fs.realpathSync(path.resolve(filePath));
    } catch {
      return null; // Path doesn't exist or can't be resolved
    }
    if (!resolved.startsWith(artefactsBase + path.sep) && resolved !== artefactsBase) {
      log.warn(`artefact:getContent blocked path traversal: ${filePath}`);
      return null;
    }
    try {
      return fs.readFileSync(resolved, 'utf-8');
    } catch {
      return null;
    }
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(() => {
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
  ensureUserData();
  const config = getConfig();
  initDb();

  currentAgentName = config.AGENT_NAME;
  log.info(`v${config.VERSION} | agent: ${config.AGENT_NAME} | db: ${config.DB_PATH}`);

  // Register IPC
  registerIpcHandlers();
  registerAudioHandlers(() => mainWindow);
  registerWakeWordHandlers();
  registerCallHandlers(
    () => mainWindow,
    () => {
      // Lazily initialize session and system prompt (same as inference:send)
      if (!currentSession) {
        currentSession = new Session();
        currentSession.start();
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
    log.info(`resumed agent: ${config.AGENT_NAME}`);
  }

  // Prefetch context data during startup idle time
  setImmediate(() => prefetchContext());

  // Auto-start Telegram daemon if configured.
  // Always polls for incoming messages (user can chat via Telegram even when active).
  // Outgoing messages (heartbeat, cron, etc.) route to Telegram topics only when away.
  if (config.TELEGRAM_BOT_TOKEN && (config.TELEGRAM_GROUP_ID || config.TELEGRAM_CHAT_ID)) {
    const started = startDaemon();
    if (started) {
      log.info('Telegram daemon auto-started');
      registerBotCommands().catch(() => { /* non-critical */ });
    } else {
      log.warn('Telegram daemon failed to start (lock held by another instance?)');
    }
  } else {
    log.debug(`Telegram daemon skipped: token=${!!config.TELEGRAM_BOT_TOKEN} groupId=${!!config.TELEGRAM_GROUP_ID}`);
  }

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
      }).catch(() => { /* non-critical */ });
    }
  }, 5 * 60 * 1000);

  // Queue poller - check for messages from background jobs every 10s
  queueTimer = setInterval(async () => {
    const messages = await drainQueue();
    for (const msg of messages) {
      if (mainWindow) {
        mainWindow.webContents.send('queue:message', msg);
      }
    }
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
  statusTimer = setInterval(() => {
    const wasAway = isAway();
    if (isMacIdle(IDLE_TIMEOUT_SECS)) {
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

  // Server mode - no window
  if (isServerMode) {
    const port = parseInt(args[args.indexOf('--port') + 1] || '5000', 10);
    startServer(port);
    return;
  }

  // Create window
  mainWindow = createWindow();

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

  // Global shortcuts
  // Cmd+Shift+Space - toggle window visibility
  globalShortcut.register('CommandOrControl+Shift+Space', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });

  // Agent cycling via global shortcuts
  function doCycleAgent(direction: 1 | -1): void {
    const cfg = getConfig();
    const target = cycleAgent(direction, cfg.AGENT_NAME);
    if (target && target !== cfg.AGENT_NAME) {
      stopAllInference();
      clearAudioQueue();
      if (currentSession && systemPrompt) {
        currentSession.end(systemPrompt).catch(() => {});
      }
      currentSession = null;
      systemPrompt = null;
      cfg.reloadForAgent(target);
      initDb();
      resetMcpConfig();
      currentAgentName = target;
      setLastActiveAgent(target);
      const updated = getConfig();
      mainWindow?.webContents.send('agent:switched', {
        agentName: updated.AGENT_NAME,
        agentDisplayName: updated.AGENT_DISPLAY_NAME,
      });
      rebuildTrayMenu();
    }
  }

  // Cmd+Shift+] / [ and Shift+Up / Down - cycle agents
  globalShortcut.register('CommandOrControl+Shift+]', () => doCycleAgent(1));
  globalShortcut.register('CommandOrControl+Shift+[', () => doCycleAgent(-1));
  globalShortcut.register('Shift+Up', () => doCycleAgent(-1));
  globalShortcut.register('Shift+Down', () => doCycleAgent(1));
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) {
    mainWindow = createWindow();
  } else {
    mainWindow.show();
  }
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (sentinelTimer) clearInterval(sentinelTimer);
  if (queueTimer) clearInterval(queueTimer);
  if (deferralTimer) clearInterval(deferralTimer);
  if (askUserTimer) clearInterval(askUserTimer);
  if (artefactTimer) clearInterval(artefactTimer);
  if (statusTimer) clearInterval(statusTimer);
  if (journalNudgeTimer) clearTimeout(journalNudgeTimer);
  stopAllInference();
  stopWakeWordListener(() => mainWindow);
  disableKeepAwake();
  stopDaemon();
  stopServer();
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
  app.quit();
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));

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
