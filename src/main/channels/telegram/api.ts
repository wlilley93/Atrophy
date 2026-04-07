/**
 * Telegram channel - send and receive via Bot API.
 * Port of channels/telegram.py.
 *
 * Uses inline keyboards for confirmations/permissions and polls for
 * text replies. Pure HTTP via fetch - no webhooks, no extra dependencies.
 */

import * as crypto from 'crypto';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { getConfig } from '../../config';
import { createLogger } from '../../logger';

const log = createLogger('telegram');

// Track last processed update to avoid re-reading old ones.
// Per-bot offset keyed by bot token to prevent cross-agent stomping.
const _lastUpdateIds = new Map<string, number>();

function getOffset(botToken?: string): number {
  return _lastUpdateIds.get(botToken || getConfig().TELEGRAM_BOT_TOKEN) || 0;
}

function setOffset(updateId: number, botToken?: string): void {
  const key = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  const cur = _lastUpdateIds.get(key) || 0;
  if (updateId > cur) _lastUpdateIds.set(key, updateId);
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

function apiUrl(method: string, botToken?: string): string {
  const token = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  return `https://api.telegram.org/bot${token}/${method}`;
}

const MAX_RETRIES = 3;

// Sentinel for internal use: distinguishes network errors from API errors.
// Only used by the markdown fallback functions - post() returns null to external callers.
const NETWORK_ERROR = Symbol('network_error');

async function _post(method: string, payload: Record<string, unknown>, timeoutMs = 15_000, botToken?: string): Promise<unknown | null | typeof NETWORK_ERROR> {
  const token = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  if (!token) {
    log.warn('TELEGRAM_BOT_TOKEN not configured');
    return null;
  }

  // Long-poll requests (getUpdates with timeout) need a longer fetch timeout
  const pollTimeout = (payload.timeout as number) || 0;
  const fetchTimeout = pollTimeout > 0 ? (pollTimeout + 10) * 1000 : timeoutMs;

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const resp = await fetch(apiUrl(method, botToken), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(fetchTimeout),
      });

      const data = await resp.json() as {
        ok: boolean;
        result?: unknown;
        description?: string;
        parameters?: { retry_after?: number };
      };

      if (data.ok) return data.result ?? null;

      // Flood control - Telegram asks us to wait
      if (resp.status === 429 && data.parameters?.retry_after) {
        const wait = data.parameters.retry_after;
        if (wait > 30) {
          log.warn(`Rate limited for ${wait}s - dropping ${method}`);
          return NETWORK_ERROR; // Prevent markdown-fallback retry
        }
        log.debug(`Rate limited - waiting ${wait}s before retry`);
        await new Promise((r) => setTimeout(r, wait * 1000));
        continue;
      }

      // "message is not modified" is not a real error - happens when editing
      // with identical content. Return success.
      if (data.description?.includes('message is not modified')) {
        return data.result ?? {};
      }

      // Markdown parse failures are expected when agent output contains
      // unbalanced markdown. The caller (postWithMarkdownFallback) will retry
      // without parse_mode, so this is recoverable noise, not a real error.
      const desc = data.description || '';
      if (desc.includes("can't parse entities") || desc.includes('Bad Request: can\'t parse')) {
        log.debug(`Markdown parse failed (will retry plain): ${desc.slice(0, 100)}`);
        return null;
      }

      log.error(`API error: ${desc || JSON.stringify(data)}`);
      return null;
    } catch (e) {
      if (attempt < MAX_RETRIES - 1) {
        log.debug(`${method} attempt ${attempt + 1} failed: ${e} - retrying`);
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        continue;
      }
      log.error(`${method} failed after ${MAX_RETRIES} attempts: ${e}`);
      return NETWORK_ERROR;
    }
  }

  return null;
}

/** Public wrapper - strips the internal NETWORK_ERROR sentinel for external callers. */
export async function post(method: string, payload: Record<string, unknown>, timeoutMs = 15_000, botToken?: string): Promise<unknown | null> {
  const result = await _post(method, payload, timeoutMs, botToken);
  return result === NETWORK_ERROR ? null : result;
}

/**
 * Send a message with Markdown, falling back to plain text if Markdown parsing fails.
 */
