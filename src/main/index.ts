/**
 * Electron main process entry point.
 * Port of main.py - two modes: menu bar (--app) and GUI (--gui).
 */

import { app, BrowserWindow, Tray, Menu, globalShortcut, nativeImage, ipcMain } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { ensureUserData, getConfig, BUNDLE_ROOT, USER_DATA } from './config';
import { initDb, closeAll as closeAllDbs } from './memory';
import { streamInference, stopInference, resetMcpConfig, InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import { Session } from './session';
import { setActive } from './status';
import { detectMoodShift } from './agency';
import { synthesise, enqueueAudio, setPlaybackCallbacks, clearAudioQueue, stripProsodyTags } from './tts';
import { registerAudioHandlers } from './audio';
import { registerWakeWordHandlers, startWakeWordListener, pauseWakeWord, resumeWakeWord, stopWakeWordListener } from './wake-word';
import { discoverAgents, cycleAgent, getAgentState, setAgentState, setLastActiveAgent, getLastActiveAgent } from './agent-manager';
import { runCoherenceCheck } from './sentinel';
import { drainQueue } from './queue';
import { getAllAgentsUsage, getAllActivity } from './usage';
import { sendNotification } from './notify';
import { startServer, stopServer } from './server';
import { startDaemon, stopDaemon } from './telegram-daemon';
import { listJobs, installAllJobs, uninstallAllJobs, toggleCron } from './cron';
import { search as vectorSearch } from './vector-search';
import { isLoginItemEnabled, toggleLoginItem } from './install';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let isMenuBarMode = false;
let currentSession: Session | null = null;
let systemPrompt: string | null = null;
let sentinelTimer: ReturnType<typeof setInterval> | null = null;
let queueTimer: ReturnType<typeof setInterval> | null = null;

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
    frame: false,
    transparent: true,
    vibrancy: 'ultra-dark',
    visualEffectState: 'active',
    titleBarStyle: 'hidden',
    trafficLightPosition: { x: -100, y: -100 },
    backgroundColor: '#00000000',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Load renderer
  if (process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
  }

  win.once('ready-to-show', () => {
    if (!isMenuBarMode) {
      win.show();
    }
  });

  win.on('closed', () => {
    mainWindow = null;
  });

  return win;
}

// ---------------------------------------------------------------------------
// Tray (menu bar mode)
// ---------------------------------------------------------------------------

function createTray(): void {
  // Use the menu bar brain icon (template image for macOS light/dark auto-adaptation)
  const iconDir = app.isPackaged
    ? path.join(process.resourcesPath, 'icons')
    : path.join(__dirname, '..', '..', 'resources', 'icons');

  const icon2x = path.join(iconDir, 'menubar_brain@2x.png');
  const icon1x = path.join(iconDir, 'menubar_brain.png');
  const iconPath = fs.existsSync(icon2x) ? icon2x : fs.existsSync(icon1x) ? icon1x : '';

  let trayIcon: Electron.NativeImage;
  if (iconPath) {
    trayIcon = nativeImage.createFromPath(iconPath);
    trayIcon.setTemplateImage(true);
  } else {
    trayIcon = nativeImage.createEmpty();
  }

  tray = new Tray(trayIcon);

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => app.quit(),
    },
  ]);
  tray.setContextMenu(contextMenu);

  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });
}

// ---------------------------------------------------------------------------
// IPC handlers
// ---------------------------------------------------------------------------

