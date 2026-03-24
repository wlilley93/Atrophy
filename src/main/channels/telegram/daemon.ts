/**
 * Telegram daemon - parallel per-agent pollers.
 *
 * Each agent has its own Telegram bot (own token + chat ID). On startup,
 * discovers all agents with telegram credentials and launches a poller
 * per agent. No group, no topics, no routing - each bot IS the agent.
 *
 * Messages flow through the central switchboard:
 *   Telegram poll -> Envelope -> switchboard -> agent router -> inference
 *   Response -> Envelope -> switchboard -> telegram handler -> Telegram API
 *
 * Can run as:
 *   - Continuous loop (KeepAlive daemon)
 *   - Managed from within the Electron main process
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { spawnSync } from 'child_process';
import { getConfig, USER_DATA, BUNDLE_ROOT } from '../../config';
import { setActive } from '../../status';
import { sendMessage, sendMessageGetId, editMessage, deleteMessage, post, downloadTelegramFile, setBotProfilePhoto, sendChatAction, sendDocument, sendPhoto } from './api';
import { buildStatusDisplay, formatElapsed, type StreamState, type ToolCallState } from './formatter';
import { discoverAgents, getAgentState } from '../../agent-manager';
import { streamInference, stopInference, resetMcpConfig, InferenceEvent } from '../../inference';
import { loadSystemPrompt } from '../../context';
import { getReferenceImages } from '../../jobs/generate-avatar';
import * as memory from '../../memory';
import { createLogger } from '../../logger';
import { switchboard, type Envelope } from '../switchboard';
import { AgentRouter, defaultConfigForAgent } from '../agent-router';
import { Session } from '../../session';

// ---------------------------------------------------------------------------
// Per-agent session persistence with idle rotation
// ---------------------------------------------------------------------------

const _agentSessions: Map<string, Session> = new Map();
const _agentLastActivity: Map<string, number> = new Map();

/** Idle gap (ms) after which a Telegram session is rotated and summarised. */
const SESSION_IDLE_THRESHOLD_MS = 30 * 60 * 1000; // 30 minutes

const log = createLogger('telegram-daemon');

/**
 * Get or create the persistent Session for an agent.
 * The Session tracks the CLI session ID so that every inference call
 * resumes the same conversation thread (compaction handles context limits).
 *
 * If the agent's session has been idle for more than SESSION_IDLE_THRESHOLD_MS,
 * the old session is ended (triggering summary generation) and a new one is
 * started. The CLI session ID carries over - it tracks Claude's conversation
 * context, which is independent of memory sessions.
 *
 * IMPORTANT: Does NOT inherit CLI session ID here. The caller must call
 * session.inheritCliSessionId() inside the config lock, after
 * config.reloadForAgent() + memory.initDb() have loaded the correct
 * agent's DB. This prevents cross-agent session contamination.
 */
function getAgentSession(agentName: string): Session {
  let session = _agentSessions.get(agentName);
  const now = Date.now();

  if (session) {
    const lastActivity = _agentLastActivity.get(agentName) || 0;
    const gap = now - lastActivity;

    if (gap > SESSION_IDLE_THRESHOLD_MS && session.turnHistory.length > 0) {
      // Session has been idle long enough - rotate it.
      // End the old session asynchronously (generates summary in background).
      // NOTE: caller must have already called config.reloadForAgent() and
      // memory.initDb() before calling getAgentSession() so that
      // loadSystemPrompt() and session.end() target the correct agent DB.
      const oldSession = session;
      const oldCliId = oldSession.cliSessionId;
      const system = loadSystemPrompt();
      oldSession.end(system).catch((err) => {
        log.error(`[${agentName}] failed to end idle session: ${err}`);
      });

      // Start a fresh memory session, carrying over the CLI session ID
      session = new Session();
      session.start();
      if (oldCliId) {
        session.cliSessionId = oldCliId;
      }
      _agentSessions.set(agentName, session);
      log.info(`[${agentName}] rotated idle session (gap: ${Math.round(gap / 60000)}m)`);
    }
  }

  if (!session) {
    session = new Session();
    session.start();
    _agentSessions.set(agentName, session);
  }

  _agentLastActivity.set(agentName, now);
  return session;
}

// ---------------------------------------------------------------------------
// Agent routers - one per agent, created on daemon start
// ---------------------------------------------------------------------------

const _agentRouters: Map<string, AgentRouter> = new Map();

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentPollerState {
  last_update_id: number;
}

interface DaemonState {
  agents: Record<string, AgentPollerState>;
}

