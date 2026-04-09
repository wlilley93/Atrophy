/**
 * Boot sequence orchestrator.
 * Called from app.ts on app.whenReady(). Each phase is labeled and sequential.
 * This file replaces the 650+ line whenReady() callback.
 */

import { app, ipcMain } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { v4 as uuidv4 } from 'uuid';
import type { AppContext } from './app-context';
import { TimerManager } from './timers';
import { TrayManager } from './tray-manager';
import { createMainWindow, registerGlobalShortcuts } from './window-manager';
import { ensureUserData, getConfig, isValidAgentName, BUNDLE_ROOT, USER_DATA } from './config';
import { initDb, closeStaleOpenSessions, endSession, getLastCliSessionId, closeForPath } from './memory';
import { stopInference, resetMcpConfig, prefetchContext, invalidateContextCache, getTmuxPool } from './inference';
import { clearAudioQueue, synthesise, playAudio, waitForAudioIdle, setPlaybackCallbacks } from './tts';
import { Session } from './session';
import { loadSystemPrompt } from './context';
import { sendCronNotification } from './notify';
import { cronOutputEmitter } from './channels/telegram/daemon';
import { registerAudioHandlers } from './audio';
import { registerWakeWordHandlers, pauseWakeWord, resumeWakeWord } from './wake-word';
import {
  discoverAgents,
  getAgentDir,
  syncBundledPrompts,
  setLastActiveAgent,
  getLastActiveAgent,
} from './agent-manager';
import { startServer, startMeridianServer } from './server';
import { startDaemon, setMainWindowAccessor } from './channels/telegram';
import { startFederation } from './channels/federation';
import { cronScheduler } from './channels/cron';
import { mcpRegistry } from './mcp-registry';
import { wireAgent, markBootComplete } from './create-agent';
import { backupAgentData } from './backup';
import { ensureAvatarAssets, ensureAmbientVideo } from './avatar-downloader';
import { initAutoUpdater } from './updater';
import { getAppIcon } from './icon';
import { isAway } from './status';
import { switchboard } from './channels/switchboard';
import { registerIpcHandlers } from './ipc-handlers';
import { registerCallHandlers } from './call';
import { getCustomSetup } from './tray-manager';
import { createLogger } from './logger';
import type { SwitchAgentResult } from './app-context';

const log = createLogger('boot');

