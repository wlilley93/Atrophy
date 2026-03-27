// src/main/channels/federation/poller.ts
import { post, sendMessage as telegramSend } from '../telegram/api';
import { getConfig } from '../../config';
import { createLogger } from '../../logger';
import type { FederationLink } from './config';
import { appendTranscript } from './transcript';
import { buildSandboxedMcpConfig, buildFederationPreamble, sanitizeFederationContent } from './sandbox';
import { streamInference, stopInference, setMcpConfigPath, resetMcpConfig, type InferenceEvent } from '../../inference';
import { loadSystemPrompt } from '../../context';
import * as memory from '../../memory';

const log = createLogger('federation-poller');

const POLL_INTERVAL_MS = 5000;
const STALENESS_WINDOW_MS = 60 * 60 * 1000; // 1 hour
const INBOUND_RATE_LIMIT = 60; // per hour
const FEDERATION_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

interface PollerState {
  linkName: string;
  link: FederationLink;
  lastUpdateId: number;
  timer: ReturnType<typeof setTimeout> | null;
  running: boolean;
  inboundCount: number;
  inboundWindowStart: number;
  outboundCount: number;
  outboundWindowStart: number;
  localBotUsername: string | null;
  botToken: string;
}

const _pollers = new Map<string, PollerState>();

/**
 * Get the local bot's username (cached per link since it requires an API call).
 */
async function getLocalBotUsername(botToken: string): Promise<string | null> {
  const result = await post('getMe', {}, 10_000, botToken) as { username?: string } | null;
  return result?.username || null;
}

/**
 * Start a federation poller for a single link.
 */
export async function startPoller(linkName: string, link: FederationLink): Promise<void> {
  if (_pollers.has(linkName)) {
    log.warn(`Poller for ${linkName} already running`);
    return;
  }

  // Resolve the local bot token from the agent's config
  const config = getConfig();
  const originalAgent = config.AGENT_NAME;
  config.reloadForAgent(link.local_agent);
  const botToken = config.TELEGRAM_BOT_TOKEN;
  config.reloadForAgent(originalAgent);

  if (!botToken) {
    log.error(`[${linkName}] No bot token for agent "${link.local_agent}" - cannot start poller`);
    return;
  }

  const localBotUsername = await getLocalBotUsername(botToken);
  if (!localBotUsername) {
    log.error(`[${linkName}] Could not resolve local bot username - cannot start poller`);
    return;
  }

  const state: PollerState = {
    linkName,
    link,
    lastUpdateId: 0,
    timer: null,
    running: true,
    inboundCount: 0,
    inboundWindowStart: Date.now(),
    outboundCount: 0,
    outboundWindowStart: Date.now(),
    localBotUsername,
    botToken,
  };

  _pollers.set(linkName, state);

  // Flush old updates on first poll to avoid processing stale messages
  await flushOldUpdates(state, botToken);

  // Start polling loop
  pollLoop(state, botToken);
  log.info(`[${linkName}] Poller started (remote: @${link.remote_bot_username}, group: ${link.telegram_group_id})`);
}

/**
 * Stop a federation poller.
 */
export function stopPoller(linkName: string): void {
  const state = _pollers.get(linkName);
  if (!state) return;
  state.running = false;
  if (state.timer) clearTimeout(state.timer);
  _pollers.delete(linkName);
  log.info(`[${linkName}] Poller stopped`);
}

/**
 * Stop all federation pollers.
 */
export function stopAllPollers(): void {
  for (const [name] of _pollers) {
    stopPoller(name);
  }
}

/**
 * Get all active poller names.
 */
export function getActivePollers(): string[] {
  return Array.from(_pollers.keys());
}

/**
 * Flush old updates so we start from the latest offset.
 */
async function flushOldUpdates(state: PollerState, botToken: string): Promise<void> {
  try {
    const result = await post('getUpdates', {
      offset: -1,
      limit: 1,
      timeout: 0,
    }, 10_000, botToken) as Array<{ update_id: number }> | null;

    if (result && result.length > 0) {
      state.lastUpdateId = result[result.length - 1].update_id;
    }
  } catch (e) {
    log.warn(`[${state.linkName}] Failed to flush old updates: ${e}`);
  }
}

/**
 * Main polling loop. Schedules itself via setTimeout.
 */
function pollLoop(state: PollerState, botToken: string): void {
  if (!state.running) return;

  pollOnce(state, botToken)
    .catch((e) => log.error(`[${state.linkName}] Poll error: ${e}`))
    .finally(() => {
      if (state.running) {
        state.timer = setTimeout(() => pollLoop(state, botToken), POLL_INTERVAL_MS);
      }
    });
}

// ---------------------------------------------------------------------------
// Config mutex - narrow lock so federation inference doesn't race with
// other dispatches that also call config.reloadForAgent().
// ---------------------------------------------------------------------------

let _federationConfigQueue: Promise<void> = Promise.resolve();