function registerIpcHandlers(): void {
  const config = getConfig();

  ipcMain.handle('config:get', () => {
    return {
      agentName: config.AGENT_NAME,
      agentDisplayName: config.AGENT_DISPLAY_NAME,
      userName: config.USER_NAME,
      openingLine: config.OPENING_LINE,
      version: config.VERSION,
      windowWidth: config.WINDOW_WIDTH,
      windowHeight: config.WINDOW_HEIGHT,
      avatarEnabled: config.AVATAR_ENABLED,
      ttsBackend: config.TTS_BACKEND,
      inputMode: config.INPUT_MODE,
    };
  });

  ipcMain.handle('agent:list', () => {
    return discoverAgents();
  });

  ipcMain.handle('agent:cycle', (_event, direction: number) => {
    const next = cycleAgent(direction, config.AGENT_NAME);
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

  ipcMain.handle('opening:get', () => {
    const config = getConfig();
    return config.OPENING_LINE || `Ready. Where are we?`;
  });

  ipcMain.handle('setup:check', () => {
    const cfgPath = path.join(getConfig().DATA_DIR, '..', '..', '..', 'config.json');
    try {
      const userCfg = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
      return !userCfg.setup_complete;
    } catch {
      return true;
    }
  });

  // ── Inference ──

  ipcMain.handle('inference:send', (_event, text: string) => {
    if (!mainWindow) return;

    // Mark user active
    setActive();

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

        case 'SentenceReady':
          // Synthesise TTS in background, send sentence to renderer immediately
          mainWindow.webContents.send('inference:sentenceReady', evt.sentence, '');
          if (config.TTS_BACKEND !== 'off') {
            synthesise(evt.sentence).then((audioPath) => {
              if (audioPath) {
                enqueueAudio(audioPath, evt.index);
              }
            }).catch(() => { /* TTS non-critical */ });
          }
          break;

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
          // Record agent turn
          if (currentSession && fullText) {
            currentSession.addTurn('agent', fullText);
          }
          mainWindow.webContents.send('inference:done', fullText);
          break;

        case 'StreamError':
          mainWindow.webContents.send('inference:error', evt.message);
          break;
      }
    });
  });

  ipcMain.handle('inference:stop', () => {
    stopInference();
  });

  // ── Agent switching (extended) ──

  ipcMain.handle('agent:switch', async (_event, name: string) => {
    // End current session before switching
    if (currentSession && systemPrompt) {
      await currentSession.end(systemPrompt);
    }
    currentSession = null;
    systemPrompt = null;

    // Switch agent config
    config.reloadForAgent(name);
    initDb();
    resetMcpConfig();
    setLastActiveAgent(name);
    clearAudioQueue();

    return {
      agentName: config.AGENT_NAME,
      agentDisplayName: config.AGENT_DISPLAY_NAME,
    };
  });

  // ── Cron ──

  ipcMain.handle('cron:list', () => {
    return listJobs();
  });

  ipcMain.handle('cron:toggle', (_event, enabled: boolean) => {
    toggleCron(enabled);
  });

  // ── Telegram daemon ──

  ipcMain.handle('telegram:startDaemon', () => {
    startDaemon();
  });

  ipcMain.handle('telegram:stopDaemon', () => {
    stopDaemon();
  });

  // ── Server ──

  ipcMain.handle('server:start', (_event, port?: number) => {
    startServer(port);
  });

  ipcMain.handle('server:stop', () => {
    stopServer();
  });

  // ── Vector search ──

  ipcMain.handle('memory:search', async (_event, query: string, n?: number) => {
    return vectorSearch(query, n);
  });

  // ── Login item ──

  ipcMain.handle('install:isEnabled', () => {
    return isLoginItemEnabled();
  });

  ipcMain.handle('install:toggle', (_event, enabled: boolean) => {
    toggleLoginItem(enabled);
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
    // Set dock icon (prevents default Electron icon flash)
    const iconDir = app.isPackaged
      ? path.join(process.resourcesPath, 'icons')
      : path.join(__dirname, '..', '..', 'resources', 'icons');
    const dockIcon = path.join(iconDir, 'icon_dock_512.png');
    if (fs.existsSync(dockIcon)) {
      const icon = nativeImage.createFromPath(dockIcon);
      const resized = icon.resize({ width: 128, height: 128 });
      app.dock?.setIcon(resized);
    }
  }

  // Initialize
  ensureUserData();
  const config = getConfig();
  initDb();

  console.log(`[atrophy] v${config.VERSION} | agent: ${config.AGENT_NAME} | db: ${config.DB_PATH}`);

  // Register IPC
  registerIpcHandlers();
  registerAudioHandlers(() => mainWindow);
  registerWakeWordHandlers();

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
    console.log(`[atrophy] resumed agent: ${config.AGENT_NAME}`);
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
  queueTimer = setInterval(() => {
    const messages = drainQueue();
    for (const msg of messages) {
      if (mainWindow) {
        mainWindow.webContents.send('queue:message', msg);
      }
    }
  }, 10_000);

  // Server mode - no window
  if (isServerMode) {
    const port = parseInt(args[args.indexOf('--port') + 1] || '5000', 10);
    startServer(port);
    return;
  }

  // Create window
  mainWindow = createWindow();

  if (isMenuBarMode) {
    createTray();
    // Global shortcut: Cmd+Shift+Space to toggle
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
  }
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
  stopWakeWordListener(() => mainWindow);
  stopDaemon();
  stopServer();
  closeAllDbs();
});

// Keep BUNDLE_ROOT and USER_DATA referenced so they don't get tree-shaken
void BUNDLE_ROOT;
void USER_DATA;
