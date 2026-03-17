/**
 * Telegram Topics daemon - one topic per agent, sequential dispatch.
 * Port of channels/telegram_daemon.py (Topics mode).
 *
 * Uses Telegram Forum (Topics) mode in a supergroup. On startup, creates
 * a topic for each enabled agent. Messages in a topic go directly to that
 * agent - no routing needed, the topic IS the agent.
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
import { sendMessage, sendMessageGetId, editMessage, post, setLastUpdateId, downloadTelegramFile } from './telegram';
import { discoverAgents, getAgentState } from './agent-manager';
import { streamInference, resetMcpConfig, InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import * as memory from './memory';
import { createLogger } from './logger';

const log = createLogger('telegram-daemon');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DaemonState {
  last_update_id: number;
  topic_map: Record<string, string>; // thread_id -> agent_name
}

// ---------------------------------------------------------------------------
// State persistence
// ---------------------------------------------------------------------------

const STATE_FILE = path.join(USER_DATA, '.telegram_daemon_state.json');

function loadState(): DaemonState {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const raw = JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
      return {
        last_update_id: raw.last_update_id || 0,
        topic_map: raw.topic_map || {},
      };
    }
  } catch { /* default */ }
  return { last_update_id: 0, topic_map: {} };
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
// Topic management
// ---------------------------------------------------------------------------

/**
 * Create a forum topic in a supergroup. Returns the topic thread_id or null.
 */
async function createForumTopic(chatId: string, name: string): Promise<number | null> {
  const payload: Record<string, unknown> = { chat_id: chatId, name };
  const result = await post('createForumTopic', payload) as { message_thread_id?: number } | null;
  if (result) {
    return result.message_thread_id ?? null;
  }
  return null;
}

/**
 * Discover enabled agents and return their info with manifest data.
 */
function discoverEnabledAgents(): { name: string; display_name: string; emoji: string }[] {
  const agents: { name: string; display_name: string; emoji: string }[] = [];

  for (const agent of discoverAgents()) {
    const state = getAgentState(agent.name);
    if (!state.enabled) {
      continue;
    }
    const manifest = getAgentManifest(agent.name);
    agents.push({
      name: agent.name,
      display_name: agent.display_name || agent.name.charAt(0).toUpperCase() + agent.name.slice(1),
      emoji: (manifest.telegram_emoji as string) || '',
    });
  }

  return agents;
}

/**
 * Ensure each enabled agent has a topic in the group. Creates missing ones.
 * Returns the updated state with topic_map populated.
 */
async function ensureTopics(groupId: string, state: DaemonState): Promise<DaemonState> {
  const topicMap = state.topic_map;

  // Build reverse map: agent_name -> thread_id
  const agentToTopic: Record<string, string> = {};
  for (const [threadId, agentName] of Object.entries(topicMap)) {
    agentToTopic[agentName] = threadId;
  }

  const agents = discoverEnabledAgents();

  for (const agent of agents) {
    if (agent.name in agentToTopic) {
      log.debug(`Agent ${agent.name} already has topic ${agentToTopic[agent.name]}`);
      continue;
    }

    // Create a new topic for this agent
    const topicName = agent.emoji ? `${agent.emoji} ${agent.display_name}` : agent.display_name;
    const threadId = await createForumTopic(groupId, topicName);

    if (threadId) {
      topicMap[String(threadId)] = agent.name;
      log.info(`Created topic '${topicName}' (thread_id=${threadId}) for agent ${agent.name}`);
    } else {
      log.error(`Failed to create topic for agent ${agent.name}`);
    }
  }

  state.topic_map = topicMap;
  return state;
}

// ---------------------------------------------------------------------------
// Agent dispatch
// ---------------------------------------------------------------------------

const DISPATCH_TIMEOUT_MS = 5 * 60 * 1000; // 5 minute max per agent dispatch