function withFederationConfigLock<T>(fn: () => Promise<T>): Promise<T> {
  let resolve: () => void;
  const next = new Promise<void>((r) => { resolve = r; });
  const prev = _federationConfigQueue;
  _federationConfigQueue = next;
  return prev.then(async () => {
    try {
      return await fn();
    } finally {
      resolve!();
      if (_federationConfigQueue === next) {
        _federationConfigQueue = Promise.resolve();
      }
    }
  });
}

/**
 * Run sandboxed inference for a federation message and return the response text.
 * Returns null if inference produced no output or timed out.
 */
interface FederationDispatchResult {
  responseText: string | null;
  ownerChatId: string | null;
  ownerBotToken: string | null;
}

async function dispatchFederationInference(
  state: PollerState,
  cleanText: string,
): Promise<FederationDispatchResult> {
  const { linkName, link } = state;
  const config = getConfig();
  const originalAgent = config.AGENT_NAME;

  const sessionId = `federation-${linkName}`;

  const sanitized = sanitizeFederationContent(cleanText);
  const preamble = buildFederationPreamble(linkName, link.remote_bot_username, link.trust_tier);

  // Narrow config lock - hold only while reloading and spawning the subprocess.
  // Also capture notification credentials while config is loaded for the right agent.
  const { emitter, ownerChatId, ownerBotToken } = await withFederationConfigLock(async () => {
    config.reloadForAgent(link.local_agent);
    memory.initDb();

    // Capture notification credentials while config is loaded
    const chatId = config.TELEGRAM_DM_CHAT_ID || config.TELEGRAM_CHAT_ID;
    const botToken = config.TELEGRAM_BOT_TOKEN;

    const sandboxedMcpPath = buildSandboxedMcpConfig(link.local_agent, link.trust_tier);
    setMcpConfigPath(sandboxedMcpPath);

    const baseSystem = loadSystemPrompt();
    const system = preamble + baseSystem;

    // Restore original agent immediately after spawning so the config
    // singleton is not left pointing at the federation agent.
    const emitterInner = streamInference(sanitized, system, sessionId, { source: 'other', processKey: `federation-${linkName}` });

    resetMcpConfig();
    config.reloadForAgent(originalAgent);

    return { emitter: emitterInner, ownerChatId: chatId, ownerBotToken: botToken };
  });

  const responseText = await new Promise<string | null>((resolve) => {
    let fullText = '';
    let settled = false;

    const settle = (result: string | null): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };

    const timer = setTimeout(() => {
      log.warn(`[${linkName}] federation inference timed out`);
      stopInference(`federation-${linkName}`);
      settle(null);
    }, FEDERATION_TIMEOUT_MS);

    emitter.on('event', (evt: InferenceEvent) => {
      switch (evt.type) {
        case 'TextDelta':
          fullText += evt.text;
          break;
        case 'StreamDone':
          settle(evt.fullText?.trim() || fullText.trim() || null);
          break;
        case 'StreamError':
          log.error(`[${linkName}] federation inference error: ${evt.message}`);
          settle(null);
          break;
        default:
          break;
      }
    });
  });

  return { responseText, ownerChatId, ownerBotToken };
}

/**
 * Single poll iteration.
 */
