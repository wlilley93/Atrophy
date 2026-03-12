/**
 * Telegram polling daemon - single process, sequential agent dispatch.
 * Port of channels/telegram_daemon.py.
 *
 * Polls the shared Telegram bot for incoming messages. Routes each message
 * via the router (explicit match -> routing agent), then dispatches to target
 * agent(s) one at a time. Sequential dispatch eliminates race conditions.
 *
 * Can run as:
 *   - Single poll (for launchd interval jobs)
 *   - Continuous loop (KeepAlive daemon)
 *   - Managed from within the Electron main process
 */

import * as fs from 'fs';
import * as path from 'path';
import { spawnSync } from 'child_process';
import { getConfig, USER_DATA, BUNDLE_ROOT } from './config';
import { sendMessage, _post, setLastUpdateId } from './telegram';
import { routeMessage, RoutingDecision } from './router';
import { discoverAgents, getAgentState, setAgentState } from './agent-manager';
import { streamInference, InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import * as memory from './memory';
import { createLogger } from './logger';

const log = createLogger('telegram-daemon');

// ---------------------------------------------------------------------------
// State persistence
// ---------------------------------------------------------------------------

const STATE_FILE = path.join(USER_DATA, '.telegram_daemon_state.json');

function loadLastUpdateId(): number {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
      return state.last_update_id || 0;
    }
  } catch { /* default */ }
  return 0;
}

function saveLastUpdateId(updateId: number): void {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify({ last_update_id: updateId }) + '\n');
}

// ---------------------------------------------------------------------------
// Instance locking
// ---------------------------------------------------------------------------

const LOCK_FILE = path.join(USER_DATA, '.telegram_daemon.lock');

let _lockFd: number | null = null;

/**
 * Acquire an exclusive daemon lock using file-level locking.
 *
 * Opens the lock file with O_EXLOCK | O_NONBLOCK on macOS to get an
 * exclusive, non-blocking lock - equivalent to Python's fcntl.flock
 * with LOCK_EX | LOCK_NB. Falls back to a simple pid-check strategy
 * on platforms that do not support O_EXLOCK.
 *
 * Returns true if the lock was acquired, false if another instance holds it.
 */
export function acquireLock(): boolean {
  fs.mkdirSync(path.dirname(LOCK_FILE), { recursive: true });

  // macOS supports O_EXLOCK (0x20) for advisory exclusive lock on open
  const O_EXLOCK = 0x20;
  const O_NONBLOCK = 0x4000; // fs.constants.O_NONBLOCK is not always exposed

  try {
    _lockFd = fs.openSync(
      LOCK_FILE,
      fs.constants.O_WRONLY | fs.constants.O_CREAT | O_EXLOCK | O_NONBLOCK,
      0o644,
    );
  } catch (err: unknown) {
    // EAGAIN / EWOULDBLOCK means another process holds the lock
    const code = (err as NodeJS.ErrnoException).code;
    if (code === 'EAGAIN' || code === 'EWOULDBLOCK') {
      return false;
    }
    // If O_EXLOCK is not supported (Linux), fall back to pid-check
    return acquireLockFallback();
  }

  // Write our pid so operators can inspect who holds the lock
  const pidBuf = Buffer.from(String(process.pid) + '\n');
  fs.writeSync(_lockFd, pidBuf, 0, pidBuf.length, 0);
  fs.ftruncateSync(_lockFd, pidBuf.length);
  return true;
}

/**
 * Fallback lock strategy for systems without O_EXLOCK.
 *
 * Reads the pid from the lock file. If no process with that pid exists,
 * the lock is stale and we reclaim it. This is not race-free but is
 * acceptable for a single-user daemon.
 */
