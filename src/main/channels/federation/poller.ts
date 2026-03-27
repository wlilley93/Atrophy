// src/main/channels/federation/poller.ts
import { post } from '../telegram/api';
import { getConfig } from '../../config';
import { switchboard } from '../switchboard';
import { createLogger } from '../../logger';
import type { FederationLink } from './config';
import { appendTranscript } from './transcript';

const log = createLogger('federation-poller');

const POLL_INTERVAL_MS = 5000;
const STALENESS_WINDOW_MS = 60 * 60 * 1000; // 1 hour
const INBOUND_RATE_LIMIT = 60; // per hour

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

    // Inbound rate limiting
    const now = Date.now();
    if (now - state.inboundWindowStart > 3600_000) {
      state.inboundCount = 0;
      state.inboundWindowStart = now;
    }
    state.inboundCount++;
    if (state.inboundCount > INBOUND_RATE_LIMIT) {
      log.warn(`[${state.linkName}] Inbound rate limit exceeded (${state.inboundCount}/${INBOUND_RATE_LIMIT}/hr)`);
      continue;
    }

    // Muted - log but don't process
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

    // Strip the @ mention from the text before processing
    const cleanText = msg.text.replace(new RegExp(`@${state.localBotUsername}\\s*`, 'gi'), '').trim();
    if (!cleanText) continue;

    log.info(`[${state.linkName}] Inbound from @${state.link.remote_bot_username}: "${cleanText.slice(0, 80)}"`);

    // Create and route the envelope
    const envelope = switchboard.createEnvelope(
      `federation:${state.linkName}`,
      `agent:${state.link.local_agent}`,
      cleanText,
      {
        type: 'user',
        priority: 'normal',
        replyTo: `federation:${state.linkName}`,
        metadata: {
          telegramMessageId: msg.message_id,
          remoteBotUsername: state.link.remote_bot_username,
          linkName: state.linkName,
          trustTier: state.link.trust_tier,
        },
      },
    );
    // Attach federation field (not part of createEnvelope defaults)
    (envelope as any).federation = {
      linkName: state.linkName,
      remoteBotUsername: state.link.remote_bot_username,
      trustTier: state.link.trust_tier,
    };

    // Dispatch to inference via switchboard
    // The response handler (registered in index.ts) handles outbound
    try {
      await switchboard.route(envelope);
    } catch (e) {
      log.error(`[${state.linkName}] Failed to route envelope: ${e}`);
    }
  }
}

/**
 * Send a response to the federation group.
 * Called by the switchboard handler when the agent produces a response.
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

  // Get bot token for the local agent
  const config = getConfig();
  const originalAgent = config.AGENT_NAME;
  config.reloadForAgent(state.link.local_agent);
  const botToken = config.TELEGRAM_BOT_TOKEN;
  config.reloadForAgent(originalAgent);

  if (!botToken) {
    log.error(`[${linkName}] No bot token - cannot send response`);
    return;
  }

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