async function pollOnce(state: PollerState, botToken: string): Promise<void> {
  const result = await post('getUpdates', {
    offset: state.lastUpdateId + 1,
    limit: 20,
    timeout: 0,
    allowed_updates: ['message'],
  }, 10_000, botToken) as Array<{
    update_id: number;
    message?: {
      message_id: number;
      from?: { username?: string; is_bot?: boolean };
      chat?: { id: number };
      text?: string;
      date: number;
    };
    edited_message?: unknown;
  }> | null;

  if (!result) return;

  for (const update of result) {
    state.lastUpdateId = update.update_id;

    // Skip edits entirely
    if (update.edited_message) continue;

    const msg = update.message;
    if (!msg) continue;

    // Only process messages from the shared federation group
    if (String(msg.chat?.id) !== state.link.telegram_group_id) continue;

    // Only process messages from the remote bot
    if (!msg.from?.is_bot || msg.from?.username !== state.link.remote_bot_username) continue;

    // Skip non-text messages
    if (!msg.text) {
      appendTranscript(state.linkName, {
        timestamp: new Date().toISOString(),
        direction: 'inbound',
        from_bot: state.link.remote_bot_username,
        to_bot: state.localBotUsername || '',
        text: '[media message skipped]',
        telegram_message_id: msg.message_id,
        inference_triggered: false,
        trust_tier: state.link.trust_tier,
        skipped_reason: 'non-text',
      });
      continue;
    }

    // Skip commands
    if (msg.text.startsWith('/')) continue;

    // Staleness check
    const messageAge = Date.now() - (msg.date * 1000);
    if (messageAge > STALENESS_WINDOW_MS) {
      appendTranscript(state.linkName, {
        timestamp: new Date().toISOString(),
        direction: 'inbound',
        from_bot: state.link.remote_bot_username,
        to_bot: state.localBotUsername || '',
        text: msg.text,
        telegram_message_id: msg.message_id,
        inference_triggered: false,
        trust_tier: state.link.trust_tier,
        skipped_reason: 'stale',
      });
      continue;
    }

    // Check @ mention - must mention local bot to trigger inference
    const mentionPattern = `@${state.localBotUsername}`;
    const isMentioned = msg.text.toLowerCase().includes(mentionPattern.toLowerCase());

    if (!isMentioned) {
      appendTranscript(state.linkName, {
        timestamp: new Date().toISOString(),
        direction: 'inbound',
        from_bot: state.link.remote_bot_username,
        to_bot: state.localBotUsername || '',
        text: msg.text,
        telegram_message_id: msg.message_id,
        inference_triggered: false,
        trust_tier: state.link.trust_tier,
        skipped_reason: 'no-mention',
      });
      continue;
    }

    // Muted - log but don't process (checked before rate limit so muted messages don't consume quota)
    if (state.link.muted) {
      appendTranscript(state.linkName, {
        timestamp: new Date().toISOString(),
        direction: 'inbound',
        from_bot: state.link.remote_bot_username,
        to_bot: state.localBotUsername || '',
        text: msg.text,
        telegram_message_id: msg.message_id,
        inference_triggered: false,
        trust_tier: state.link.trust_tier,
        skipped_reason: 'muted',
      });
      continue;
    }

    // Inbound rate limiting
    const now = Date.now();
    if (now - state.inboundWindowStart > 3600_000) {
      state.inboundCount = 0;
      state.inboundWindowStart = now;
    }
    state.inboundCount++;
    if (state.inboundCount > INBOUND_RATE_LIMIT) {
      log.warn(`[${state.linkName}] Inbound rate limit exceeded (${state.inboundCount}/${INBOUND_RATE_LIMIT}/hr)`);
      appendTranscript(state.linkName, {
        timestamp: new Date().toISOString(),
        direction: 'inbound',
        from_bot: state.link.remote_bot_username,
        to_bot: state.localBotUsername || '',
        text: msg.text,
        telegram_message_id: msg.message_id,
        inference_triggered: false,
        trust_tier: state.link.trust_tier,
        skipped_reason: 'rate-limited',
      });
      continue;
    }

    // Strip the @ mention from the text before processing
    const cleanText = msg.text.replace(new RegExp(`@${state.localBotUsername}\\s*`, 'gi'), '').trim();
    if (!cleanText) continue;

    log.info(`[${state.linkName}] Inbound from @${state.link.remote_bot_username}: "${cleanText.slice(0, 80)}"`);

    // Log inbound message to transcript
    appendTranscript(state.linkName, {
      timestamp: new Date().toISOString(),
      direction: 'inbound',
      from_bot: state.link.remote_bot_username,
      to_bot: state.localBotUsername || '',
      text: cleanText,
      telegram_message_id: msg.message_id,
      inference_triggered: true,
      trust_tier: state.link.trust_tier,
    });

    // Dispatch sandboxed inference directly
    const { responseText, ownerChatId, ownerBotToken } = await dispatchFederationInference(state, cleanText);

    // Send the response back to the federation group if we got one
    if (responseText) {
      await sendFederationResponse(state.linkName, responseText, msg.message_id);
    }

    // Notify the owner about the federation message
    try {
      if (ownerChatId && ownerBotToken) {
        const notif = `[Federation] @${state.link.remote_bot_username} sent a message to ${state.link.local_agent}:\n"${cleanText.slice(0, 200)}"`;
        await telegramSend(notif, ownerChatId, false, ownerBotToken);
      }
    } catch { /* notification is best-effort */ }
  }
}

/**
 * Send a response to the federation group.
 * Called after inference produces a response.
 */
export async function sendFederationResponse(
  linkName: string,
  text: string,
  replyToMessageId?: number,
): Promise<void> {
  const state = _pollers.get(linkName);
  if (!state) {
    log.warn(`Cannot send federation response - no active poller for ${linkName}`);
    return;
  }

  // Outbound rate limiting
  const now = Date.now();
  if (now - state.outboundWindowStart > 3600_000) {
    state.outboundCount = 0;
    state.outboundWindowStart = now;
  }
  state.outboundCount++;
  if (state.outboundCount > state.link.rate_limit_per_hour) {
    log.warn(`[${linkName}] Outbound rate limit exceeded - dropping response`);
    return;
  }

  // Prefix with @ mention of remote bot
  const mentionedText = `@${state.link.remote_bot_username} ${text}`;

  // Use the bot token cached at poller start - no config reload needed
  const botToken = state.botToken;

  // Send as a single complete message (no streaming display)
  const payload: Record<string, unknown> = {
    chat_id: state.link.telegram_group_id,
    text: mentionedText,
  };
  if (replyToMessageId) {
    payload.reply_to_message_id = replyToMessageId;
  }

  await post('sendMessage', payload, 15_000, botToken);

  // Log to transcript
  appendTranscript(linkName, {
    timestamp: new Date().toISOString(),
    direction: 'outbound',
    from_bot: state.localBotUsername || '',
    to_bot: state.link.remote_bot_username,
    text,
    inference_triggered: false,
    trust_tier: state.link.trust_tier,
  });

  log.info(`[${linkName}] Sent response (${text.length} chars)`);
}