function acquireLockFallback(): boolean {
  if (fs.existsSync(LOCK_FILE)) {
    try {
      const raw = fs.readFileSync(LOCK_FILE, 'utf-8').trim();
      const pid = parseInt(raw, 10);
      if (pid && isProcessAlive(pid)) {
        return false;
      }
    } catch { /* stale or corrupt - reclaim */ }
  }

  fs.writeFileSync(LOCK_FILE, String(process.pid) + '\n');
  // Open + hold the fd so the file stays referenced for our lifetime
  _lockFd = fs.openSync(LOCK_FILE, fs.constants.O_RDONLY);
  return true;
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/**
 * Release the daemon lock. Safe to call even if no lock is held.
 */
export function releaseLock(): void {
  if (_lockFd !== null) {
    try { fs.closeSync(_lockFd); } catch { /* ignore */ }
    _lockFd = null;
  }
  try { fs.unlinkSync(LOCK_FILE); } catch { /* may already be gone */ }
}

// ---------------------------------------------------------------------------
// launchd install / uninstall
// ---------------------------------------------------------------------------

const PLIST_LABEL = 'com.atrophiedmind.telegram-daemon';
const LAUNCH_AGENTS = path.join(process.env.HOME || '/tmp', 'Library', 'LaunchAgents');
const PLIST_PATH = path.join(LAUNCH_AGENTS, `${PLIST_LABEL}.plist`);

/**
 * Build an XML plist string for the telegram daemon launchd agent.
 *
 * Uses the same XML serialisation style as cron.ts - hand-built rather
 * than pulling in a plist library.
 */
function buildDaemonPlist(electronBin: string, loopFlag: boolean): string {
  const logDir = path.join(USER_DATA, 'logs');
  fs.mkdirSync(logDir, { recursive: true });

  const args = [electronBin];
  if (loopFlag) args.push('--telegram-daemon');

  const envPath = process.env.PATH || '/usr/local/bin:/usr/bin:/bin';

  const lines: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
    '<plist version="1.0">',
    '<dict>',
    '\t<key>Label</key>',
    `\t<string>${PLIST_LABEL}</string>`,
    '\t<key>ProgramArguments</key>',
    '\t<array>',
    ...args.map((a) => `\t\t<string>${escapeXml(a)}</string>`),
    '\t</array>',
    '\t<key>RunAtLoad</key>',
    '\t<true/>',
    '\t<key>KeepAlive</key>',
    '\t<true/>',
    '\t<key>StandardOutPath</key>',
    `\t<string>${escapeXml(path.join(logDir, 'telegram_daemon.log'))}</string>`,
    '\t<key>StandardErrorPath</key>',
    `\t<string>${escapeXml(path.join(logDir, 'telegram_daemon.err'))}</string>`,
    '\t<key>EnvironmentVariables</key>',
    '\t<dict>',
    '\t\t<key>PATH</key>',
    `\t\t<string>${escapeXml(envPath)}</string>`,
    '\t</dict>',
    '</dict>',
    '</plist>',
  ];

  return lines.join('\n');
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Install the telegram daemon as a launchd agent.
 *
 * @param electronBin - Path to the Electron binary or app entry point that
 *   accepts a --telegram-daemon flag to start continuous polling.
 */
export function installLaunchd(electronBin: string): void {
  fs.mkdirSync(LAUNCH_AGENTS, { recursive: true });

  // Unload first if already installed
  if (fs.existsSync(PLIST_PATH)) {
    spawnSync('launchctl', ['unload', PLIST_PATH], { stdio: 'pipe' });
  }

  fs.writeFileSync(PLIST_PATH, buildDaemonPlist(electronBin, true));
  spawnSync('launchctl', ['load', PLIST_PATH], { stdio: 'pipe' });
  log.info(`Installed launchd agent: ${PLIST_PATH}`);
}

/**
 * Uninstall the telegram daemon launchd agent.
 */
export function uninstallLaunchd(): void {
  if (fs.existsSync(PLIST_PATH)) {
    spawnSync('launchctl', ['unload', PLIST_PATH], { stdio: 'pipe' });
    fs.unlinkSync(PLIST_PATH);
    log.info(`Uninstalled launchd agent: ${PLIST_PATH}`);
  } else {
    log.info('launchd agent not installed');
  }
}

/**
 * Check whether the daemon is installed as a launchd agent.
 */
export function isLaunchdInstalled(): boolean {
  return fs.existsSync(PLIST_PATH);
}

// ---------------------------------------------------------------------------
// Agent dispatch
// ---------------------------------------------------------------------------

async function dispatchToAgent(agentName: string, text: string): Promise<string | null> {
  const config = getConfig();
  const originalAgent = config.AGENT_NAME;

  try {
    // Temporarily switch config for this agent - capture needed values
    // synchronously, then restore before the async inference call to
    // minimize the window where global config is mutated.
    config.reloadForAgent(agentName);
    memory.initDb();

    const system = loadSystemPrompt();
    const cliSessionId = memory.getLastCliSessionId();

    // Restore config now - inference reads config internally but only
    // at spawn time, and we've already captured what we need.
    config.reloadForAgent(originalAgent);
    memory.initDb();

    const prompt = `[Telegram message from Will]\n\n${text}`;
    let fullText = '';
    const toolsUsed: string[] = [];

    await new Promise<void>((resolve) => {
      const emitter = streamInference(prompt, system, cliSessionId);

      emitter.on('event', (evt: InferenceEvent) => {
        switch (evt.type) {
          case 'ToolUse':
            toolsUsed.push(evt.name);
            log.debug(`[${agentName}] tool -> ${evt.name}`);
            break;
          case 'StreamDone':
            fullText = evt.fullText;
            resolve();
            break;
          case 'StreamError':
            log.error(`[${agentName}] inference error: ${evt.message}`);
            resolve();
            break;
        }
      });
    });

    if (toolsUsed.length) {
      log.debug(`[${agentName}] used tools: ${toolsUsed.join(', ')}`);
    }

    return fullText.trim() || null;
  } catch (e) {
    log.error(`[${agentName}] dispatch failed: ${e}`);
    // Always restore original agent on failure
    config.reloadForAgent(originalAgent);
    memory.initDb();
    return null;
  }
}

function sendAgentResponse(agentName: string, text: string): void {
  // Load agent manifest for emoji prefix
  for (const base of [
    path.join(USER_DATA, 'agents', agentName),
    path.join(BUNDLE_ROOT, 'agents', agentName),
  ]) {
    const mpath = path.join(base, 'data', 'agent.json');
    if (fs.existsSync(mpath)) {
      try {
        const manifest = JSON.parse(fs.readFileSync(mpath, 'utf-8'));
        const emoji = manifest.telegram_emoji || '';
        const display = manifest.display_name || agentName.charAt(0).toUpperCase() + agentName.slice(1);
        if (emoji) {
          text = `${emoji} *${display}*\n\n${text}`;
        }
        break;
      } catch { /* use plain text */ }
    }
  }

  sendMessage(text, '', false);
}

// ---------------------------------------------------------------------------
// Utility commands
// ---------------------------------------------------------------------------

function handleStatusCommand(): void {
  const lines = ['*Active agents:*\n'];

  for (const agent of discoverAgents()) {
    const name = agent.name;
    const state = getAgentState(name);

    // Load emoji from manifest
    let emoji = '';
    for (const base of [
      path.join(USER_DATA, 'agents', name),
      path.join(BUNDLE_ROOT, 'agents', name),
    ]) {
      const mpath = path.join(base, 'data', 'agent.json');
      if (fs.existsSync(mpath)) {
        try {
          const manifest = JSON.parse(fs.readFileSync(mpath, 'utf-8'));
          emoji = manifest.telegram_emoji || '';
        } catch { /* skip */ }
        break;
      }
    }

    let status = 'active';
    if (!state.enabled) status = 'disabled';
    else if (state.muted) status = 'muted';

    const prefix = emoji ? `${emoji} ` : '';
    lines.push(`${prefix}*${agent.display_name}* (\`/${name}\`) - ${status}`);
  }

  sendMessage(lines.join('\n'), '', false);
}

function handleMuteCommand(text: string): void {
  const parts = text.trim().split(/\s+/);
  const agents = discoverAgents();

  let targetName: string;
  if (parts.length < 2) {
    if (!agents.length) {
      sendMessage('No agents available.', '', false);
      return;
    }
    targetName = agents[0].name;
  } else {
    targetName = parts[1].toLowerCase().replace(/^\//, '');
  }

  const found = agents.find(
    (a) => a.name === targetName || a.display_name.toLowerCase() === targetName,
  );
  if (!found) {
    sendMessage(`Unknown agent: \`${targetName}\``, '', false);
    return;
  }

  const state = getAgentState(found.name);
  const newMuted = !state.muted;
  setAgentState(found.name, { muted: newMuted });

  const verb = newMuted ? 'muted' : 'unmuted';
  sendMessage(`*${found.display_name}* ${verb}.`, '', false);
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

let _lastUpdateId = 0;

async function pollOnce(): Promise<void> {
  const config = getConfig();
  if (!config.TELEGRAM_BOT_TOKEN) {
    log.warn('TELEGRAM_BOT_TOKEN not configured');
    return;
  }

  const result = await _post('getUpdates', {
    offset: _lastUpdateId + 1,
    timeout: 30,
    allowed_updates: ['message'],
  }) as { update_id: number; message?: {
    text?: string;
    from?: { id: number };
    chat?: { id: number };
  } }[] | null;

  if (!result) return;

  for (const update of result) {
    _lastUpdateId = Math.max(_lastUpdateId, update.update_id);

    const msg = update.message;
    if (!msg?.text) continue;

    const senderId = String(msg.from?.id || '');
    const chatId = String(msg.chat?.id || '');
    if (config.TELEGRAM_CHAT_ID && senderId !== config.TELEGRAM_CHAT_ID && chatId !== config.TELEGRAM_CHAT_ID) {
      continue;
    }

    const text = msg.text.trim();
    if (!text) continue;

    log.info(`Received: ${text.slice(0, 80)}`);

    // Utility commands
    if (text.toLowerCase() === '/status') {
      handleStatusCommand();
      continue;
    }
    if (text.toLowerCase().startsWith('/mute')) {
      handleMuteCommand(text);
      continue;
    }

    // Route the message
    const decision = await routeMessage(text);
    log.debug(`Routed: agents=${decision.agents.join(',')} tier=${decision.tier}`);

    if (!decision.agents.length) {
      log.warn('No agents available to handle message');
      continue;
    }

    // Dispatch to each agent sequentially
    for (const agentName of decision.agents) {
      log.info(`Dispatching to ${agentName}...`);
      const response = await dispatchToAgent(agentName, decision.text);
      if (response) {
        sendAgentResponse(agentName, response);
        log.info(`[${agentName}] responded (${response.length} chars)`);
      } else {
        log.debug(`[${agentName}] no response`);
      }
    }
  }

  saveLastUpdateId(_lastUpdateId);
}

// ---------------------------------------------------------------------------
// Daemon control
// ---------------------------------------------------------------------------

let _pollTimer: ReturnType<typeof setInterval> | null = null;
let _running = false;

/**
 * Start the polling daemon. Acquires an instance lock to prevent
 * duplicate processes. Returns false if another instance is already running.
 */
export function startDaemon(intervalMs = 10_000): boolean {
  if (_running) return true;

  if (!acquireLock()) {
    log.warn('Another instance is running - exiting');
    return false;
  }

  _running = true;
  _lastUpdateId = loadLastUpdateId();
  setLastUpdateId(_lastUpdateId);

  log.info(`Starting (last_update_id=${_lastUpdateId}, interval=${intervalMs}ms)`);

  // Initial poll
  pollOnce().catch((e) => log.error(`Poll error: ${e}`));

  // Recurring polls
  _pollTimer = setInterval(() => {
    pollOnce().catch((e) => log.error(`Poll error: ${e}`));
  }, intervalMs);

  return true;
}

/**
 * Stop the polling daemon and release the instance lock.
 */
export function stopDaemon(): void {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
  _running = false;
  releaseLock();
  log.info('Stopped');
}

export function isDaemonRunning(): boolean {
  return _running;
}