async function postWithMarkdownFallback(
  payload: Record<string, unknown>,
  botToken?: string,
): Promise<unknown | null> {
  // Try with Markdown first (use _post to get network error distinction)
  const result = await _post('sendMessage', payload, 15_000, botToken);
  if (result !== null && result !== NETWORK_ERROR) return result;

  // Don't retry without Markdown if the failure was a network error -
  // retrying the same request won't help if the network is down.
  if (result === NETWORK_ERROR) return null;

  // API error (likely Markdown parse failure) - retry without parse_mode
  const plainPayload = { ...payload };
  delete plainPayload.parse_mode;
  log.debug('Send failed - retrying without Markdown');
  const fallback = await _post('sendMessage', plainPayload, 15_000, botToken);
  return fallback === NETWORK_ERROR ? null : fallback;
}

/**
 * Edit a message with Markdown, falling back to plain text if Markdown parsing fails.
 */
async function editWithMarkdownFallback(
  payload: Record<string, unknown>,
  botToken?: string,
): Promise<unknown | null> {
  const result = await _post('editMessageText', payload, 15_000, botToken);
  if (result !== null && result !== NETWORK_ERROR) return result;

  if (result === NETWORK_ERROR) return null;

  const plainPayload = { ...payload };
  delete plainPayload.parse_mode;
  const fallback = await _post('editMessageText', plainPayload, 15_000, botToken);
  return fallback === NETWORK_ERROR ? null : fallback;
}

// ---------------------------------------------------------------------------
// Sending
// ---------------------------------------------------------------------------

