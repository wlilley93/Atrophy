/**
 * Telegram daemon - parallel per-agent pollers.
 *
 * Each agent has its own Telegram bot (own token + chat ID). On startup,
 * discovers all agents with telegram credentials and launches a poller
 * per agent. No group, no topics, no routing - each bot IS the agent.
 *
 * Can run as:
 *   - Continuous loop (KeepAlive daemon)
 *   - Managed from within the Electron main process
 */

import * as fs from 'fs';
import * as path from 'path';
import { spawnSync } from 'child_process';
import { getConfig, USER_DATA, BUNDLE_ROOT } from './config';
import { sendMessage, sendMessageGetId, editMessage, post, downloadTelegramFile, setBotProfilePhoto } from './telegram';
import { discoverAgents, getAgentState } from './agent-manager';
import { streamInference, resetMcpConfig, InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import { getReferenceImages } from './jobs/generate-avatar';
import * as memory from './memory';
import { createLogger } from './logger';

const log = createLogger('telegram-daemon');

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
// Agent dispatch
// ---------------------------------------------------------------------------

const DISPATCH_TIMEOUT_MS = 5 * 60 * 1000; // 5 minute max per agent dispatch

// ---------------------------------------------------------------------------
// Telegram streaming display
// ---------------------------------------------------------------------------

/**
 * Formats a tool name for display - strips MCP prefixes for readability.
 * e.g. "mcp__memory__recall" -> "recall"
 *      "mcp__google__calendar_events" -> "calendar_events"
 */
function formatToolName(name: string): string {
  const parts = name.split('__');
  return parts.length > 2 ? parts.slice(2).join('__') : parts[parts.length - 1];
}

/**
 * Truncate text with ellipsis for display in status lines.
 */
function truncate(text: string, maxLen: number): string {
  const cleaned = text.replace(/\n/g, ' ').trim();
  if (cleaned.length <= maxLen) return cleaned;
  return cleaned.slice(0, maxLen - 1) + '\u2026';
}

/**
 * Build a rich status display for Telegram showing the full inference process.
 *
 * Layout:
 *   [thinking block if present]
 *   [completed tool calls with results]
 *   [active tool call if in progress]
 *   [response text as it streams]
 */
function buildStatusDisplay(state: StreamState): string {
  const parts: string[] = [];

  // Thinking section - show a summary of thinking if present
  if (state.thinkingText) {
    const thinkPreview = truncate(state.thinkingText, 200);
    parts.push(`\u{1f9e0} _${thinkPreview}_`);
  }

  // Completed tool calls with results
  for (const tool of state.completedTools) {
    const name = formatToolName(tool.name);
    const inputPreview = tool.input ? truncate(tool.input, 120) : '';
    const resultPreview = tool.result ? truncate(tool.result, 150) : '';

    let line = `\u2705 \`${name}\``;
    if (inputPreview) line += `  ${inputPreview}`;
    if (resultPreview) line += `\n    \u2192 _${resultPreview}_`;
    parts.push(line);
  }

  // Active tool call (in progress)
  if (state.activeTool) {
    const name = formatToolName(state.activeTool.name);
    const inputPreview = state.activeTool.input ? truncate(state.activeTool.input, 120) : '';
    let line = `\u23f3 \`${name}\``;
    if (inputPreview) line += `  ${inputPreview}`;
    else line += '\u2026';
    parts.push(line);
  }

  // Compacting indicator
  if (state.isCompacting) {
    parts.push('_Compacting context\u2026_');
  }

  // Streamed response text
  if (state.responseText) {
    if (parts.length > 0) parts.push(''); // blank line separator
    parts.push(state.responseText);
  } else if (parts.length === 0) {
    parts.push('_Thinking\u2026_');
  }

  return parts.join('\n');
}

interface ToolCallState {
  name: string;
  id: string;
  input: string;
  result: string;
}

interface StreamState {
  thinkingText: string;
  activeTool: ToolCallState | null;
  completedTools: ToolCallState[];
  responseText: string;
  isCompacting: boolean;
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
): Promise<string | null> {
  const config = getConfig();
  const originalAgent = config.AGENT_NAME;

  // Send initial thinking indicator and capture message_id for edits
  const manifest = getAgentManifest(agentName);
  const emoji = (manifest.telegram_emoji as string) || '';
  const display = (manifest.display_name as string) || agentName.charAt(0).toUpperCase() + agentName.slice(1);
  const header = emoji ? `${emoji} *${display}*\n\n` : '';

  const msgId = await sendMessageGetId(`${header}_Thinking\u2026_`, chatId, botToken);

  try {
    config.reloadForAgent(agentName);
    resetMcpConfig();
    memory.initDb();

    const system = loadSystemPrompt();
    const cliSessionId = memory.getLastCliSessionId();

    const prompt = `[Telegram message from ${config.USER_NAME}]\n\n${text}`;
    let fullText = '';
    const toolsUsed: string[] = [];

    // Rich streaming state
    const state: StreamState = {
      thinkingText: '',
      activeTool: null,
      completedTools: [],
      responseText: '',
      isCompacting: false,
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
      const emitter = streamInference(prompt, system, cliSessionId);

      const timer = setTimeout(() => {
        log.error(`[${agentName}] dispatch timed out after ${DISPATCH_TIMEOUT_MS / 1000}s`);
        reject(new Error('dispatch timeout'));
      }, DISPATCH_TIMEOUT_MS);

      // Periodically flush throttled edits
      const flushTimer = setInterval(async () => {
        if (editPending) {
          await doEdit();
        }
      }, EDIT_INTERVAL_MS);

      emitter.on('event', async (evt: InferenceEvent) => {
        switch (evt.type) {
          case 'ThinkingDelta':
            state.thinkingText += evt.text;
            await doEdit();
            break;

          case 'ToolUse': {
            // If there was a previous active tool, move it to completed
            if (state.activeTool) {
              state.completedTools.push(state.activeTool);
            }
            state.activeTool = {
              name: evt.name,
              id: evt.toolId,
              input: evt.inputJson || '',
              result: '',
            };
            toolsUsed.push(evt.name);
            log.debug(`[${agentName}] tool -> ${evt.name}`);
            await doEdit();
            break;
          }

          case 'ToolInputDelta':
            // Accumulate tool input JSON for the active tool
            if (state.activeTool) {
              state.activeTool.input += evt.delta;
              await doEdit();
            }
            break;

          case 'ToolResult': {
            // Match result to tool and move to completed
            if (state.activeTool) {
              state.activeTool.result = evt.output;
              state.completedTools.push(state.activeTool);
              state.activeTool = null;
            } else {
              // Result for a tool we didn't track - add as completed
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
            // Clear thinking once response starts
            if (state.thinkingText && state.responseText.length < 20) {
              state.thinkingText = '';
            }
            await doEdit();
            break;

          case 'Compacting':
            state.isCompacting = true;
            await doEdit();
            break;

          case 'StreamDone':
            clearTimeout(timer);
            clearInterval(flushTimer);
            state.isCompacting = false;
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

    // Final edit with complete response (clean - no tool/thinking indicators)
    if (finalText && msgId) {
      await editMessage(msgId, `${header}${finalText}`, chatId, botToken);
    } else if (!finalText && msgId) {
      await editMessage(msgId, `${header}_No response_`, chatId, botToken);
    }

    return finalText;
  } catch (e) {
    log.error(`[${agentName}] dispatch failed: ${e}`);
    if (msgId) {
      await editMessage(msgId, `${header}_Error: dispatch failed_`, chatId, botToken);
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
      from?: { id: number };
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
      await handleStatusCommand(msgChatId, agent.botToken);
      continue;
    }

    // Build the prompt from text and/or media
    const promptParts: string[] = [];
    const mediaDir = path.join(USER_DATA, 'agents', agent.name, 'media');

    if (msg.photo && msg.photo.length > 0) {
      // Telegram sends multiple sizes - take the largest (last in array)
      const largest = msg.photo[msg.photo.length - 1];
      const savedPath = await downloadTelegramFile(largest.file_id, mediaDir, undefined, agent.botToken);
      if (savedPath) {
        promptParts.push(`[Telegram photo from Will]\n\n<image saved to: ${savedPath}>`);
      } else {
        promptParts.push('[Telegram photo from Will - download failed]');
      }
    }

    if (msg.voice) {
      const savedPath = await downloadTelegramFile(msg.voice.file_id, mediaDir, undefined, agent.botToken);
      if (savedPath) {
        promptParts.push(`[Telegram voice message from Will]\n\n<voice note saved to: ${savedPath}>`);
      } else {
        promptParts.push('[Telegram voice message from Will - download failed]');
      }
    }

    if (msg.document) {
      const docFilename = msg.document.file_name || undefined;
      const savedPath = await downloadTelegramFile(msg.document.file_id, mediaDir, docFilename, agent.botToken);
      const label = msg.document.file_name ? `Telegram document from Will: ${msg.document.file_name}` : 'Telegram document from Will';
      if (savedPath) {
        promptParts.push(`[${label}]\n\n<file saved to: ${savedPath}>`);
      } else {
        promptParts.push(`[${label} - download failed]`);
      }
    }

    if (msg.video) {
      const savedPath = await downloadTelegramFile(msg.video.file_id, mediaDir, undefined, agent.botToken);
      if (savedPath) {
        promptParts.push(`[Telegram video from Will]\n\n<video saved to: ${savedPath}>`);
      } else {
        promptParts.push('[Telegram video from Will - download failed]');
      }
    }

    // Include text/caption content
    const messageText = text || (msg.caption || '').trim();
    if (messageText) {
      promptParts.push(messageText);
    }

    const fullPrompt = promptParts.join('\n\n');
    if (!fullPrompt) continue;

    log.info(`[${agent.name}] Message: ${fullPrompt.slice(0, 80)}`);

    // Dispatch with live streaming back to Telegram
    const response = await dispatchToAgent(agent.name, fullPrompt, msgChatId, agent.botToken);
    if (response) {
      log.info(`[${agent.name}] Responded (${response.length} chars)`);
    } else {
      log.warn(`[${agent.name}] No response`);
    }
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
        const t = setTimeout(resolve, jitter);
        _pollerTimers.push(t);
      });
    }
  }

  log.info(`[${agent.name}] Poller stopped`);
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

  // Launch all pollers in parallel
  for (const agent of agents) {
    runAgentPoller(agent);
  }

  return true;
}

/**
 * Stop the polling daemon and release the instance lock.
 */
export function stopDaemon(): void {
  _running = false;
  for (const t of _pollerTimers) clearTimeout(t);
  _pollerTimers = [];
  releaseLock();
  log.info('Stopped');
}

export function isDaemonRunning(): boolean {
  return _running;
}