interface TelegramAgent {
  name: string;
  display_name: string;
  emoji: string;
  botToken: string;
  chatId: string;
}

// ---------------------------------------------------------------------------
// State persistence
// ---------------------------------------------------------------------------

const STATE_FILE = path.join(USER_DATA, '.telegram_daemon_state.json');

function loadState(): DaemonState {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const raw = JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
      // Migrate from old format (had last_update_id + topic_map at top level)
      if (raw.agents && typeof raw.agents === 'object') {
        return { agents: raw.agents };
      }
      // Old format - start fresh
      return { agents: {} };
    }
  } catch { /* default */ }
  return { agents: {} };
}

function saveState(state: DaemonState): void {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2) + '\n');
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
      const lines = raw.split('\n');
      const pid = parseInt(lines[0], 10);
      const lockTime = lines[1] ? parseInt(lines[1], 10) : NaN;

      // If process is alive AND lock is < 30 minutes old, it's valid.
      const STALE_MS = 30 * 60 * 1000;
      if (pid && isProcessAlive(pid)) {
        if (isNaN(lockTime) || (Date.now() - lockTime < STALE_MS)) {
          return false;
        }
      }
    } catch { /* stale or corrupt - reclaim */ }
  }

  fs.writeFileSync(LOCK_FILE, `${process.pid}\n${Date.now()}\n`);
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

const PLIST_LABEL = 'com.atrophy.telegram-daemon';
const LAUNCH_AGENTS = path.join(process.env.HOME || '/tmp', 'Library', 'LaunchAgents');
const PLIST_PATH = path.join(LAUNCH_AGENTS, `${PLIST_LABEL}.plist`);

/**
 * Build an XML plist string for the telegram daemon launchd agent.
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
 */