export async function sendMessage(
  text: string,
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<boolean> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) {
    log.warn('TELEGRAM_CHAT_ID not configured');
    return false;
  }

  if (prefix && config.TELEGRAM_EMOJI) {
    text = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${text}`;
  }

  // Telegram has a 4096 character limit per message - split if needed
  const MAX_LEN = 4096;
  if (text.length <= MAX_LEN) {
    const payload: Record<string, unknown> = {
      chat_id: target,
      text,
      parse_mode: 'Markdown',
    };
    const result = await postWithMarkdownFallback(payload, botToken);
    if (result) {
      log.debug(`Sent message (${text.length} chars)`);
      return true;
    }
    return false;
  }

  // Split on paragraph boundaries, falling back to character limit
  let remaining = text;
  let allSent = true;
  while (remaining.length > 0) {
    let chunk: string;
    if (remaining.length <= MAX_LEN) {
      chunk = remaining;
      remaining = '';
    } else {
      // Try to split at a paragraph boundary
      let splitAt = remaining.lastIndexOf('\n\n', MAX_LEN);
      if (splitAt < MAX_LEN / 2) splitAt = remaining.lastIndexOf('\n', MAX_LEN);
      if (splitAt <= 0) splitAt = MAX_LEN;
      chunk = remaining.slice(0, splitAt);
      remaining = remaining.slice(splitAt).trimStart();
    }
    const payload: Record<string, unknown> = {
      chat_id: target,
      text: chunk,
      parse_mode: 'Markdown',
    };
    const result = await postWithMarkdownFallback(payload, botToken);
    if (!result) allSent = false;
  }
  log.debug(`Sent message (${text.length} chars, split)`);
  return allSent;
}

/**
 * Send a message and return the message_id (needed for later edits).
 * Returns null on failure.
 */
export async function sendMessageGetId(
  text: string,
  chatId = '',
  botToken?: string,
): Promise<number | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) {
    log.warn('TELEGRAM_CHAT_ID not configured');
    return null;
  }

  const payload: Record<string, unknown> = {
    chat_id: target,
    text,
    parse_mode: 'Markdown',
  };

  const result = await postWithMarkdownFallback(payload, botToken) as { message_id?: number } | null;
  return result?.message_id ?? null;
}

/**
 * Edit an existing message's text in-place.
 * Returns true on success.
 */
export async function editMessage(
  messageId: number,
  text: string,
  chatId = '',
  botToken?: string,
): Promise<boolean> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) return false;

  // Telegram max message length
  if (text.length > 4096) {
    text = text.slice(0, 4093) + '...';
  }

  const payload: Record<string, unknown> = {
    chat_id: target,
    message_id: messageId,
    text,
    parse_mode: 'Markdown',
  };

  const result = await editWithMarkdownFallback(payload, botToken);
  return result !== null;
}

/**
 * Delete a message by ID. Used to clean up orphaned "Thinking..." indicators
 * when inference produces no response.
 */
export async function deleteMessage(
  messageId: number,
  chatId: string,
  botToken?: string,
): Promise<boolean> {
  const result = await post('deleteMessage', { chat_id: chatId, message_id: messageId }, 15_000, botToken);
  return result !== null;
}

/**
 * Send a chat action (e.g. "typing") to show activity indicator.
 * Action persists for ~5 seconds or until a message is sent.
 */
export async function sendChatAction(
  action: string,
  chatId: string,
  botToken?: string,
): Promise<boolean> {
  const result = await post('sendChatAction', { chat_id: chatId, action }, 5_000, botToken);
  return result !== null;
}

export async function sendButtons(
  text: string,
  buttons: { text: string; callback_data: string }[][],
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<number | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) {
    log.warn('TELEGRAM_CHAT_ID not configured');
    return null;
  }

  if (prefix && config.TELEGRAM_EMOJI) {
    text = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${text}`;
  }

  const payload: Record<string, unknown> = {
    chat_id: target,
    text,
    parse_mode: 'Markdown',
    reply_markup: { inline_keyboard: buttons },
  };
  const result = await post('sendMessage', payload, 15_000, botToken) as { message_id?: number } | null;

  if (result) {
    log.debug(`Sent buttons (${text.length} chars)`);
    return result.message_id ?? null;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Multipart helper
// ---------------------------------------------------------------------------

/**
 * Build a multipart/form-data body buffer for file uploads.
 *
 * @param fields - String key-value pairs (chat_id, caption, parse_mode, etc.)
 * @param fileField - The file to upload: { name: form field name, path: local file path, contentType: MIME type }
 * @param boundary - The multipart boundary string
 * @returns Buffer ready to use as fetch body
 */
function buildMultipartBody(
  fields: Record<string, string>,
  fileField: { name: string; path: string; contentType: string },
  boundary: string,
): Buffer {
  const parts: Buffer[] = [];

  // Add string fields
  for (const [key, value] of Object.entries(fields)) {
    parts.push(Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="${key}"\r\n\r\n${value}\r\n`,
    ));
  }

  // Add file field
  const fileData = fs.readFileSync(fileField.path);
  const filename = path.basename(fileField.path);
  parts.push(Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="${fileField.name}"; filename="${filename}"\r\n` +
    `Content-Type: ${fileField.contentType}\r\n\r\n`,
  ));
  parts.push(fileData);
  parts.push(Buffer.from(`\r\n--${boundary}--\r\n`));

  return Buffer.concat(parts);
}

/**
 * Shared logic for sending a file via any Telegram upload method.
 */
async function sendFileUpload(
  method: string,
  fieldName: string,
  filePath: string,
  contentType: string,
  caption: string,
  chatId: string,
  prefix: boolean,
  botToken?: string,
  timeoutMs = 30_000,
): Promise<boolean> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) {
    log.warn('TELEGRAM_CHAT_ID not configured');
    return false;
  }

  if (prefix && config.TELEGRAM_EMOJI && caption) {
    caption = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${caption}`;
  }

  try {
    const boundary = `----FormBoundary${crypto.randomBytes(16).toString('hex')}`;

    const fields: Record<string, string> = { chat_id: target };
    if (caption) {
      fields.caption = caption;
      fields.parse_mode = 'Markdown';
    }

    const body = buildMultipartBody(fields, { name: fieldName, path: filePath, contentType }, boundary);

    const resp = await fetch(apiUrl(method, botToken), {
      method: 'POST',
      headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` },
      body,
      signal: AbortSignal.timeout(timeoutMs),
    });

    const result = await resp.json() as { ok: boolean };
    if (result.ok) {
      log.debug(`Sent ${method} (${fs.statSync(filePath).size} bytes)`);
      return true;
    }
    log.error(`${method} error: ${JSON.stringify(result)}`);
    return false;
  } catch (e) {
    log.error(`${method} error: ${e}`);
    return false;
  }
}

// ---------------------------------------------------------------------------
// File sending functions
// ---------------------------------------------------------------------------