export async function boot(ctx: AppContext): Promise<void> {
  log.info('app.whenReady() fired');

  // Parse args
  const args = process.argv.slice(2);
  ctx.isMenuBarMode = args.includes('--app');
  const isServerMode = args.includes('--server');

  if (ctx.isMenuBarMode || isServerMode) {
    app.dock?.hide();
  } else {
    const appIcon = getAppIcon();
    app.dock?.setIcon(appIcon);
  }

  // -- Phase 1: Config + DB --
  log.info('ensureUserData + config + db init');
  ensureUserData();
  syncBundledPrompts();
  const config = getConfig();
  initDb();

  closeStaleSessionsForAllAgents();

  ctx.currentAgentName = config.AGENT_NAME;
  log.info(`v${config.VERSION} | agent: ${config.AGENT_NAME} | db: ${config.DB_PATH}`);

  // -- Phase 2: Wire managers --
  ctx.timers = new TimerManager(ctx);
  ctx.tray = new TrayManager(ctx);

  // Wire switchAgent into context (needs managers to exist)
  let switchInProgress = false;
  ctx.switchAgent = async (name: string): Promise<SwitchAgentResult> => {
    if (switchInProgress) throw new Error('Agent switch already in progress');
    switchInProgress = true;
    try {
      return await switchAgentImpl(ctx, name);
    } finally {
      switchInProgress = false;
    }
  };

  // -- Phase 3: IPC --
  log.info('registering IPC handlers');
  registerIpcHandlers(ctx as any); // AppContext is a superset of IpcContext
  registerAudioHandlers(() => ctx.mainWindow);
  registerWakeWordHandlers();
  registerCallHandlers(
    () => ctx.mainWindow,
    () => {
      if (!ctx.currentSession) {
        ctx.currentSession = new Session();
        ctx.currentSession.start();
        ctx.currentSession.inheritCliSessionId();
      }
      if (!ctx.systemPrompt) {
        ctx.systemPrompt = loadSystemPrompt();
      }
      return ctx.systemPrompt;
    },
    () => ctx.currentSession?.cliSessionId || null,
    (id: string) => { if (ctx.currentSession) ctx.currentSession.setCliSessionId(id); },
  );

  // TTS playback callbacks
  setPlaybackCallbacks({
    onStarted: (index) => {
      ctx.mainWindow?.webContents.send('tts:started', index);
      pauseWakeWord();
    },
    onDone: (index) => {
      ctx.mainWindow?.webContents.send('tts:done', index);
    },
    onQueueEmpty: () => {
      ctx.mainWindow?.webContents.send('tts:queueEmpty');
      resumeWakeWord();
    },
  });

  // Actual quit - called from tray menu or renderer
  ipcMain.handle('app:shutdown', () => {
    ctx.forceQuit = true;
    app.quit();
  });

  // -- Phase 4: Resume last active agent --
  const lastAgent = getLastActiveAgent();
  if (lastAgent && lastAgent !== config.AGENT_NAME) {
    config.reloadForAgent(lastAgent);
    initDb();
    ctx.currentAgentName = config.AGENT_NAME;
    log.info(`resumed agent: ${config.AGENT_NAME}`);
  }

  // -- Phase 5: Agent wiring --
  discoverAndWireAgents(ctx);

  // -- Phase 6: Services --
  const crashSafe = isCrashRateSafe();
  log.info(`crashSafe=${crashSafe}`);
  if (!crashSafe) {
    log.error('CRASH LOOP DETECTED - skipping cron scheduler and Telegram daemon');
  }

  startServices(ctx, crashSafe);

  // -- Phase 7: Timers --
  ctx.timers.startAll();

  // -- Phase 8: UI --
  if (isServerMode) {
    const portIdx = args.indexOf('--port');
    const port = portIdx !== -1 ? parseInt(args[portIdx + 1], 10) || 5000 : 5000;
    startServer(port);
    return;
  }

  registerGlobalShortcuts(ctx);

  if (ctx.isMenuBarMode) {
    ctx.tray.create();
    return;
  }

  // GUI mode
  log.info('creating main window');
  ctx.mainWindow = createMainWindow(ctx.hotBundle);
  log.info('main window created, loading renderer');

  ctx.timers.resetJournalNudge();

  if (ctx.mainWindow) {
    initAutoUpdater(ctx.mainWindow);
  }

  if (ctx.hotBundle) {
    log.info(`running on hot bundle v${ctx.hotBundle.version}`);
  }

  Promise.all([
    ensureAvatarAssets(config.AGENT_NAME, ctx.mainWindow),
    ensureAmbientVideo(ctx.mainWindow),
  ]).catch(() => { /* non-critical */ });

  ctx.tray.create();

  // -- Phase 9: Background warm-up --
  scheduleBackgroundWarmup();
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

function closeStaleSessionsForAllAgents(): void {
  const config = getConfig();
  const defaultAgent = config.AGENT_NAME;
  const allAgents = discoverAgents();
  for (const agent of allAgents) {
    try {
      config.reloadForAgent(agent.name);
      initDb();
      const staleClosed = closeStaleOpenSessions();
      if (staleClosed > 0) {
        log.info(`closed ${staleClosed} stale open session(s) for agent ${agent.name}`);
      }
    } catch (e) {
      log.warn(`failed to clean stale sessions for ${agent.name}: ${e}`);
    }
  }
  config.reloadForAgent(defaultAgent);
  initDb();
}

function discoverAndWireAgents(ctx: AppContext): void {
  // MCP registry
  try {
    mcpRegistry.discover();
    mcpRegistry.registerWithSwitchboard(switchboard);
    log.info(`MCP registry: ${mcpRegistry.getRegistry().length} server(s) discovered`);
  } catch (e) {
    log.warn(`MCP registry init failed (non-fatal): ${e}`);
  }

  // Wire all agents through switchboard
  const agents = discoverAgents();
  let wiredCount = 0;
  for (const agent of agents) {
    try {
      const manifestPath = path.join(getAgentDir(agent.name), 'data', 'agent.json');
      if (fs.existsSync(manifestPath)) {
        const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
        wireAgent(agent.name, manifest);
        wiredCount++;
      } else {
        log.warn(`manifest not found for "${agent.name}" at ${manifestPath}`);
      }
    } catch (e) {
      log.warn(`failed to wire agent "${agent.name}": ${e}`);
    }
  }
  log.info(`switchboard: ${wiredCount}/${agents.length} agent(s) wired`);
  markBootComplete();

  // Initialize tmux pool
  const config = getConfig();
  const pool = getTmuxPool();
  if (pool) {
    pool.ensureSession();
    const primaryAgents = agents.filter(a => {
      try {
        const mp = path.join(getAgentDir(a.name), 'data', 'agent.json');
        const m = JSON.parse(fs.readFileSync(mp, 'utf-8'));
        return m.channels?.desktop?.enabled || m.channels?.telegram?.enabled;
      } catch { return false; }
    });

    for (const agent of primaryAgents) {
      try {
        config.reloadForAgent(agent.name);
        initDb();
        const lastSession = getLastCliSessionId() || uuidv4();
        const mcpConfig = mcpRegistry.buildConfigForAgent(agent.name);

        pool.createWindow(agent.name, {
          sessionId: lastSession,
          claudeBin: config.CLAUDE_BIN,
          mcpConfigPath: mcpConfig,
        });

        setTimeout(() => {
          try { pool.pressEnter(agent.name); } catch (e) {
            log.warn(`[${agent.name}] tmux Enter failed: ${e}`);
          }
        }, 1000);
      } catch (e) {
        log.warn(`[${agent.name}] tmux window creation failed: ${e}`);
      }
    }

    const lastActive = getLastActiveAgent() || 'xan';
    config.reloadForAgent(lastActive);
    initDb();

    log.info(`tmux pool: ${pool.agentNames().length} agent(s) ready`);
    pool.startHealthCheck();
  } else {
    log.info('tmux not available - using one-shot spawn for inference');
  }
}

function startServices(ctx: AppContext, crashSafe: boolean): void {
  // Cron scheduler
  if (crashSafe) {
    try {
      cronScheduler.start();
      cronScheduler.registerWithSwitchboard();
      const schedule = cronScheduler.getSchedule();
      log.info(`cron scheduler: ${schedule.length} job(s) scheduled`);
    } catch (e) {
      log.warn(`cron scheduler start failed (non-fatal): ${e}`);
    }

    // Cron output notification
    cronOutputEmitter.on('output', async (data: { agentName: string; agentDisplayName: string; jobName: string; text: string }) => {
      if (isAway()) return;

      const jobLabel = data.jobName.charAt(0).toUpperCase() + data.jobName.slice(1);
      const played = await sendCronNotification(data.agentDisplayName, jobLabel, data.text);

      if (played) {
        log.info(`[cron-notify] playing TTS for ${data.agentName}.${data.jobName}`);
        try {
          await waitForAudioIdle();

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

  // Reconcile launchd jobs
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
        (err: Error | null, stdout: string, _stderr: string) => {
          if (err) {
            log.debug(`job reconciler: ${err.message}`);
          } else if (stdout.trim()) {
            log.info(`job reconciler:\n${stdout.trim()}`);
          }
        },
      );
    }
  } catch (e) {
    log.debug(`job reconciler failed (non-fatal): ${e}`);
  }

  // Telegram daemon
  if (crashSafe) {
    log.info('calling startDaemon()');
    const started = startDaemon();
    log.info(`startDaemon returned ${started}`);
    if (started) {
      log.info('Telegram daemon auto-started');
    } else {
      log.debug('Telegram daemon not started (no agents with credentials, or lock held)');
    }
  }

  setMainWindowAccessor(() => ctx.mainWindow);

  // Federation
  startFederation().catch((e) => log.error(`federation start failed: ${e}`));

  // Switchboard queue polling
  switchboard.startQueuePolling();

  // Meridian web handler
  if (!switchboard.hasHandler('meridian:web')) {
    switchboard.register('meridian:web', async () => {
      log.debug('meridian:web received envelope (send-only channel, ignored)');
    }, {
      type: 'channel',
      description: 'Meridian Eye web interface',
      capabilities: ['chat', 'query'],
    });
  }

  // Meridian bridge + Cloudflare tunnel
  const tunnelConfigPath = path.join(USER_DATA, 'services', 'cloudflared', 'config.yml');
  if (fs.existsSync(tunnelConfigPath)) {
    startMeridianServer(3847, '127.0.0.1');

    try {
      const { execFileSync, spawn: spawnTunnel } = require('child_process');
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
        log.warn(`failed to start Cloudflare Tunnel (non-fatal): ${e}`);
      }
    }
  }

  // Daily agent backup
  backupAgentData();

  // Voice agent
  import('./voice-agent').then(({ configureVoiceAgent }) => {
    configureVoiceAgent({
      getWindow: () => ctx.mainWindow,
      setCliSessionId: (id: string) => { if (ctx.currentSession) ctx.currentSession.setCliSessionId(id); },
    });
  });

  const config = getConfig();
  if (config.ELEVENLABS_API_KEY) {
    import('./voice-agent').then(({ provisionAgent }) => {
      provisionAgent(config.AGENT_NAME).catch(() => { /* non-critical */ });
    });
  }
}

function scheduleBackgroundWarmup(): void {
  setImmediate(() => prefetchContext());

  setTimeout(() => {
    import('./opening').then(({ precacheAllOpenings }) => {
      precacheAllOpenings();
    }).catch(() => { /* non-fatal */ });
  }, 10_000);

  setTimeout(() => {
    import('./kokoro').then(({ ensureKokoroReady }) => {
      ensureKokoroReady().catch(() => { /* non-fatal */ });
    }).catch(() => { /* non-fatal */ });
  }, 20_000);
}

// ---------------------------------------------------------------------------
// Agent switching
// ---------------------------------------------------------------------------

async function switchAgentImpl(ctx: AppContext, name: string): Promise<SwitchAgentResult> {
  if (!isValidAgentName(name)) throw new Error('Invalid agent name');
  const knownAgents = discoverAgents();
  if (!knownAgents.some(a => a.name === name)) {
    throw new Error(`Agent "${name}" not found`);
  }

  stopInference(ctx.currentAgentName ?? undefined);
  clearAudioQueue();

  const oldSession = ctx.currentSession;
  const oldPrompt = ctx.systemPrompt;
  const oldAgentName = ctx.currentAgentName;
  if (oldSession?.sessionId != null) {
    endSession(oldSession.sessionId, null, oldSession.mood);
    if (oldPrompt && oldSession.turnHistory.length >= 4) {
      const sid = oldSession.sessionId;
      const turnHistory = [...oldSession.turnHistory];
      setImmediate(() => {
        generateDeferredSummary(sid, turnHistory, oldPrompt, oldAgentName || '').catch(() => {});
      });
    }
  }
  ctx.currentSession = null;
  ctx.systemPrompt = null;

  const oldDbPath = getConfig().DB_PATH;
  setTimeout(() => {
    closeForPath(oldDbPath);
  }, 5000);

  getConfig().reloadForAgent(name);
  initDb();
  resetMcpConfig();
  invalidateContextCache();
  ctx.currentAgentName = name;
  setLastActiveAgent(name);
  ctx.tray.invalidateAgentCache();

  setImmediate(() => prefetchContext());

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
}

async function generateDeferredSummary(
  sessionId: number,
  turnHistory: { role: string; content: string; turnId: number }[],
  systemPrompt: string,
  oldAgentName: string,
): Promise<void> {
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
      const Database = (await import('better-sqlite3')).default;
      const dbPath = path.join(getAgentDir(oldAgentName), 'data', 'memory.db');
      const db = new Database(dbPath);
      try {
        db.prepare(
          'UPDATE sessions SET ended_at = CURRENT_TIMESTAMP, summary = ? WHERE id = ?',
        ).run(summary.trim(), sessionId);
        db.prepare(
          'INSERT INTO summaries (session_id, content) VALUES (?, ?)',
        ).run(sessionId, summary.trim());
        log.info(`[deferred-summary] written for ${oldAgentName} session ${sessionId}`);
      } finally {
        db.close();
      }
    }
  } catch (err) {
    log.warn(`[deferred-summary] failed for ${oldAgentName}: ${err}`);
  }
}