export function installLaunchd(electronBin: string): void {
  fs.mkdirSync(LAUNCH_AGENTS, { recursive: true });

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
// Agent manifest helper
// ---------------------------------------------------------------------------

function getAgentManifest(agentName: string): Record<string, unknown> {
  for (const base of [
    path.join(USER_DATA, 'agents', agentName),
    path.join(BUNDLE_ROOT, 'agents', agentName),
  ]) {
    const mpath = path.join(base, 'data', 'agent.json');
    if (fs.existsSync(mpath)) {
      try {
        return JSON.parse(fs.readFileSync(mpath, 'utf-8'));
      } catch { /* skip */ }
    }
  }
  return {};
}

// ---------------------------------------------------------------------------
// Agent discovery
// ---------------------------------------------------------------------------

/**
 * Discover agents that have telegram credentials configured.
 * Temporarily reloads config for each agent to read per-agent tokens,
 * then restores the original agent.
 */
function discoverTelegramAgents(): TelegramAgent[] {
  const config = getConfig();
  const originalAgent = config.AGENT_NAME;
  const agents: TelegramAgent[] = [];

  try {
    for (const agent of discoverAgents()) {
      const state = getAgentState(agent.name);
      if (!state.enabled) continue;

      config.reloadForAgent(agent.name);

      const botToken = config.TELEGRAM_BOT_TOKEN;
      const chatId = config.TELEGRAM_CHAT_ID;

      if (!botToken || !chatId) continue;

      const manifest = getAgentManifest(agent.name);
      agents.push({
        name: agent.name,
        display_name: agent.display_name || agent.name.charAt(0).toUpperCase() + agent.name.slice(1),
        emoji: (manifest.telegram_emoji as string) || '',
        botToken,
        chatId,
      });
    }
  } finally {
    config.reloadForAgent(originalAgent);
  }

  return agents;
}

// ---------------------------------------------------------------------------
// Bot profile photo
// ---------------------------------------------------------------------------

async function setAgentBotPhoto(agentName: string, botToken: string): Promise<void> {
  const refs = getReferenceImages(agentName);
  if (refs.length === 0) return;
  try {
    await setBotProfilePhoto(refs[0], botToken);
    log.info(`[${agentName}] Bot profile photo set`);
  } catch (e) {
    log.debug(`[${agentName}] Profile photo failed: ${e}`);
  }
}

// ---------------------------------------------------------------------------
// Per-agent dispatch locks - agents dispatch in parallel, but each agent
// serialises its own dispatches to prevent overlapping inference.
// ---------------------------------------------------------------------------

const _agentDispatchQueues = new Map<string, Promise<void>>();
const _activeDispatches = new Set<string>();

function withAgentDispatchLock<T>(agentName: string, fn: () => Promise<T>): Promise<T> {
  let resolve: () => void;
  const next = new Promise<void>((r) => { resolve = r; });
  const prev = _agentDispatchQueues.get(agentName) || Promise.resolve();
  _agentDispatchQueues.set(agentName, next);
  return prev.then(async () => {
    try {
      return await fn();
    } finally {
      resolve!();
    }
  });
}

// ---------------------------------------------------------------------------
// Config mutex - narrow lock around config.reloadForAgent() which mutates
// a shared singleton. Released as soon as the subprocess is spawned.
// ---------------------------------------------------------------------------

let _configQueue: Promise<void> = Promise.resolve();

function withConfigLock<T>(fn: () => Promise<T>): Promise<T> {
  let resolve: () => void;
  const next = new Promise<void>((r) => { resolve = r; });
  const prev = _configQueue;
  _configQueue = next;
  return prev.then(async () => {
    try {
      return await fn();
    } finally {
      resolve!();
    }
  });
}

// ---------------------------------------------------------------------------
// Agent dispatch
// ---------------------------------------------------------------------------

const DISPATCH_TIMEOUT_MS = 6 * 60 * 60 * 1000; // 6 hours - agents need time for deep research

// ---------------------------------------------------------------------------
// Message deduplication
// ---------------------------------------------------------------------------

const DEDUP_WINDOW_MS = 5000;
const DEDUP_CACHE_SIZE = 200;
const _dedupCache = new Map<string, number>(); // hash -> timestamp

function isDuplicate(agentName: string, text: string): boolean {
  const hash = `${agentName}:${text.slice(0, 200)}`;
  const now = Date.now();

  // Evict old entries
  if (_dedupCache.size > DEDUP_CACHE_SIZE) {
    for (const [k, ts] of _dedupCache) {
      if (now - ts > DEDUP_WINDOW_MS * 2) _dedupCache.delete(k);
    }
  }

  const lastSeen = _dedupCache.get(hash);
  if (lastSeen && now - lastSeen < DEDUP_WINDOW_MS) {
    return true;
  }
  _dedupCache.set(hash, now);
  return false;
}

/**
 * Dispatch a message to an agent with rich live streaming back to Telegram.
 *
 * Shows the full inference process: thinking, tool calls with inputs and
 * results, compacting, and streamed response text - updated in real-time
 * by editing the Telegram message.
 */
async function dispatchToAgent(
  agentName: string,
  text: string,
  chatId: string,
  botToken: string,
  sourceLabel?: string,
): Promise<string | null> {
  const config = getConfig();
  const originalAgent = config.AGENT_NAME;

  // System-originated dispatches (cron, agent-to-agent) should be silent on
  // Telegram - no "Thinking..." indicator, no "No response" or error messages.
  // Only show output if the agent produces a real response.
  const isTelegramOrigin = !sourceLabel || sourceLabel.startsWith('Telegram message');

  const manifest = getAgentManifest(agentName);
  const emoji = (manifest.telegram_emoji as string) || '';
  const display = (manifest.display_name as string) || agentName.charAt(0).toUpperCase() + agentName.slice(1);
  const header = emoji ? `${emoji} *${display}*\n\n` : '';

  // Show typing indicator instead of "Thinking..." message for realism
  let msgId: number | null = null;
  if (isTelegramOrigin) {
    await sendChatAction('typing', chatId, botToken);
  }

  try {
    // Narrow config lock - only held while reloading config and spawning
    // the inference subprocess. Released before streaming begins.
    const emitter = await withConfigLock(async () => {
      config.reloadForAgent(agentName);
      resetMcpConfig();
      memory.initDb();

      const system = loadSystemPrompt();
      const agentSession = getAgentSession(agentName);
      agentSession.inheritCliSessionId();
      const prompt = sourceLabel ? `[${sourceLabel}]\n\n${text}` : text;

      // Cron dispatches use a fresh session to avoid writing into
      // interactive sessions (CCBot, desktop). The inherited session ID
      // is only safe for Telegram/user-originated messages.
      const isCronDispatch = sourceLabel?.startsWith('Scheduled job result');
      const sessionId = isCronDispatch ? null : agentSession.cliSessionId;

      // Save user turn before inference
      try { agentSession.addTurn('will', text); } catch { /* session not started */ }

      // Mark user as active when a real Telegram message arrives (not cron)
      if (isTelegramOrigin) { try { setActive(); } catch { /* non-critical */ } }

      return streamInference(prompt, system, sessionId);
    });

    let fullText = '';
    let _lastStreamSessionId: string | null = null;
    const toolsUsed: string[] = [];

    // Rich streaming state
    const startTime = Date.now();
    const state: StreamState = {
      thinkingText: '',
      activeTool: null,
      pendingTools: new Map(),
      completedTools: [],
      responseText: '',
      isCompacting: false,
      startTime,
    };

    // Throttle edits to avoid Telegram rate limits
    const EDIT_INTERVAL_MS = 1500;
    let lastEditTime = 0;
    let editPending = false;

    const doEdit = async (): Promise<void> => {
      if (!msgId) return;
      const now = Date.now();
      if (now - lastEditTime < EDIT_INTERVAL_MS) {
        editPending = true;
        return;
      }
      editPending = false;
      lastEditTime = now;
      const displayText = buildStatusDisplay(state);
      await editMessage(msgId, `${header}${displayText}`, chatId, botToken);
    };


    await new Promise<void>((resolve, reject) => {
      // Periodically flush throttled edits
      const flushTimer = setInterval(async () => {
        if (editPending) {
          await doEdit();
        }
      }, EDIT_INTERVAL_MS);

      const timer = setTimeout(() => {
        log.error(`[${agentName}] dispatch timed out after ${DISPATCH_TIMEOUT_MS / 1000}s`);
        clearInterval(flushTimer);
        stopInference(agentName); // Kill the lingering CLI process for this agent only
        reject(new Error('dispatch timeout'));
      }, DISPATCH_TIMEOUT_MS);

      emitter.on('event', async (evt: InferenceEvent) => {
        switch (evt.type) {
          case 'ThinkingDelta':
            // Don't show thinking in Telegram - just keep typing indicator alive
            if (isTelegramOrigin) {
              await sendChatAction('typing', chatId, botToken);
            }
            break;

          case 'ToolUse': {
            // Track new tool - don't move active to completed yet (wait for result)
            const toolState: ToolCallState = {
              name: evt.name,
              id: evt.toolId,
              input: evt.inputJson || '',
              result: '',
            };
            state.activeTool = toolState;
            state.pendingTools.set(evt.toolId, toolState);
            toolsUsed.push(evt.name);
            log.debug(`[${agentName}] tool -> ${evt.name}`);
            await doEdit();
            break;
          }

          case 'ToolInputDelta': {
            // Accumulate tool input JSON - look up by ID to handle parallel calls
            const tool = state.pendingTools.get(evt.toolId) || state.activeTool;
            if (tool) {
              tool.input += evt.delta;
              await doEdit();
            }
            break;
          }

          case 'ToolResult': {
            // Match result to tool by ID across pending tools
            const tool = state.pendingTools.get(evt.toolId);
            if (tool) {
              tool.result = evt.output;
              state.pendingTools.delete(evt.toolId);
              state.completedTools.push(tool);
              if (state.activeTool?.id === evt.toolId) {
                state.activeTool = null;
              }
            } else {
              // Result for a tool we didn't track
              state.completedTools.push({
                name: evt.toolName || '?',
                id: evt.toolId,
                input: '',
                result: evt.output,
              });
            }
            await doEdit();
            break;
          }

          case 'TextDelta':
            state.responseText += evt.text;
            break;

          case 'Compacting':
            state.isCompacting = true;
            if (isTelegramOrigin) {
              await sendChatAction('typing', chatId, botToken);
            }
            break;

          case 'StreamDone':
            clearTimeout(timer);
            clearInterval(flushTimer);
            state.isCompacting = false;
            fullText = evt.fullText;
            // Stash session ID for persistence after promise resolves
            _lastStreamSessionId = evt.sessionId || null;
            resolve();
            break;

          case 'StreamError':
            clearTimeout(timer);
            clearInterval(flushTimer);
            log.error(`[${agentName}] inference error: ${evt.message}`);
            resolve();
            break;
        }
      });
    });

    if (toolsUsed.length) {
      log.debug(`[${agentName}] used tools: ${toolsUsed.join(', ')}`);
    }

    // Persist session ID and agent turn under the correct agent's DB.
    // Skip session ID save for cron dispatches - they use throwaway sessions
    // and must not overwrite the interactive session ID in memory.db.
    const isCronDispatch = sourceLabel?.startsWith('Scheduled job result');
    if (_lastStreamSessionId || fullText) {
      await withConfigLock(async () => {
        config.reloadForAgent(agentName);
        memory.initDb();
        const agentSession = getAgentSession(agentName);
        if (_lastStreamSessionId && !isCronDispatch) {
          agentSession.setCliSessionId(_lastStreamSessionId);
          log.debug(`[${agentName}] saved CLI session: ${_lastStreamSessionId}`);
        }
        if (fullText.trim()) {
          try { agentSession.addTurn('agent', fullText.trim()); } catch { /* */ }
        }
      });
    }

    const finalText = fullText.trim() || null;
    const elapsed = formatElapsed(Date.now() - startTime);

    log.info(`[${agentName}] completed in ${elapsed}`);

    // Send final response as a fresh message (no editing, no thinking shown)
    if (finalText && isTelegramOrigin) {
      await sendMessage(`${header}${finalText}`, chatId, false, botToken);

      // Auto-upload files mentioned in the response (e.g. generated docs)
      // Matches paths like /Users/.../file.docx or ~/.atrophy/.../file.pdf
      const fileRe = /(?:\/Users\/\S+|~\/\S+)\.(?:docx|pdf|xlsx|csv|txt|md|html|json|png|jpg)/g;
      const filePaths = finalText.match(fileRe);
      if (filePaths) {
        for (const raw of filePaths) {
          const fp = raw.startsWith('~') ? raw.replace('~', os.homedir()) : raw;
          if (fs.existsSync(fp)) {
            try {
              await sendDocument(fp, path.basename(fp), chatId, '', botToken);
              log.info(`[${agentName}] uploaded file: ${path.basename(fp)}`);
            } catch (e) {
              log.warn(`[${agentName}] file upload failed: ${e}`);
            }
          }
        }
      }

      // Auto-send artefacts created during this dispatch
      try {
        const displayFile = path.join(USER_DATA, 'agents', agentName, 'data', '.artefact_display.json');
        if (fs.existsSync(displayFile)) {
          const artefact = JSON.parse(fs.readFileSync(displayFile, 'utf-8')) as {
            status?: string;
            type?: string;
            name?: string;
            path?: string;
            file?: string;
          };
          const artefactPath = artefact.path || artefact.file;
          if (artefact.status === 'ready' && artefactPath && fs.existsSync(artefactPath)) {
            const ext = path.extname(artefactPath).toLowerCase();
            if (['.html', '.htm'].includes(ext)) {
              // Send HTML artefacts as documents
              await sendDocument(artefactPath, artefact.name || 'artefact', chatId, '', botToken);
              log.info(`[${agentName}] sent artefact: ${artefact.name}`);
            } else if (['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes(ext)) {
              // Send images inline
              await sendPhoto(artefactPath, artefact.name || '', chatId, '', botToken);
              log.info(`[${agentName}] sent artefact image: ${artefact.name}`);
            } else {
              // Send everything else as a document
              await sendDocument(artefactPath, artefact.name || 'artefact', chatId, '', botToken);
              log.info(`[${agentName}] sent artefact: ${artefact.name}`);
            }
            // Clean up display signal so it doesn't re-send next dispatch
            try { fs.unlinkSync(displayFile); } catch { /* already gone */ }
          }
        }
      } catch (artefactErr) {
        log.debug(`[${agentName}] artefact check: ${artefactErr}`);
      }
    } else if (!finalText && isTelegramOrigin) {
      log.warn(`[${agentName}] no response after ${elapsed}`);
    }

    return finalText;
  } catch (e) {
    log.error(`[${agentName}] dispatch failed: ${e}`);
    return null;
  } finally {
    await withConfigLock(async () => {
      config.reloadForAgent(originalAgent);
      resetMcpConfig();
      memory.initDb();
    });
  }
}

// ---------------------------------------------------------------------------
// Utility commands
// ---------------------------------------------------------------------------

async function handleStatusCommand(chatId: string, botToken: string): Promise<void> {
  const agents = discoverTelegramAgents();
  const lines = ['*Active agents:*\n'];

  for (const a of agents) {
    const prefix = a.emoji ? `${a.emoji} ` : '';
    lines.push(`${prefix}*${a.display_name}* (\`/${a.name}\`)`);
  }

  const text = lines.join('\n');
  await sendMessage(text, chatId, false, botToken);
}

// ---------------------------------------------------------------------------
// Per-agent polling
// ---------------------------------------------------------------------------

let _state: DaemonState = { agents: {} };
let _running = false;
let _pollerTimers: ReturnType<typeof setTimeout>[] = [];

/**
 * One poll cycle for a single agent's bot. Fetches updates, processes
 * messages, and dispatches to the agent.
 */
async function pollAgent(agent: TelegramAgent): Promise<void> {
  if (!_running) return;

  const agentState = _state.agents[agent.name] || { last_update_id: 0 };

  let raw: unknown;
  try {
    raw = await post('getUpdates', {
      offset: agentState.last_update_id + 1,
      timeout: 30,
      allowed_updates: ['message'],
    }, 45_000, agent.botToken);
  } catch (e) {
    if (!_running) return;
    throw e;
  }

  const result = Array.isArray(raw) ? raw as {
    update_id: number;
    message?: {
      text?: string;
      caption?: string;
      from?: { id: number; is_bot?: boolean };
      chat?: { id: number };
      photo?: { file_id: string; file_unique_id: string; width: number; height: number; file_size?: number }[];
      voice?: { file_id: string; duration: number; mime_type?: string; file_size?: number };
      document?: { file_id: string; file_name?: string; mime_type?: string; file_size?: number };
      video?: { file_id: string; duration: number; width: number; height: number; mime_type?: string; file_size?: number };
    };
  }[] : null;

  if (!result) return;

  for (const update of result) {
    agentState.last_update_id = Math.max(agentState.last_update_id, update.update_id);

    const msg = update.message;
    if (!msg) continue;

    // Ignore messages from other bots (prevents cross-talk with CCBot etc.)
    if (msg.from?.is_bot) continue;

    // A message has content if it has text, caption, or any media attachment
    const hasText = !!(msg.text?.trim());
    const hasMedia = !!(msg.photo || msg.voice || msg.document || msg.video);
    if (!hasText && !hasMedia) continue;

    // Only accept messages from the configured chat
    const msgChatId = String(msg.chat?.id || '');
    if (msgChatId !== agent.chatId) continue;

    const text = (msg.text || '').trim();

    // Handle /status command
    if (text.toLowerCase() === '/status') {
      await withAgentDispatchLock(agent.name, () => handleStatusCommand(msgChatId, agent.botToken));
      continue;
    }

    // Build the prompt from text and/or media
    const promptParts: string[] = [];
    const mediaDir = path.join(USER_DATA, 'agents', agent.name, 'media');

    // Identify the sender by their Telegram name (not hardcoded)
    const senderName = msg.from?.first_name || 'Someone';

    if (msg.photo && msg.photo.length > 0) {
      // Telegram sends multiple sizes - take the largest (last in array)
      const largest = msg.photo[msg.photo.length - 1];
      const savedPath = await downloadTelegramFile(largest.file_id, mediaDir, undefined, agent.botToken);
      if (savedPath) {
        promptParts.push(`[Telegram photo from ${senderName}]\n\n<image saved to: ${savedPath}>`);
      } else {
        promptParts.push(`[Telegram photo from ${senderName} - download failed]`);
      }
    }

    if (msg.voice) {
      const savedPath = await downloadTelegramFile(msg.voice.file_id, mediaDir, undefined, agent.botToken);
      if (savedPath) {
        promptParts.push(`[Telegram voice message from ${senderName}]\n\n<voice note saved to: ${savedPath}>`);
      } else {
        promptParts.push(`[Telegram voice message from ${senderName} - download failed]`);
      }
    }

    if (msg.document) {
      const docFilename = msg.document.file_name || undefined;
      const savedPath = await downloadTelegramFile(msg.document.file_id, mediaDir, docFilename, agent.botToken);
      const label = msg.document.file_name ? `Telegram document from ${senderName}: ${msg.document.file_name}` : `Telegram document from ${senderName}`;
      if (savedPath) {
        promptParts.push(`[${label}]\n\n<file saved to: ${savedPath}>`);
      } else {
        promptParts.push(`[${label} - download failed]`);
      }
    }

    if (msg.video) {
      const savedPath = await downloadTelegramFile(msg.video.file_id, mediaDir, undefined, agent.botToken);
      if (savedPath) {
        promptParts.push(`[Telegram video from ${senderName}]\n\n<video saved to: ${savedPath}>`);
      } else {
        promptParts.push(`[Telegram video from ${senderName} - download failed]`);
      }
    }

    // Include text/caption content, prefixed with sender name for group chats
    const messageText = text || (msg.caption || '').trim();
    if (messageText) {
      const isGroup = msg.chat?.type === 'group' || msg.chat?.type === 'supergroup';
      promptParts.push(isGroup ? `${senderName}: ${messageText}` : messageText);
    }

    const fullPrompt = promptParts.join('\n\n');
    if (!fullPrompt) continue;

    // Deduplicate - skip if same message received within 5s
    if (isDuplicate(agent.name, fullPrompt)) {
      log.debug(`[${agent.name}] Skipping duplicate message`);
      continue;
    }

    log.info(`[${agent.name}] Message: ${fullPrompt.slice(0, 80)}`);

    // Route through switchboard - create an Envelope and let the
    // switchboard deliver it to the agent's router
    const envelope = switchboard.createEnvelope(
      `telegram:${agent.name}`,
      `agent:${agent.name}`,
      fullPrompt,
      {
        type: 'user',
        priority: 'normal',
        replyTo: `telegram:${agent.name}`,
        metadata: {
          chatId: msgChatId,
          botToken: agent.botToken,
          agentName: agent.name,
          senderName,
        },
      },
    );

    await switchboard.route(envelope);
  }

  _state.agents[agent.name] = agentState;
  saveState(_state);
}

/**
 * Per-agent polling loop with random jitter between polls for organic feel.
 */
async function runAgentPoller(agent: TelegramAgent): Promise<void> {
  log.info(`[${agent.name}] Poller started`);

  while (_running) {
    try {
      await pollAgent(agent);
    } catch (e) {
      if (!_running) return;
      log.error(`[${agent.name}] Poll error: ${e}`);
    }
    if (_running) {
      // Random jitter: 8-15 seconds for organic feel
      const jitter = 8000 + Math.random() * 7000;
      await new Promise((resolve) => {
        const t = setTimeout(() => {
          const idx = _pollerTimers.indexOf(t);
          if (idx !== -1) _pollerTimers.splice(idx, 1);
          resolve(undefined);
        }, jitter);
        _pollerTimers.push(t);
      });
    }
  }

  log.info(`[${agent.name}] Poller stopped`);
}

// ---------------------------------------------------------------------------
// Switchboard integration
// ---------------------------------------------------------------------------

/**
 * Register an agent's message handlers with the switchboard.
 *
 * Creates two handlers per agent:
 *   1. agent:{name} - receives inbound messages, runs inference via
 *      dispatchToAgent (with full streaming display logic intact)
 *   2. telegram:{name} - receives response envelopes, sends text to
 *      Telegram (used when responses arrive from other agents or system)
 */
function registerAgentSwitchboard(agent: TelegramAgent): void {
  // Register telegram response handler - receives envelopes addressed
  // to this agent's Telegram channel and sends them via Telegram API
  switchboard.register(`telegram:${agent.name}`, async (envelope: Envelope) => {
    // If this is a response from the agent's own inference, the streaming
    // display already sent it. Only send here for cross-agent messages
    // or system notifications that arrive via the switchboard.
    const fromSelf = envelope.from === `agent:${agent.name}`;
    if (fromSelf && envelope.metadata?.streamedToTelegram) {
      // Already sent during streaming - skip to avoid duplicate
      return;
    }

    if (envelope.text) {
      await sendMessage(envelope.text, agent.chatId, false, agent.botToken);
      log.debug(`[${agent.name}] Telegram response sent (${envelope.text.length} chars)`);
    }
  });

  // Create agent router - handles inbound messages to agent:{name}
  // The router filters messages and calls our callback for accepted ones
  const routerConfig = defaultConfigForAgent(agent.name);
  const router = new AgentRouter(agent.name, routerConfig, async (envelope: Envelope) => {
    // Per-agent dispatch guard: drop non-Telegram envelopes if already dispatching.
    // Telegram messages are allowed through - they queue via withAgentDispatchLock
    // so the user's message is handled after the current dispatch finishes.
    if (_activeDispatches.has(agent.name)) {
      if (!envelope.from.startsWith('telegram:')) {
        log.debug(`[${agent.name}] Dispatch in progress - dropping non-Telegram envelope from ${envelope.from}`);
        return undefined;
      }
      log.info(`[${agent.name}] Dispatch in progress - queuing Telegram message`);
      // Let the user know the agent is busy but received their message
      const busyChatId = (envelope.metadata?.chatId as string) || agent.chatId;
      await sendChatAction('typing', busyChatId, agent.botToken);
    }

    // Extract Telegram-specific metadata for streaming display
    const chatId = (envelope.metadata?.chatId as string) || agent.chatId;
    const botToken = (envelope.metadata?.botToken as string) || agent.botToken;

    // Build source label based on envelope origin
    const isCron = envelope.from.startsWith('cron:');
    const telegramSender = envelope.options?.metadata?.senderName || getConfig().USER_NAME;
    const sourceLabel = envelope.from.startsWith('telegram:')
      ? `Telegram message from ${telegramSender}`
      : isCron
        ? `Scheduled job result - ${envelope.from}`
        : `Message from ${envelope.from}`;

    // Only dispatch cron jobs that explicitly opt in via route_output_to in
    // jobs.json. Background jobs (observer, sleep_cycle, evolve, introspect)
    // produce diagnostic output that should be logged but never trigger
    // inference or reach Telegram.
    if (isCron) {
      if (!envelope.metadata?.dispatch) {
        log.debug(`[${agent.name}] Cron output suppressed (no dispatch flag): ${envelope.from} - ${envelope.text.slice(0, 80)}`);
        return undefined;
      }

      // Even dispatched jobs may produce skip-worthy output on certain runs
      const text = envelope.text.trim().toLowerCase();
      const exitCode = (envelope.metadata?.exitCode as number) ?? 0;
      const isSkip = text.includes('skipping') || text.includes('outside active hours')
        || text.includes('user is away') || text.includes('no heartbeat')
        || text.includes('no reminders') || text.includes('nothing to surface');
      const isFail = exitCode !== 0;

      if (isSkip || isFail) {
        const reason = isFail ? `exit=${exitCode}` : 'skip';
        log.debug(`[${agent.name}] Cron output filtered (${reason}): ${envelope.text.slice(0, 80)}`);
        return undefined;
      }
    }

    // Per-agent dispatch lock - agents dispatch in parallel
    _activeDispatches.add(agent.name);
    let response: string | null = null;
    try {
      response = await withAgentDispatchLock(agent.name, () =>
        dispatchToAgent(agent.name, envelope.text, chatId, botToken, sourceLabel),
      );
    } finally {
      _activeDispatches.delete(agent.name);
    }

    // For cron dispatches with meaningful responses, send to Telegram.
    // dispatchToAgent only sends via edit for Telegram-origin messages
    // (where msgId exists). For cron, we need to explicitly send.
    if (isCron && response) {
      const manifest = getAgentManifest(agent.name);
      const emoji = (manifest.telegram_emoji as string) || '';
      const display = (manifest.display_name as string) || agent.name;
      const header = emoji ? `${emoji} *${display}*\n\n` : '';
      await sendMessage(`${header}${response}`, chatId, false, botToken);
      log.info(`[${agent.name}] Cron response sent to Telegram (${response.length} chars)`);
    } else if (response) {
      log.info(`[${agent.name}] Responded via switchboard (${response.length} chars)`);
    } else if (!isCron) {
      log.warn(`[${agent.name}] No response via switchboard`);
    }

    return undefined;
  });

  _agentRouters.set(agent.name, router);
  log.info(`[${agent.name}] Switchboard handlers registered`);
}

// ---------------------------------------------------------------------------
// Daemon control
// ---------------------------------------------------------------------------

/**
 * Start the polling daemon. Discovers agents with telegram credentials
 * and launches a parallel poller per agent. Acquires an instance lock
 * to prevent duplicate processes. Returns false if another instance
 * is already running or no agents have telegram credentials.
 */
export function startDaemon(): boolean {
  if (_running) return true;

  if (!acquireLock()) {
    log.warn('Another instance is running - exiting');
    return false;
  }

  _running = true;
  _state = loadState();
  _pollerTimers = [];

  const agents = discoverTelegramAgents();
  if (agents.length === 0) {
    log.warn('No agents with telegram credentials');
    releaseLock();
    _running = false;
    return false;
  }

  log.info(`Starting ${agents.length} poller(s): ${agents.map(a => a.name).join(', ')}`);

  // Set bot profile photos (fire-and-forget)
  for (const agent of agents) {
    setAgentBotPhoto(agent.name, agent.botToken).catch(() => {});
  }

  // Register switchboard handlers for each agent
  for (const agent of agents) {
    registerAgentSwitchboard(agent);
  }

  // Stagger poller launches to avoid thundering herd on startup
  agents.forEach((agent, i) => {
    setTimeout(() => runAgentPoller(agent), i * 10_000);
  });

  return true;
}

/**
 * Stop the polling daemon and release the instance lock.
 * Tears down agent routers and unregisters switchboard handlers.
 */
export function stopDaemon(): void {
  _running = false;
  for (const t of _pollerTimers) clearTimeout(t);
  _pollerTimers = [];

  // End all per-agent telegram sessions so ended_at gets set.
  // Each agent has its own DB, so we must switch config before ending.
  const config = getConfig();
  for (const [name, session] of _agentSessions) {
    if (session.sessionId != null) {
      try {
        config.reloadForAgent(name);
        memory.initDb();
        memory.endSession(session.sessionId, null, session.mood);
      } catch { /* DB may already be closing */ }
    }
  }
  _agentSessions.clear();

  // Tear down agent routers
  for (const [name, router] of _agentRouters) {
    router.destroy();
  }
  _agentRouters.clear();

  // Unregister telegram response handlers
  for (const address of switchboard.getRegisteredAddresses()) {
    if (address.startsWith('telegram:')) {
      switchboard.unregister(address);
    }
  }

  releaseLock();
  log.info('Stopped');
}

export function isDaemonRunning(): boolean {
  return _running;
}