export async function sendVoiceNote(
  audioPath: string,
  caption = '',
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<boolean> {
  const isOgg = audioPath.endsWith('.ogg') || audioPath.endsWith('.oga');
  const method = isOgg ? 'sendVoice' : 'sendAudio';
  const fieldName = isOgg ? 'voice' : 'audio';
  const contentType = isOgg ? 'audio/ogg' : 'audio/mpeg';

  return sendFileUpload(method, fieldName, audioPath, contentType, caption, chatId, prefix, botToken);
}

export async function sendPhoto(
  filePath: string,
  caption = '',
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<boolean> {
  // Detect content type from extension
  const ext = path.extname(filePath).toLowerCase();
  const mimeMap: Record<string, string> = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
  };
  const contentType = mimeMap[ext] || 'image/jpeg';

  return sendFileUpload('sendPhoto', 'photo', filePath, contentType, caption, chatId, prefix, botToken);
}

export async function sendVideo(
  filePath: string,
  caption = '',
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<boolean> {
  const ext = path.extname(filePath).toLowerCase();
  const mimeMap: Record<string, string> = {
    '.mp4': 'video/mp4',
    '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo',
    '.webm': 'video/webm',
    '.mkv': 'video/x-matroska',
  };
  const contentType = mimeMap[ext] || 'video/mp4';

  // Videos can be large - allow 60s timeout
  return sendFileUpload('sendVideo', 'video', filePath, contentType, caption, chatId, prefix, botToken, 60_000);
}

export async function sendDocument(
  filePath: string,
  caption = '',
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<boolean> {
  return sendFileUpload('sendDocument', 'document', filePath, 'application/octet-stream', caption, chatId, prefix, botToken);
}

/**
 * Send text content as a document file. Writes content to a temp file,
 * sends it via sendDocument, then cleans up.
 *
 * Useful for code blocks, HTML artefacts, structured data, etc.
 */
export async function sendArtefact(
  content: string,
  filename: string,
  caption = '',
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<boolean> {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'atrophy-artefact-'));
  const tmpPath = path.join(tmpDir, filename);

  try {
    fs.writeFileSync(tmpPath, content, 'utf-8');
    return await sendDocument(tmpPath, caption, chatId, prefix, botToken);
  } finally {
    try { fs.unlinkSync(tmpPath); } catch { /* ignore */ }
    try { fs.rmdirSync(tmpDir); } catch { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// File downloading (for receiving media)
// ---------------------------------------------------------------------------

/**
 * Download a file from Telegram's servers using a file_id.
 *
 * Calls getFile to get the file_path, then downloads from the file API.
 * Creates destDir if it does not exist.
 *
 * @param fileId - Telegram file_id
 * @param destDir - Local directory to save the file
 * @param filename - Optional filename override (defaults to Telegram's filename)
 * @returns Local file path on success, null on failure
 */
export async function downloadTelegramFile(
  fileId: string,
  destDir: string,
  filename?: string,
  botToken?: string,
): Promise<string | null> {
  const config = getConfig();
  const token = botToken || config.TELEGRAM_BOT_TOKEN;
  if (!token) {
    log.warn('TELEGRAM_BOT_TOKEN not configured');
    return null;
  }

  try {
    // Step 1: call getFile to get the file_path
    const fileInfo = await post('getFile', { file_id: fileId }, 15_000, botToken) as {
      file_id: string;
      file_path?: string;
      file_size?: number;
    } | null;

    if (!fileInfo?.file_path) {
      log.error(`getFile failed for file_id ${fileId}`);
      return null;
    }

    // Step 2: download the file
    const downloadUrl = `https://api.telegram.org/file/bot${token}/${fileInfo.file_path}`;
    const resp = await fetch(downloadUrl, {
      signal: AbortSignal.timeout(60_000),
    });

    if (!resp.ok) {
      log.error(`File download failed: ${resp.status} ${resp.statusText}`);
      return null;
    }

    // Determine the local filename
    const remoteName = path.basename(fileInfo.file_path);
    const localName = filename || remoteName;

    // Ensure destination directory exists
    fs.mkdirSync(destDir, { recursive: true });

    const destPath = path.join(destDir, localName);
    const arrayBuffer = await resp.arrayBuffer();
    fs.writeFileSync(destPath, Buffer.from(arrayBuffer));

    log.debug(`Downloaded file to ${destPath} (${arrayBuffer.byteLength} bytes)`);
    return destPath;
  } catch (e) {
    log.error(`File download error: ${e}`);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Receiving
// ---------------------------------------------------------------------------

async function flushOldUpdates(botToken?: string): Promise<void> {
  const result = await post('getUpdates', { offset: getOffset(botToken) + 1, timeout: 0 }, undefined, botToken) as
    { update_id: number }[] | null;
  if (result) {
    for (const update of result) {
      setOffset(update.update_id, botToken);
    }
  }
}

export async function pollCallback(
  timeoutSecs = 120,
  chatId = '',
  botToken?: string,
): Promise<string | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  const deadline = Date.now() + timeoutSecs * 1000;

  let retryDelay = 2000;
  while (Date.now() < deadline) {
    const remaining = Math.max(1, Math.floor((deadline - Date.now()) / 1000));
    const pollTime = Math.min(remaining, 30);

    const raw = await post('getUpdates', {
      offset: getOffset(botToken) + 1,
      timeout: pollTime,
      allowed_updates: ['callback_query', 'message'],
    }, (pollTime + 10) * 1000, botToken);
    const result = Array.isArray(raw) ? raw as { update_id: number; callback_query?: { id: string; from?: { id: number }; data?: string } }[] : null;

    if (!result) {
      await new Promise((r) => setTimeout(r, retryDelay));
      retryDelay = Math.min(retryDelay * 1.5, 30_000); // backoff up to 30s
      continue;
    }
    retryDelay = 2000; // reset on success

    for (const update of result) {
      setOffset(update.update_id, botToken);

      const cb = update.callback_query;
      // Match on chat ID (works for both groups and DMs) or fall back to user ID
      const cbChatId = String((cb as any)?.message?.chat?.id ?? '');
      const cbUserId = String(cb?.from?.id ?? '');
      if (cb && (cbChatId === target || cbUserId === target)) {
        await post('answerCallbackQuery', { callback_query_id: cb.id }, 15_000, botToken);
        return cb.data ?? null;
      }
    }
  }

  return null;
}

export async function pollReply(
  timeoutSecs = 120,
  chatId = '',
  botToken?: string,
): Promise<string | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  const deadline = Date.now() + timeoutSecs * 1000;

  let retryDelay = 2000;
  while (Date.now() < deadline) {
    const remaining = Math.max(1, Math.floor((deadline - Date.now()) / 1000));
    const pollTime = Math.min(remaining, 30);

    const raw = await post('getUpdates', {
      offset: getOffset(botToken) + 1,
      timeout: pollTime,
      allowed_updates: ['message'],
    }, (pollTime + 10) * 1000, botToken);
    const result = Array.isArray(raw) ? raw as { update_id: number; message?: { from?: { id: number }; text?: string } }[] : null;

    if (!result) {
      await new Promise((r) => setTimeout(r, retryDelay));
      retryDelay = Math.min(retryDelay * 1.5, 30_000);
      continue;
    }
    retryDelay = 2000;

    for (const update of result) {
      setOffset(update.update_id, botToken);

      const msg = update.message;
      // Match on chat ID (works for both groups and DMs) or fall back to user ID
      const msgChatId = String((msg as any)?.chat?.id ?? '');
      const msgUserId = String(msg?.from?.id ?? '');
      if (msg && (msgChatId === target || msgUserId === target) && msg.text) {
        return msg.text;
      }
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// High-level: ask and wait
// ---------------------------------------------------------------------------

export async function askConfirm(text: string, timeoutSecs = 120): Promise<boolean | null> {
  await flushOldUpdates();

  const buttons = [[
    { text: 'Yes', callback_data: 'yes' },
    { text: 'No', callback_data: 'no' },
  ]];
  const msgId = await sendButtons(text, buttons);
  if (!msgId) return null;

  const response = await pollCallback(timeoutSecs);
  if (response === 'yes') return true;
  if (response === 'no') return false;
  return null;
}

export async function askQuestion(text: string, timeoutSecs = 120): Promise<string | null> {
  await flushOldUpdates();
  if (!(await sendMessage(text))) return null;
  return pollReply(timeoutSecs);
}

// ---------------------------------------------------------------------------
// Bot command registration
// ---------------------------------------------------------------------------

interface BotCommand {
  command: string;
  description: string;
}

function buildCommands(): BotCommand[] {
  // Per-agent bots - each agent has its own bot, only utility commands needed.
  return [
    { command: 'status', description: 'Show which agents are active' },
  ];
}

/**
 * Register bot commands with the Telegram API (setMyCommands).
 * Scans all discovered agents and registers /agent_name commands
 * plus utility commands (/status, /mute) for autocomplete.
 *
 * Returns true on success, false on failure.
 */
export async function registerBotCommands(): Promise<boolean> {
  const config = getConfig();
  if (!config.TELEGRAM_BOT_TOKEN) {
    log.warn('Cannot register commands - TELEGRAM_BOT_TOKEN not configured');
    return false;
  }

  const commands = buildCommands();
  log.info(`Registering ${commands.length} bot commands`);

  const result = await post('setMyCommands', { commands });
  if (result !== null) {
    log.info('Bot commands registered successfully');
    return true;
  }

  log.error('Failed to register bot commands');
  return false;
}

/**
 * Remove all bot commands from the Telegram API (deleteMyCommands).
 *
 * Returns true on success, false on failure.
 */
export async function clearBotCommands(): Promise<boolean> {
  const config = getConfig();
  if (!config.TELEGRAM_BOT_TOKEN) {
    log.warn('Cannot clear commands - TELEGRAM_BOT_TOKEN not configured');
    return false;
  }

  const result = await post('deleteMyCommands', {});
  if (result !== null) {
    log.info('Bot commands cleared');
    return true;
  }

  log.error('Failed to clear bot commands');
  return false;
}

// ---------------------------------------------------------------------------
// Chat ID auto-discovery
// ---------------------------------------------------------------------------

/**
 * Discover the user's chat ID by polling for incoming messages.
 *
 * After the user pastes a bot token, they need to send any message to the bot
 * (e.g. /start) so we can capture their chat ID. This polls getUpdates for up
 * to `timeoutSecs` waiting for the first message, then returns the sender's
 * chat ID.
 *
 * Also sends a greeting once the chat ID is captured so the user knows it worked.
 */
export async function discoverChatId(
  botToken: string,
  timeoutSecs = 120,
): Promise<{ chatId: string; username?: string } | null> {
  const url = (method: string) => `https://api.telegram.org/bot${botToken}/${method}`;

  // Flush old updates first
  let offset = 0;
  try {
    const flushResp = await fetch(url('getUpdates'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ offset: 0, timeout: 0 }),
      signal: AbortSignal.timeout(10_000),
    });
    const flushData = await flushResp.json() as { ok: boolean; result?: { update_id: number }[] };
    if (flushData.ok && flushData.result?.length) {
      offset = Math.max(...flushData.result.map((u) => u.update_id)) + 1;
    }
  } catch { /* proceed with offset 0 */ }

  // Poll for new messages
  const deadline = Date.now() + timeoutSecs * 1000;

  while (Date.now() < deadline) {
    const remaining = Math.max(1, Math.floor((deadline - Date.now()) / 1000));
    const pollTime = Math.min(remaining, 30);

    try {
      const resp = await fetch(url('getUpdates'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          offset,
          timeout: pollTime,
          allowed_updates: ['message'],
        }),
        signal: AbortSignal.timeout((pollTime + 5) * 1000),
      });

      const data = await resp.json() as {
        ok: boolean;
        result?: {
          update_id: number;
          message?: {
            from?: { id: number; username?: string; first_name?: string };
            chat?: { id: number };
            text?: string;
          };
        }[];
      };

      if (!data.ok || !data.result) continue;

      for (const update of data.result) {
        offset = Math.max(offset, update.update_id + 1);

        const msg = update.message;
        if (msg?.from?.id) {
          const chatId = String(msg.chat?.id || msg.from.id);
          const username = msg.from.username || msg.from.first_name || '';

          // Send a greeting to confirm the connection
          try {
            await fetch(url('sendMessage'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                chat_id: chatId,
                text: `Connected. Chat ID captured: \`${chatId}\``,
                parse_mode: 'Markdown',
              }),
              signal: AbortSignal.timeout(10_000),
            });
          } catch { /* greeting is non-critical */ }

          log.info(`Chat ID discovered: ${chatId} (user: ${username})`);
          return { chatId, username };
        }
      }
    } catch {
      // Network error - wait and retry
      await new Promise((r) => setTimeout(r, 2000));
    }
  }

  log.warn('Chat ID discovery timed out');
  return null;
}

/**
 * Set the bot's profile photo from a local image file.
 */
export async function setBotProfilePhoto(photoPath: string, botToken?: string): Promise<boolean> {
  const token = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  if (!token) return false;

  try {
    const boundary = `----FormBoundary${crypto.randomBytes(16).toString('hex')}`;
    const body = buildMultipartBody({}, { name: 'photo', path: photoPath, contentType: 'image/png' }, boundary);

    const resp = await fetch(apiUrl('setMyProfilePhoto', token), {
      method: 'POST',
      headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` },
      body,
      signal: AbortSignal.timeout(30_000),
    });

    const result = await resp.json() as { ok: boolean };
    if (result.ok) {
      log.info('Bot profile photo updated');
      return true;
    }
    log.warn(`setMyProfilePhoto failed: ${JSON.stringify(result)}`);
    return false;
  } catch (e) {
    log.warn(`setMyProfilePhoto error: ${e}`);
    return false;
  }
}

// Export for daemon access
export { _lastUpdateIds, apiUrl };
export function setLastUpdateId(id: number, botToken?: string): void {
  setOffset(id, botToken);
}
