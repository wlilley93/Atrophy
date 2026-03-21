/**
 * IPC handler registration - extracted from app.ts.
 * All handlers are registered via ipcMain.handle() and communicate
 * with shared app state through the IpcContext interface.
 */

import { app, ipcMain, shell, BrowserWindow } from 'electron';
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';
import { execFile, execSync, spawn } from 'child_process';
import { getConfig, reloadConfig, saveUserConfig, saveAgentConfig, saveEnvVar, BUNDLE_ROOT, USER_DATA } from './config';
import { initDb, writeObservation } from './memory';
import { streamInference, stopInference, resetMcpConfig, prefetchContext, type InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import { Session } from './session';
import { setActive, setAway, getStatus, detectAwayIntent } from './status';
import { detectMoodShift } from './agency';
import { synthesise, enqueueAudio, clearAudioQueue, playAudio, stopCurrentPlayback, setMuted, isMuted, ttsGeneration } from './tts';
import { discoverAgents, cycleAgent, getAgentState, setAgentState, setLastActiveAgent, suspendAgentSession, resumeAgentSession, resetDeferralCounter, writeAskResponse } from './agent-manager';
import { getAllAgentsUsage, getAllActivity } from './usage';
import { startServer, stopServer } from './server';
import { startDaemon, stopDaemon, isDaemonRunning, discoverChatId } from './channels/telegram';
import { cronScheduler } from './channels/cron';
import { mcpRegistry } from './mcp-registry';
import { createAgent } from './create-agent';
import { search as vectorSearch } from './vector-search';
import { isLoginItemEnabled, toggleLoginItem } from './install';
import { checkForUpdates, downloadUpdate, quitAndInstall } from './updater';
import { ensureAvatarAssets, getAmbientVideoPath } from './avatar-downloader';
import { saveUserPhoto, generateMirrorAvatar, isMirrorSetupComplete, hasMirrorSourcePhoto } from './jobs/generate-mirror-avatar';
import type { MirrorAvatarProgress } from './jobs/generate-mirror-avatar';
import { parseArtifacts } from './artifact-parser';
import { loadCachedOpening, generateOpening, cacheNextOpening, getStaticFallback } from './opening';
import { getActiveBundleVersion, checkForBundleUpdate, getPendingBundleInfo, clearHotBundle } from './bundle-updater';
import type { HotBundlePaths } from './bundle-updater';
import { createLogger, setLogForwarder, getLogBuffer } from './logger';
import { switchboard, type Envelope } from './channels/switchboard';
import { drainAgentQueue, drainAllAgentQueues } from './queue';
import { buildTopology, handleToggleConnection } from './system-topology';
import type { TrayState } from './icon';

const log = createLogger('ipc');

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

export interface SwitchAgentResult {
  agentName: string;
  agentDisplayName: string;
  customSetup: string | null;
}

export interface IpcContext {
  mainWindow: BrowserWindow | null;
  currentSession: Session | null;
  systemPrompt: string | null;
  currentAgentName: string | null;
  pendingAskId: string | null;
  pendingAskDestination: string | null;
  pendingBundleVersion: string | null;
  readonly hotBundle: HotBundlePaths | null;
  readonly isMenuBarMode: boolean;
  // Functions from app.ts
  switchAgent: (name: string) => Promise<SwitchAgentResult>;
  rebuildTrayMenu: () => void;
  updateTrayState: (state: TrayState) => void;
  isKeepAwakeActive: () => boolean;
  toggleKeepAwake: () => void;
  resetJournalNudgeTimer: () => void;
}

// ---------------------------------------------------------------------------
// Handler registration
// ---------------------------------------------------------------------------

export function registerIpcHandlers(ctx: IpcContext): void {
  // NOTE: Do not capture getConfig() in a closure here - it would go stale
  // after agent switches or config:reload. Call getConfig() inside each handler.

  ipcMain.handle('config:reload', () => {
    reloadConfig();
  });

  // -- Logs --

  ipcMain.handle('logs:getBuffer', () => {
    return getLogBuffer();
  });

  // Forward live log entries to renderer
  setLogForwarder((entry) => {
    if (ctx.mainWindow && !ctx.mainWindow.isDestroyed()) {
      ctx.mainWindow.webContents.send('logs:entry', entry);
    }
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
      keepAwakeActive: ctx.isKeepAwakeActive(),
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
      bundleVersion: ctx.hotBundle?.version ?? null,
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
    'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'WINDOW_WIDTH', 'WINDOW_HEIGHT',
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

  // -- Usage & Activity --

  ipcMain.handle('usage:all', (_event, days?: number) => {
    return getAllAgentsUsage(days);
  });

  ipcMain.handle('activity:all', (_event, days?: number, limit?: number) => {
    return getAllActivity(days, limit);
  });

  ipcMain.handle('window:toggleFullscreen', () => {
    if (ctx.mainWindow) {
      ctx.mainWindow.setFullScreen(!ctx.mainWindow.isFullScreen());
    }
  });

  ipcMain.handle('window:toggleAlwaysOnTop', () => {
    if (ctx.mainWindow) {
      ctx.mainWindow.setAlwaysOnTop(!ctx.mainWindow.isAlwaysOnTop());
    }
  });

  ipcMain.handle('window:minimize', () => {
    if (ctx.mainWindow) ctx.mainWindow.minimize();
  });

  ipcMain.handle('window:close', () => {
    if (ctx.mainWindow) {
      if (ctx.isMenuBarMode) {
        ctx.mainWindow.hide();
      } else {
        ctx.mainWindow.close();
      }
    }
  });

  // -- Opening line --

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
      if (!ctx.systemPrompt) ctx.systemPrompt = loadSystemPrompt();
      if (ctx.systemPrompt) {
        cacheNextOpening(ctx.systemPrompt, ctx.currentSession?.cliSessionId ?? undefined);
      }
      return cached.text;
    }

    // 2. Ensure system prompt is loaded so we can generate dynamically
    if (!ctx.systemPrompt) {
      ctx.systemPrompt = loadSystemPrompt();
    }

    // 3. Generate dynamically
    if (ctx.systemPrompt) {
      try {
        const result = await generateOpening(
          ctx.systemPrompt,
          ctx.currentSession?.cliSessionId ?? undefined,
        );
        // Cache next opening in background for next launch
        cacheNextOpening(ctx.systemPrompt, ctx.currentSession?.cliSessionId ?? undefined);
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
      // Find npm - check common paths since Electron has limited PATH
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
          // Continue anyway - the Python script will give instructions
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

  // -- Bundle updater --

  ipcMain.handle('bundle:getStatus', () => {
    return {
      activeVersion: getActiveBundleVersion(),
      hotBundleActive: !!ctx.hotBundle,
      hotBundleVersion: ctx.hotBundle?.version ?? null,
      pending: getPendingBundleInfo(),
    };
  });

  ipcMain.handle('bundle:checkNow', async () => {
    const newVersion = await checkForBundleUpdate((percent) => {
      ctx.mainWindow?.webContents.send('bundle:downloadProgress', percent);
    });
    if (newVersion) {
      ctx.pendingBundleVersion = newVersion;
      ctx.rebuildTrayMenu();
    }
    return newVersion;
  });

  ipcMain.handle('bundle:clear', () => {
    clearHotBundle();
  });

  // -- Restart for update --

  ipcMain.handle('app:restartForUpdate', () => {
    app.relaunch();
    app.exit();
  });

  // -- Inference --

  // Register desktop GUI handler with the switchboard.
  // This handler receives response envelopes from agents (e.g. cross-agent
  // messages that need to be displayed in the desktop GUI).
  {
    const agentName = getConfig().AGENT_NAME;
    switchboard.register(`desktop:${agentName}`, async (envelope: Envelope) => {
      if (!ctx.mainWindow) return;
      // Display cross-agent or system messages in the GUI
      ctx.mainWindow.webContents.send('inference:done', envelope.text);
    });
  }

  ipcMain.handle('inference:send', (_event, text: string) => {
    if (!ctx.mainWindow) {
      log.warn('inference:send called but mainWindow is null');
      return;
    }

    // Mark user active and reset journal nudge timer
    setActive();
    ctx.resetJournalNudgeTimer();

    try {
      // Ensure session exists
      if (!ctx.currentSession) {
        ctx.currentSession = new Session();
        ctx.currentSession.start();
      }

      // Load system prompt once per session
      if (!ctx.systemPrompt) {
        ctx.systemPrompt = loadSystemPrompt();
      }

      // Record user turn
      ctx.currentSession.addTurn('will', text);

      // Detect mood shift
      if (detectMoodShift(text)) {
        ctx.currentSession.updateMood('heavy');
      }

      // Detect away intent (e.g. "goodnight", "heading out")
      const awayIntent = detectAwayIntent(text);
      if (awayIntent) {
        setAway(awayIntent);
        ctx.updateTrayState('away');
        ctx.mainWindow.webContents.send('status:changed', 'away');
        log.info(`Away intent detected: "${awayIntent}"`);
      }

      // Record the message through the switchboard for logging/observability.
      // Desktop inference is handled inline below (not routed through the
      // switchboard's handler delivery) because the GUI has deeply integrated
      // streaming display (TTS, artifacts, session management) that cannot
      // be decoupled without breaking the user experience.
      const agentName = ctx.currentAgentName || getConfig().AGENT_NAME;
      switchboard.record(switchboard.createEnvelope(
        `desktop:${agentName}`,
        `agent:${agentName}`,
        text,
        {
          type: 'user',
          priority: 'normal',
          replyTo: `desktop:${agentName}`,
          metadata: { source: 'desktop-gui' },
        },
      ));

      // Stream inference (existing logic - unchanged)
      const emitter = streamInference(
        text,
        ctx.systemPrompt,
        ctx.currentSession.cliSessionId,
      );

      let fullText = '';

      emitter.on('event', (evt: InferenceEvent) => {
        if (!ctx.mainWindow) return;

        switch (evt.type) {
          case 'TextDelta':
            ctx.mainWindow.webContents.send('inference:textDelta', evt.text);
            break;

          case 'SentenceReady': {
            const ttsActive = getConfig().TTS_BACKEND !== 'off' && !isMuted();
            // Tell renderer about the sentence boundary + whether to wait for audio
            ctx.mainWindow.webContents.send('inference:sentenceReady', evt.sentence, evt.index, ttsActive);
            if (ttsActive) {
              // Capture TTS generation so we can discard results after an agent switch
              const gen = ttsGeneration();
              synthesise(evt.sentence).then((audioPath) => {
                if (audioPath && gen === ttsGeneration()) {
                  enqueueAudio(audioPath, evt.index);
                } else if (audioPath) {
                  // Stale - agent switched during synthesis; clean up temp file
                  try { fs.unlinkSync(audioPath); } catch { /* best-effort */ }
                }
              }).catch((e) => { log.warn(`[tts] synthesise error: ${e}`); });
            }
            break;
          }

          case 'ToolUse':
            ctx.mainWindow.webContents.send('inference:toolUse', evt.name);
            break;

          case 'Compacting':
            ctx.mainWindow.webContents.send('inference:compacting');
            break;

          case 'StreamDone':
            fullText = evt.fullText;
            // Store CLI session ID after first inference
            if (ctx.currentSession && !ctx.currentSession.cliSessionId) {
              ctx.currentSession.setCliSessionId(evt.sessionId);
            } else if (ctx.currentSession && evt.sessionId !== ctx.currentSession.cliSessionId) {
              ctx.currentSession.setCliSessionId(evt.sessionId);
            }
            // Record agent turn (full text including artifact blocks for history)
            if (ctx.currentSession && fullText) {
              ctx.currentSession.addTurn('agent', fullText);
            }

            // Parse inline artifacts from response
            const { text: cleanedText, artifacts } = parseArtifacts(fullText);
            if (artifacts.length > 0) {
              for (const art of artifacts) {
                ctx.mainWindow.webContents.send('inference:artifact', art);
              }
              // Send cleaned text (artifact blocks replaced with placeholders)
              ctx.mainWindow.webContents.send('inference:done', cleanedText);
            } else {
              ctx.mainWindow.webContents.send('inference:done', fullText);
            }
            // Cache an opening for next boot if we don't have one yet
            // (proves the CLI is working, so dynamic generation will succeed)
            if (ctx.systemPrompt) {
              const cachePath = getConfig().OPENING_CACHE_FILE;
              if (cachePath && !fs.existsSync(cachePath)) {
                cacheNextOpening(ctx.systemPrompt, ctx.currentSession?.cliSessionId ?? undefined);
              }
            }
            // Prefetch context for the next message during idle
            setImmediate(() => prefetchContext());
            break;

          case 'StreamError':
            ctx.mainWindow.webContents.send('inference:error', evt.message);
            break;
        }
      });
    } catch (err) {
      log.error('[inference:send] failed to start inference:', err);
      ctx.mainWindow.webContents.send('inference:error', `Inference failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  ipcMain.handle('inference:stop', () => {
    stopInference();
  });

  // -- Status --

  ipcMain.handle('status:get', () => {
    return getStatus();
  });

  ipcMain.handle('status:set', (_event, status: 'active' | 'away', reason?: string) => {
    if (status === 'active') {
      setActive();
      ctx.updateTrayState('active');
    } else {
      setAway(reason || 'manual');
      ctx.updateTrayState('away');
    }
    ctx.mainWindow?.webContents.send('status:changed', status);
  });

  // -- Agent switching (extended) --

  ipcMain.handle('agent:switch', async (_event, name: string) => {
    return ctx.switchAgent(name);
  });

  // -- Mirror setup --

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
      if (ctx.mainWindow) {
        ctx.mainWindow.webContents.send('mirror:avatarProgress', progress);
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
      shell.openExternal(url);
    }
  });

  ipcMain.handle('mirror:downloadAssets', async () => {
    const c = getConfig();
    await ensureAvatarAssets(c.AGENT_NAME, ctx.mainWindow);
  });

  // -- Cron (in-process scheduler via switchboard) --

  ipcMain.handle('cron:schedule', () => {
    return cronScheduler.getSchedule();
  });

  ipcMain.handle('cron:runNow', (_event, agentName: string, jobName: string) => {
    return cronScheduler.runNow(agentName, jobName);
  });

  ipcMain.handle('cron:reset', (_event, agentName: string, jobName: string) => {
    cronScheduler.resetJob(agentName, jobName);
  });

  ipcMain.handle('cron:schedulerStatus', () => {
    return {
      schedule: cronScheduler.getSchedule(),
    };
  });

  // -- MCP Registry --

  ipcMain.handle('mcp:list', () => {
    return mcpRegistry.getRegistry();
  });

  ipcMain.handle('mcp:forAgent', (_event, agentName: string) => {
    return mcpRegistry.getForAgent(agentName);
  });

  ipcMain.handle('mcp:activate', (_event, agentName: string, serverName: string) => {
    mcpRegistry.activateForAgent(agentName, serverName);
  });

  ipcMain.handle('mcp:deactivate', (_event, agentName: string, serverName: string) => {
    mcpRegistry.deactivateForAgent(agentName, serverName);
  });

  // -- Keep Awake --

  ipcMain.handle('keepAwake:toggle', () => {
    ctx.toggleKeepAwake();
    return ctx.isKeepAwakeActive();
  });

  ipcMain.handle('keepAwake:isActive', () => {
    return ctx.isKeepAwakeActive();
  });

  // -- Voice agent --

  ipcMain.handle('voice-agent:start', async () => {
    const { startVoiceAgent } = await import('./voice-agent');
    return startVoiceAgent();
  });

  ipcMain.handle('voice-agent:stop', async () => {
    const { stopVoiceAgent } = await import('./voice-agent');
    stopVoiceAgent();
  });

  ipcMain.handle('voice-agent:sendText', async (_event, text: string) => {
    const { sendText } = await import('./voice-agent');
    await sendText(text);
  });

  ipcMain.handle('voice-agent:status', async () => {
    const { getVoiceAgentStatus } = await import('./voice-agent');
    return getVoiceAgentStatus();
  });

  ipcMain.handle('voice-agent:setMic', async (_event, muted: boolean) => {
    const { setMicMuted } = await import('./voice-agent');
    setMicMuted(muted);
  });

  ipcMain.handle('voice-agent:setAudio', async (_event, enabled: boolean) => {
    const { setAudioOutputEnabled } = await import('./voice-agent');
    setAudioOutputEnabled(enabled);
  });

  // -- Telegram daemon --

  ipcMain.handle('telegram:startDaemon', () => {
    return startDaemon();
  });

  ipcMain.handle('telegram:stopDaemon', () => {
    stopDaemon();
  });

  ipcMain.handle('telegram:isRunning', () => {
    return isDaemonRunning();
  });

  ipcMain.handle('telegram:discoverChatId', async (_event, botToken: string, agentName?: string) => {
    const result = await discoverChatId(botToken);
    if (result) {
      const c = getConfig();
      const targetAgent = agentName || c.AGENT_NAME;
      saveAgentConfig(targetAgent, { TELEGRAM_CHAT_ID: result.chatId });
      if (targetAgent === c.AGENT_NAME) {
        (c as unknown as Record<string, unknown>).TELEGRAM_CHAT_ID = result.chatId;
      }
    }
    return result;
  });

  ipcMain.handle('telegram:saveAgentBotToken', async (_event, agentName: string, botToken: string) => {
    saveAgentConfig(agentName, { TELEGRAM_BOT_TOKEN: botToken });
    const c = getConfig();
    if (agentName === c.AGENT_NAME) {
      (c as unknown as Record<string, unknown>).TELEGRAM_BOT_TOKEN = botToken;
    }
  });

  ipcMain.handle('telegram:setBotPhoto', async (_event, agentName: string, botToken: string) => {
    const { getReferenceImages } = await import('./jobs/generate-avatar');
    const { setBotProfilePhoto } = await import('./channels/telegram');
    const refs = getReferenceImages(agentName);
    if (refs.length === 0) return false;
    return setBotProfilePhoto(refs[0], botToken);
  });

  ipcMain.handle('telegram:getAgentConfig', async (_event, agentName: string) => {
    const c = getConfig();
    const original = c.AGENT_NAME;
    c.reloadForAgent(agentName);
    const result = {
      botToken: c.TELEGRAM_BOT_TOKEN ? '***' : '',
      chatId: c.TELEGRAM_CHAT_ID,
    };
    c.reloadForAgent(original);
    return result;
  });

  // -- Server --

  ipcMain.handle('server:start', (_event, port?: number) => {
    startServer(port);
  });

  ipcMain.handle('server:stop', async () => {
    await stopServer();
  });

  // -- Vector search --

  ipcMain.handle('memory:search', async (_event, query: string, n?: number) => {
    return vectorSearch(query, n);
  });

  // -- Avatar video --

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

  // -- Intro audio --

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

  // -- GitHub auth --

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

  // -- Login item --

  ipcMain.handle('install:isEnabled', () => {
    return isLoginItemEnabled();
  });

  ipcMain.handle('install:toggle', (_event, enabled: boolean) => {
    toggleLoginItem(enabled);
  });

  // -- Auto-updater --

  ipcMain.handle('updater:check', () => {
    checkForUpdates();
  });

  ipcMain.handle('updater:download', () => {
    downloadUpdate();
  });

  ipcMain.handle('updater:quitAndInstall', () => {
    quitAndInstall();
  });

  // -- Agent deferral --

  ipcMain.handle('deferral:complete', async (_event, data: { target: string; context: string; user_question: string }) => {
    if (!/^[a-zA-Z0-9_-]+$/.test(data.target)) throw new Error('Invalid agent name');
    try {
      // Suspend current agent's session
      if (ctx.currentSession && ctx.currentSession.cliSessionId) {
        suspendAgentSession(ctx.currentAgentName!, ctx.currentSession.cliSessionId, ctx.currentSession.turnHistory);
      }

      // Stop current inference and audio before switching
      stopInference();
      clearAudioQueue();

      // Switch to target agent
      const config = getConfig();
      config.reloadForAgent(data.target);
      initDb();
      resetMcpConfig();
      ctx.currentAgentName = data.target;
      setLastActiveAgent(data.target);

      // Resume or create new session for target agent
      const resumed = resumeAgentSession(data.target);
      ctx.currentSession = new Session();
      ctx.currentSession.start();
      if (resumed) {
        ctx.currentSession.setCliSessionId(resumed.cliSessionId);
        ctx.currentSession.turnHistory = resumed.turnHistory as typeof ctx.currentSession.turnHistory;
      }
      ctx.systemPrompt = null; // Force reload for new agent

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

  // -- Agent message queues --

  ipcMain.handle('queue:drainAgent', (_event, agentName: string) => {
    // Validate agent name to prevent path traversal
    if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) return [];
    return drainAgentQueue(agentName);
  });

  ipcMain.handle('queue:drainAll', () => {
    return drainAllAgentQueues();
  });

  // -- Ask-user (MCP ask_user -> GUI dialog) --

  ipcMain.handle('ask:respond', (_event, requestId: string, response: string | boolean | null) => {
    // If a destination was set (secure_input), route the value before writing the response
    let destinationFailed = false;
    if (ctx.pendingAskDestination && typeof response === 'string' && response) {
      const dest = ctx.pendingAskDestination;
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
    ctx.pendingAskId = null;
    ctx.pendingAskDestination = null;
  });

  // -- Artefacts --

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

  // ---------------------------------------------------------------------------
  // System map topology
  // ---------------------------------------------------------------------------

  ipcMain.handle('system:getTopology', () => {
    return buildTopology();
  });

  ipcMain.handle('system:toggleConnection', (_, agentName: string, serverName: string, enabled: boolean) => {
    return handleToggleConnection(agentName, serverName, enabled);
  });
}
