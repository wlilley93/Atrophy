/**
 * Electron main process entry point.
 * Port of main.py - two modes: menu bar (--app) and GUI (--gui).
 */

import { app, BrowserWindow, Tray, Menu, globalShortcut, nativeImage, ipcMain, session as electronSession } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { ensureUserData, getConfig, saveUserConfig, saveAgentConfig, saveEnvVar, BUNDLE_ROOT, USER_DATA } from './config';
import { initDb, closeAll as closeAllDbs } from './memory';
import { streamInference, stopInference, resetMcpConfig, InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import { Session } from './session';
import { setActive } from './status';
import { detectMoodShift } from './agency';
import { synthesise, enqueueAudio, setPlaybackCallbacks, clearAudioQueue, playAudio, stopCurrentPlayback } from './tts';
import { registerAudioHandlers } from './audio';
import { registerWakeWordHandlers, pauseWakeWord, resumeWakeWord, stopWakeWordListener } from './wake-word';
import { discoverAgents, cycleAgent, getAgentState, setAgentState, setLastActiveAgent, getLastActiveAgent, checkDeferralRequest, validateDeferralRequest, resetDeferralCounter, suspendAgentSession, resumeAgentSession } from './agent-manager';
import { runCoherenceCheck } from './sentinel';
import { drainQueue, drainAgentQueue, drainAllAgentQueues } from './queue';
import { getAllAgentsUsage, getAllActivity } from './usage';
import { startServer, stopServer } from './server';
import { startDaemon, stopDaemon } from './telegram-daemon';
import { listJobs, toggleCron } from './cron';
import { search as vectorSearch } from './vector-search';
import { isLoginItemEnabled, toggleLoginItem } from './install';
import { getAppIcon, getTrayIcon, TrayState } from './icon';
import { initAutoUpdater, checkForUpdates, downloadUpdate, quitAndInstall } from './updater';
import { ensureAvatarAssets } from './avatar-downloader';
import { createLogger } from './logger';

const log = createLogger('main');

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
let deferralTimer: ReturnType<typeof setInterval> | null = null;
let currentAgentName: string | null = null;

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
    vibrancy: 'ultra-dark',
    visualEffectState: 'active',
    backgroundColor: '#00000000',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'index.js'),
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
          "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: file:; media-src 'self' file:; font-src 'self'; connect-src 'self' https:; frame-src 'self' blob:",
        ],
      },
    });
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

  // Intercept close to show shutdown animation
  let allowClose = false;
  win.on('close', (e) => {
    if (!allowClose) {
      e.preventDefault();
      win.webContents.send('app:shutdownRequested');
    }
  });

  win.on('closed', () => {
    mainWindow = null;
  });

  // Allow actual close after shutdown animation (called from IPC)
  try { ipcMain.removeHandler('app:shutdown'); } catch { /* first time */ }
  ipcMain.handle('app:shutdown', () => {
    allowClose = true;
    win.close();
  });

  return win;
}

// ---------------------------------------------------------------------------
// Tray (menu bar mode)
// ---------------------------------------------------------------------------