/**
 * Dispatch a message to an agent with live streaming back to Telegram.
 *
 * Sends an initial "Thinking..." message, then edits it in-place as
 * text streams in. Shows tool use and thinking status. Returns the
 * final response text, or null on failure.
 */
async function dispatchToAgent(
  agentName: string,
  text: string,
  chatId: string,
  threadId: number,
): Promise<string | null> {
  const config = getConfig();
  const originalAgent = config.AGENT_NAME;

  // Send initial thinking indicator and capture message_id for edits
  const manifest = getAgentManifest(agentName);
  const emoji = (manifest.telegram_emoji as string) || '';
  const display = (manifest.display_name as string) || agentName.charAt(0).toUpperCase() + agentName.slice(1);
  const header = emoji ? `${emoji} *${display}*\n\n` : '';

  const msgId = await sendMessageGetId(`${header}_Thinking..._`, chatId, threadId);

  try {
    config.reloadForAgent(agentName);
    resetMcpConfig();
    memory.initDb();

    const system = loadSystemPrompt();
    const cliSessionId = memory.getLastCliSessionId();

    const prompt = `[Telegram message from ${config.USER_NAME}]\n\n${text}`;
    let fullText = '';
    let streamedText = '';
    const toolsUsed: string[] = [];

    // Throttle edits to avoid Telegram rate limits
    const EDIT_INTERVAL_MS = 1500;
    let lastEditTime = 0;
    let editPending = false;

    const doEdit = async (content: string): Promise<void> => {
      if (!msgId) return;
      const now = Date.now();
      if (now - lastEditTime < EDIT_INTERVAL_MS) {
        editPending = true;
        return;
      }
      editPending = false;
      lastEditTime = now;
      await editMessage(msgId, `${header}${content}`, chatId);
    };

    // Flush any pending edit that was throttled
    const flushEdit = async (content: string): Promise<void> => {
      if (!msgId) return;
      await editMessage(msgId, `${header}${content}`, chatId);
    };

    await new Promise<void>((resolve, reject) => {
      const emitter = streamInference(prompt, system, cliSessionId);

      const timer = setTimeout(() => {
        log.error(`[${agentName}] dispatch timed out after ${DISPATCH_TIMEOUT_MS / 1000}s`);
        reject(new Error('dispatch timeout'));
      }, DISPATCH_TIMEOUT_MS);

      // Periodically flush throttled edits
      const flushTimer = setInterval(async () => {
        if (editPending && streamedText) {
          await doEdit(streamedText);
        }
      }, EDIT_INTERVAL_MS);

      emitter.on('event', async (evt: InferenceEvent) => {
        switch (evt.type) {
          case 'TextDelta':
            streamedText += evt.text;
            await doEdit(streamedText);
            break;
          case 'ToolUse':
            toolsUsed.push(evt.name);
            log.debug(`[${agentName}] tool -> ${evt.name}`);
            // Show tool usage in the message
            await doEdit(`${streamedText}\n\n_Using ${evt.name}..._`);
            break;
          case 'Compacting':
            await doEdit(`${streamedText}\n\n_Compacting context..._`);
            break;
          case 'StreamDone':
            clearTimeout(timer);
            clearInterval(flushTimer);
            fullText = evt.fullText;
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

    const finalText = fullText.trim() || null;

    // Final edit with complete response (removes any trailing tool-use indicators)
    if (finalText && msgId) {
      await flushEdit(finalText);
    } else if (!finalText && msgId) {
      await flushEdit('_No response_');
    }

    return finalText;
  } catch (e) {
    log.error(`[${agentName}] dispatch failed: ${e}`);
    if (msgId) {
      await editMessage(msgId, `${header}_Error: dispatch failed_`, chatId);
    }
    return null;
  } finally {
    config.reloadForAgent(originalAgent);
    resetMcpConfig();
    memory.initDb();
  }
}

// ---------------------------------------------------------------------------
// Utility commands
// ---------------------------------------------------------------------------

async function handleStatusCommand(chatId: string, threadId?: number): Promise<void> {
  const agents = discoverEnabledAgents();
  const lines = ['*Active agents:*\n'];

  for (const a of agents) {
    const prefix = a.emoji ? `${a.emoji} ` : '';
    lines.push(`${prefix}*${a.display_name}* (\`/${a.name}\`)`);
  }

  const text = lines.join('\n');
  await sendMessage(text, chatId, false, threadId);
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

let _state: DaemonState = { last_update_id: 0, topic_map: {} };

async function pollOnce(): Promise<void> {
  if (!_running) return;

  const config = getConfig();
  if (!config.TELEGRAM_BOT_TOKEN) {
    log.warn('TELEGRAM_BOT_TOKEN not configured');
    return;
  }

  const groupId = config.TELEGRAM_GROUP_ID;
  const userId = config.TELEGRAM_CHAT_ID; // Will's personal user ID for auth

  // Use abort controller so stopDaemon() can cancel the long-poll
  _pollAbort = new AbortController();

  let raw: unknown;
  try {
    raw = await post('getUpdates', {
      offset: _state.last_update_id + 1,
      timeout: 30,
      allowed_updates: ['message'],
    }, 45_000);
  } catch (e) {
    if (!_running) return; // Aborted by stopDaemon
    throw e;
  } finally {
    _pollAbort = null;
  }

  const result = Array.isArray(raw) ? raw as {
    update_id: number;
    message?: {
      text?: string;
      caption?: string;
      from?: { id: number };
      chat?: { id: number };
      message_thread_id?: number;
      photo?: { file_id: string; file_unique_id: string; width: number; height: number; file_size?: number }[];
      voice?: { file_id: string; duration: number; mime_type?: string; file_size?: number };
      document?: { file_id: string; file_name?: string; mime_type?: string; file_size?: number };
      video?: { file_id: string; duration: number; width: number; height: number; mime_type?: string; file_size?: number };
    };
  }[] : null;

  if (!result) return;

  for (const update of result) {
    _state.last_update_id = Math.max(_state.last_update_id, update.update_id);

    const msg = update.message;
    if (!msg) continue;

    // A message has content if it has text, caption, or any media attachment
    const hasText = !!(msg.text?.trim());
    const hasMedia = !!(msg.photo || msg.voice || msg.document || msg.video);
    if (!hasText && !hasMedia) continue;

    // Only accept messages from Will in the configured group
    const senderId = String(msg.from?.id || '');
    const msgChatId = String(msg.chat?.id || '');

    if (userId && senderId !== userId) {
      log.debug(`Ignoring message from user ${senderId}`);
      continue;
    }

    if (groupId && msgChatId !== groupId) {
      log.debug(`Ignoring message from chat ${msgChatId}`);
      continue;
    }

    const text = (msg.text || '').trim();
    const threadId = msg.message_thread_id;

    // Handle /status anywhere (text-only)
    if (text.toLowerCase() === '/status') {
      await handleStatusCommand(msgChatId, threadId);
      continue;
    }

    // Messages must be in a topic to reach an agent
    if (!threadId) {
      log.debug(`Ignoring message outside of topic: ${text.slice(0, 40)}`);
      continue;
    }

    // Look up which agent owns this topic
    const agentName = _state.topic_map[String(threadId)];
    if (!agentName) {
      log.warn(`No agent mapped to thread_id ${threadId}, ignoring`);
      continue;
    }

    // Build the prompt from text and/or media
    const promptParts: string[] = [];

    // Handle incoming media - download to agent's media directory
    const mediaDir = path.join(USER_DATA, 'agents', agentName, 'media');

    if (msg.photo && msg.photo.length > 0) {
      // Telegram sends multiple sizes - take the largest (last in array)
      const largest = msg.photo[msg.photo.length - 1];
      const savedPath = await downloadTelegramFile(largest.file_id, mediaDir);
      if (savedPath) {
        promptParts.push(`[Telegram photo from Will]\n\n<image saved to: ${savedPath}>`);
      } else {
        promptParts.push('[Telegram photo from Will - download failed]');
      }
    }

    if (msg.voice) {
      const savedPath = await downloadTelegramFile(msg.voice.file_id, mediaDir);
      if (savedPath) {
        promptParts.push(`[Telegram voice message from Will]\n\n<voice note saved to: ${savedPath}>`);
      } else {
        promptParts.push('[Telegram voice message from Will - download failed]');
      }
    }

    if (msg.document) {
      const docFilename = msg.document.file_name || undefined;
      const savedPath = await downloadTelegramFile(msg.document.file_id, mediaDir, docFilename);
      const label = msg.document.file_name ? `Telegram document from Will: ${msg.document.file_name}` : 'Telegram document from Will';
      if (savedPath) {
        promptParts.push(`[${label}]\n\n<file saved to: ${savedPath}>`);
      } else {
        promptParts.push(`[${label} - download failed]`);
      }
    }

    if (msg.video) {
      const savedPath = await downloadTelegramFile(msg.video.file_id, mediaDir);
      if (savedPath) {
        promptParts.push(`[Telegram video from Will]\n\n<video saved to: ${savedPath}>`);
      } else {
        promptParts.push('[Telegram video from Will - download failed]');
      }
    }

    // Include text/caption content
    // A media message can have a caption instead of text
    const messageText = text || (msg.caption || '').trim();
    if (messageText) {
      promptParts.push(messageText);
    }

    const fullPrompt = promptParts.join('\n\n');
    if (!fullPrompt) continue;

    log.info(`[${agentName}] Message: ${fullPrompt.slice(0, 80)}`);

    // Dispatch with live streaming back to Telegram
    const response = await dispatchToAgent(agentName, fullPrompt, msgChatId, threadId);
    if (response) {
      log.info(`[${agentName}] Responded (${response.length} chars)`);
    } else {
      log.warn(`[${agentName}] No response`);
    }
  }

  saveState(_state);
}

// ---------------------------------------------------------------------------
// Daemon control
// ---------------------------------------------------------------------------

let _pollTimer: ReturnType<typeof setInterval> | null = null;
let _running = false;
let _pollAbort: AbortController | null = null;

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
  _state = loadState();
  setLastUpdateId(_state.last_update_id);

  log.info(`Starting (last_update_id=${_state.last_update_id}, topics=${Object.keys(_state.topic_map).length}, interval=${intervalMs}ms)`);

  // Ensure topics exist before starting the poll loop
  async function initAndPoll(): Promise<void> {
    const config = getConfig();
    if (config.TELEGRAM_GROUP_ID) {
      try {
        _state = await ensureTopics(config.TELEGRAM_GROUP_ID, _state);
        saveState(_state);
        log.info(`Topics ready: ${Object.keys(_state.topic_map).length} agents`);
      } catch (e) {
        log.error(`Failed to ensure topics: ${e}`);
      }
    }

    // Sequential polling loop - wait for each poll to complete before scheduling next
    while (_running) {
      try {
        await pollOnce();
      } catch (e) {
        log.error(`Poll error: ${e}`);
      }
      if (_running) {
        await new Promise((resolve) => {
          _pollTimer = setTimeout(resolve, intervalMs) as unknown as ReturnType<typeof setInterval>;
        });
      }
    }
  }

  initAndPoll();

  return true;
}

/**
 * Stop the polling daemon and release the instance lock.
 */
export function stopDaemon(): void {
  _running = false;
  if (_pollTimer) {
    clearTimeout(_pollTimer as unknown as ReturnType<typeof setTimeout>);
    _pollTimer = null;
  }
  if (_pollAbort) {
    _pollAbort.abort();
    _pollAbort = null;
  }
  releaseLock();
  log.info('Stopped');
}

export function isDaemonRunning(): boolean {
  return _running;
}