// ---------------------------------------------------------------------------
// Crash rate limiter
// ---------------------------------------------------------------------------

const CRASH_LOG_PATH = path.join(USER_DATA, 'crash-log.json');
const CRASH_WINDOW_MS = 10 * 60 * 1000;
const MAX_CRASHES_IN_WINDOW = 5;

function readCrashTimestamps(): number[] {
  try {
    if (!fs.existsSync(CRASH_LOG_PATH)) return [];
    const raw = JSON.parse(fs.readFileSync(CRASH_LOG_PATH, 'utf-8'));
    if (Array.isArray(raw) && raw.every((v) => typeof v === 'number')) return raw;
    fs.unlinkSync(CRASH_LOG_PATH);
    return [];
  } catch {
    try { fs.unlinkSync(CRASH_LOG_PATH); } catch { /* already gone */ }
    return [];
  }
}

export function recordCrash(): void {
  try {
    const cutoff = Date.now() - CRASH_WINDOW_MS;
    const timestamps = readCrashTimestamps().filter((t) => t > cutoff);
    timestamps.push(Date.now());
    fs.writeFileSync(CRASH_LOG_PATH, JSON.stringify(timestamps));
  } catch { /* best effort */ }
}

export function isCrashRateSafe(): boolean {
  const cutoff = Date.now() - CRASH_WINDOW_MS;
  const recent = readCrashTimestamps().filter((t) => t > cutoff);
  return recent.length < MAX_CRASHES_IN_WINDOW;
}