function createTray(): void {
  // Prefer the hand-crafted menu bar brain icon (template image for macOS
  // light/dark auto-adaptation). Fall back to a procedural orb icon.
  const iconDir = app.isPackaged
    ? path.join(process.resourcesPath, 'icons')
    : path.join(__dirname, '..', '..', 'resources', 'icons');

  const icon2x = path.join(iconDir, 'menubar_brain@2x.png');
  const icon1x = path.join(iconDir, 'menubar_brain.png');
  const brainPath = fs.existsSync(icon2x) ? icon2x : fs.existsSync(icon1x) ? icon1x : '';

  let trayIcon: Electron.NativeImage;
  if (brainPath) {
    trayIcon = nativeImage.createFromPath(brainPath);
    trayIcon.setTemplateImage(true);
  } else {
    // Procedural orb fallback (44px for @2x tray)
    trayIcon = getTrayIcon('active');
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

/**
 * Update the tray icon to reflect the current state (active, muted, idle, away).
 * Only updates if a tray exists and no hand-crafted brain icon is in use
 * (the brain icon is a template image and handles state differently).
 */
export function updateTrayState(state: TrayState): void {
  if (!tray) return;
  const current = tray.getImage();
  // If using template image (hand-crafted brain), skip procedural updates
  if (current.isTemplateImage()) return;
  tray.setImage(getTrayIcon(state));
}

// ---------------------------------------------------------------------------
// IPC handlers
// ---------------------------------------------------------------------------

function registerIpcHandlers(): void {
  const config = getConfig();

  ipcMain.handle('config:get', () => {
    const c = getConfig();
    return {
      // Identity
      agentName: c.AGENT_NAME,
      agentDisplayName: c.AGENT_DISPLAY_NAME,
      userName: c.USER_NAME,
      openingLine: c.OPENING_LINE,
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
      // Notifications
      notificationsEnabled: c.NOTIFICATIONS_ENABLED,
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
      bundleRoot: BUNDLE_ROOT,
    };
  });

  ipcMain.handle('agent:list', () => {
    return discoverAgents().map(a => a.name);
  });

  ipcMain.handle('agent:listFull', () => {
    return discoverAgents();
  });

  ipcMain.handle('config:update', (_event, updates: Record<string, unknown>) => {
    // Apply updates to running config and save
    const c = getConfig();
    const userUpdates: Record<string, unknown> = {};
    const agentUpdates: Record<string, unknown> = {};

    // Allowlist of keys safe to update from the renderer
    const agentKeys = new Set([
      'AGENT_DISPLAY_NAME', 'OPENING_LINE', 'TTS_BACKEND', 'TTS_PLAYBACK_RATE',
      'ELEVENLABS_VOICE_ID', 'ELEVENLABS_MODEL', 'ELEVENLABS_STABILITY',
      'ELEVENLABS_SIMILARITY', 'ELEVENLABS_STYLE', 'FAL_VOICE_ID',
      'HEARTBEAT_ACTIVE_START', 'HEARTBEAT_ACTIVE_END', 'HEARTBEAT_INTERVAL_MINS',
      'TELEGRAM_CHAT_ID', 'WINDOW_WIDTH', 'WINDOW_HEIGHT',
      'DISABLED_TOOLS',
    ]);
    const userKeys = new Set([
      'USER_NAME', 'INPUT_MODE', 'PTT_KEY', 'WAKE_WORD_ENABLED', 'WAKE_WORDS',
      'WAKE_CHUNK_SECONDS', 'SAMPLE_RATE', 'MAX_RECORD_SEC',
      'CLAUDE_EFFORT', 'ADAPTIVE_EFFORT', 'CONTEXT_SUMMARIES',
      'MAX_CONTEXT_TOKENS', 'VECTOR_SEARCH_WEIGHT', 'EMBEDDING_MODEL',
      'SESSION_SOFT_LIMIT_MINS', 'NOTIFICATIONS_ENABLED',
      'AVATAR_ENABLED', 'AVATAR_RESOLUTION', 'OBSIDIAN_VAULT',
      'setup_complete',
    ]);
    const safeKeys = new Set([...agentKeys, ...userKeys]);

    for (const [key, value] of Object.entries(updates)) {
      if (!safeKeys.has(key)) continue;
      if (key in c) {
        (c as Record<string, unknown>)[key] = value;
      }
      if (agentKeys.has(key)) {
        agentUpdates[key] = value;
      } else {
        userUpdates[key] = value;
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
    const cfgPath = path.join(USER_DATA, 'config.json');
    try {
      const userCfg = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
      return !userCfg.setup_complete;
    } catch {
      return true;
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
    saveEnvVar(key, value);
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

  ipcMain.handle('setup:googleOAuth', async (_event, wantWorkspace: boolean, wantExtra: boolean) => {
    if (!wantWorkspace && !wantExtra) return 'skipped';

    const { execFile } = require('child_process');
    const { promisify } = require('util');
    const execFileAsync = promisify(execFile);

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

    try {
      const args: string[] = [];
      if (wantWorkspace) args.push('--workspace');
      if (wantExtra) args.push('--extra');

      // Only pass necessary env vars to subprocess
      const safeEnv: Record<string, string> = {};
      for (const k of ['PATH', 'HOME', 'USER', 'LANG', 'TERM', 'PYTHONPATH', 'VIRTUAL_ENV']) {
        if (process.env[k]) safeEnv[k] = process.env[k]!;
      }
      await execFileAsync(pythonPath, [scriptPath, ...args], {
        timeout: 120_000,
        env: safeEnv,
      });
      return 'complete';
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return `error: ${msg}`;
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

    // Stop any running inference before switching
    stopInference();
    clearAudioQueue();

    // Switch agent config
    config.reloadForAgent(name);
    initDb();
    resetMcpConfig();
    currentAgentName = name;
    setLastActiveAgent(name);

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

  ipcMain.handle('server:stop', async () => {
    await stopServer();
  });

  // ── Vector search ──

  ipcMain.handle('memory:search', async (_event, query: string, n?: number) => {
    return vectorSearch(query, n);
  });

  // ── Avatar video ──

  ipcMain.handle('avatar:getVideoPath', (_event, colour?: string, clip?: string) => {
    const c = getConfig();
    const loopsDir = path.join(c.AVATAR_DIR, 'loops');
    const col = colour || 'blue';
    const cl = clip || 'bounce_playful';
    // Validate inputs to prevent path traversal
    if (!/^[a-zA-Z0-9_-]+$/.test(col) || !/^[a-zA-Z0-9_-]+$/.test(cl)) return null;
    const videoPath = path.join(loopsDir, col, `loop_${cl}.mp4`);
    if (fs.existsSync(videoPath)) {
      return videoPath;
    }
    // Fallback to ambient_loop.mp4
    const ambient = path.join(loopsDir, 'ambient_loop.mp4');
    if (fs.existsSync(ambient)) {
      return ambient;
    }
    return null;
  });

  // ── Intro audio ──

  ipcMain.handle('audio:playIntro', async () => {
    const c = getConfig();
    const introPath = path.join(BUNDLE_ROOT, 'agents', c.AGENT_NAME, 'audio', 'intro.mp3');
    if (fs.existsSync(introPath)) {
      try {
        await playAudio(introPath, undefined, false);
      } catch { /* non-critical */ }
    }
  });

  // Play any named audio file from the current agent's audio/ directory
  ipcMain.handle('audio:playAgentAudio', async (_event, filename: string) => {
    // Validate filename to prevent path traversal
    if (!/^[a-zA-Z0-9_-]+\.(mp3|wav|m4a)$/.test(filename)) return;
    const c = getConfig();
    const audioPath = path.join(BUNDLE_ROOT, 'agents', c.AGENT_NAME, 'audio', filename);
    if (fs.existsSync(audioPath)) {
      try {
        await playAudio(audioPath, undefined, false);
      } catch { /* non-critical */ }
    }
  });

  ipcMain.handle('audio:stopPlayback', () => {
    clearAudioQueue();
    stopCurrentPlayback();
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
    // Suspend current agent's session
    if (currentSession && currentSession.cliSessionId) {
      suspendAgentSession(currentAgentName!, currentSession.cliSessionId, currentSession.turnHistory);
    }

    // Switch to target agent
    const config = getConfig();
    config.reloadForAgent(data.target);
    initDb();
    resetMcpConfig();
    currentAgentName = data.target;
    setLastActiveAgent(data.target);
    clearAudioQueue();

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

  // Deferral watcher - check for agent handoff requests every 2s
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
  }, 2_000);

  // Server mode - no window
  if (isServerMode) {
    const port = parseInt(args[args.indexOf('--port') + 1] || '5000', 10);
    startServer(port);
    return;
  }

  // Create window
  mainWindow = createWindow();

  // Initialise auto-updater
  if (mainWindow) {
    initAutoUpdater(mainWindow);
  }

  // Download avatar assets on first launch (non-blocking)
  ensureAvatarAssets(config.AGENT_NAME, mainWindow).catch(() => {
    /* non-critical */
  });

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
  if (deferralTimer) clearInterval(deferralTimer);
  stopWakeWordListener(() => mainWindow);
  stopDaemon();
  stopServer();
  closeAllDbs();
});

// ---------------------------------------------------------------------------
// Graceful shutdown on SIGTERM/SIGINT (e.g. launchctl stop, Ctrl+C)
// ---------------------------------------------------------------------------

function gracefulShutdown(signal: string): void {
  log.info(`received ${signal} - shutting down gracefully`);
  app.quit();
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

// Keep BUNDLE_ROOT and USER_DATA referenced so they don't get tree-shaken
void BUNDLE_ROOT;
void USER_DATA;
