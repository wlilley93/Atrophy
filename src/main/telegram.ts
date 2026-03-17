/**
 * Telegram channel - send and receive via Bot API.
 * Port of channels/telegram.py.
 *
 * Uses inline keyboards for confirmations/permissions and polls for
 * text replies. Pure HTTP via fetch - no webhooks, no extra dependencies.
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { getConfig } from './config';
import { createLogger } from './logger';

const log = createLogger('telegram');

// Track last processed update to avoid re-reading old ones
let _lastUpdateId = 0;

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

function apiUrl(method: string): string {
  const config = getConfig();
  return `https://api.telegram.org/bot${config.TELEGRAM_BOT_TOKEN}/${method}`;
}

async function post(method: string, payload: Record<string, unknown>, timeoutMs = 15_000): Promise<unknown | null> {
  const config = getConfig();
  if (!config.TELEGRAM_BOT_TOKEN) {
    log.warn('TELEGRAM_BOT_TOKEN not configured');
    return null;
  }

  // Long-poll requests (getUpdates with timeout) need a longer fetch timeout
  const pollTimeout = (payload.timeout as number) || 0;
  const fetchTimeout = pollTimeout > 0 ? (pollTimeout + 10) * 1000 : 15_000;

  try {
    const resp = await fetch(apiUrl(method), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(fetchTimeout),
    });

    const data = await resp.json() as { ok: boolean; result?: unknown; description?: string };
    if (data.ok) return data.result ?? null;

    log.error(`API error: ${data.description || JSON.stringify(data)}`);
    return null;
  } catch (e) {
    log.error(`error: ${e}`);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Sending
// ---------------------------------------------------------------------------

export async function sendMessage(
  text: string,
  chatId = '',
  prefix = true,
  threadId?: number,
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
    if (threadId) payload.message_thread_id = threadId;
    const result = await post('sendMessage', payload);
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
      if (splitAt < MAX_LEN / 2) splitAt = MAX_LEN;
      chunk = remaining.slice(0, splitAt);
      remaining = remaining.slice(splitAt).trimStart();
    }
    const payload: Record<string, unknown> = {
      chat_id: target,
      text: chunk,
      parse_mode: 'Markdown',
    };
    if (threadId) payload.message_thread_id = threadId;
    const result = await post('sendMessage', payload);
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
  threadId?: number,
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
  if (threadId) payload.message_thread_id = threadId;

  const result = await post('sendMessage', payload) as { message_id?: number } | null;
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

  const result = await post('editMessageText', payload);
  return result !== null;
}

export async function sendButtons(
  text: string,
  buttons: { text: string; callback_data: string }[][],
  chatId = '',
  prefix = true,
  threadId?: number,
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
  if (threadId) payload.message_thread_id = threadId;
  const result = await post('sendMessage', payload) as { message_id?: number } | null;

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
  threadId?: number,
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
    const boundary = `----FormBoundary${Date.now()}${Math.random().toString(36).slice(2)}`;

    const fields: Record<string, string> = { chat_id: target };
    if (threadId) fields.message_thread_id = String(threadId);
    if (caption) {
      fields.caption = caption;
      fields.parse_mode = 'Markdown';
    }

    const body = buildMultipartBody(fields, { name: fieldName, path: filePath, contentType }, boundary);

    const resp = await fetch(apiUrl(method), {
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
  threadId?: number,
): Promise<boolean> {
  const isOgg = audioPath.endsWith('.ogg') || audioPath.endsWith('.oga');
  const method = isOgg ? 'sendVoice' : 'sendAudio';
  const fieldName = isOgg ? 'voice' : 'audio';
  const contentType = isOgg ? 'audio/ogg' : 'audio/mpeg';

  return sendFileUpload(method, fieldName, audioPath, contentType, caption, chatId, prefix, threadId);
}

export async function sendPhoto(
  filePath: string,
  caption = '',
  chatId = '',
  prefix = true,
  threadId?: number,
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

  return sendFileUpload('sendPhoto', 'photo', filePath, contentType, caption, chatId, prefix, threadId);
}

export async function sendVideo(
  filePath: string,
  caption = '',
  chatId = '',
  prefix = true,
  threadId?: number,
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
  return sendFileUpload('sendVideo', 'video', filePath, contentType, caption, chatId, prefix, threadId, 60_000);
}

export async function sendDocument(
  filePath: string,
  caption = '',
  chatId = '',
  prefix = true,
  threadId?: number,
): Promise<boolean> {
  return sendFileUpload('sendDocument', 'document', filePath, 'application/octet-stream', caption, chatId, prefix, threadId);
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
  threadId?: number,
): Promise<boolean> {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'atrophy-artefact-'));
  const tmpPath = path.join(tmpDir, filename);

  try {
    fs.writeFileSync(tmpPath, content, 'utf-8');
    return await sendDocument(tmpPath, caption, chatId, prefix, threadId);
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
): Promise<string | null> {
  const config = getConfig();
  if (!config.TELEGRAM_BOT_TOKEN) {
    log.warn('TELEGRAM_BOT_TOKEN not configured');
    return null;
  }

  try {
    // Step 1: call getFile to get the file_path
    const fileInfo = await post('getFile', { file_id: fileId }) as {
      file_id: string;
      file_path?: string;
      file_size?: number;
    } | null;

    if (!fileInfo?.file_path) {
      log.error(`getFile failed for file_id ${fileId}`);
      return null;
    }

    // Step 2: download the file
    const downloadUrl = `https://api.telegram.org/file/bot${config.TELEGRAM_BOT_TOKEN}/${fileInfo.file_path}`;
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

async function flushOldUpdates(): Promise<void> {
  const result = await post('getUpdates', { offset: _lastUpdateId + 1, timeout: 0 }) as
    { update_id: number }[] | null;
  if (result) {
    for (const update of result) {
      _lastUpdateId = Math.max(_lastUpdateId, update.update_id);
    }
  }
}

export async function pollCallback(
  timeoutSecs = 120,
  chatId = '',
): Promise<string | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  const deadline = Date.now() + timeoutSecs * 1000;

  let retryDelay = 2000;
  while (Date.now() < deadline) {
    const remaining = Math.max(1, Math.floor((deadline - Date.now()) / 1000));
    const pollTime = Math.min(remaining, 30);

    const raw = await post('getUpdates', {
      offset: _lastUpdateId + 1,
      timeout: pollTime,
      allowed_updates: ['callback_query', 'message'],
    }, (pollTime + 10) * 1000);
    const result = Array.isArray(raw) ? raw as { update_id: number; callback_query?: { id: string; from?: { id: number }; data?: string } }[] : null;

    if (!result) {
      await new Promise((r) => setTimeout(r, retryDelay));
      retryDelay = Math.min(retryDelay * 1.5, 30_000); // backoff up to 30s
      continue;
    }
    retryDelay = 2000; // reset on success

    for (const update of result) {
      _lastUpdateId = Math.max(_lastUpdateId, update.update_id);

      const cb = update.callback_query;
      if (cb && String(cb.from?.id) === target) {
        await post('answerCallbackQuery', { callback_query_id: cb.id });
        return cb.data ?? null;
      }
    }
  }

  return null;
}

export async function pollReply(
  timeoutSecs = 120,
  chatId = '',
): Promise<string | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  const deadline = Date.now() + timeoutSecs * 1000;

  let retryDelay = 2000;
  while (Date.now() < deadline) {
    const remaining = Math.max(1, Math.floor((deadline - Date.now()) / 1000));
    const pollTime = Math.min(remaining, 30);

    const raw = await post('getUpdates', {
      offset: _lastUpdateId + 1,
      timeout: pollTime,
      allowed_updates: ['message'],
    }, (pollTime + 10) * 1000);
    const result = Array.isArray(raw) ? raw as { update_id: number; message?: { from?: { id: number }; text?: string } }[] : null;

    if (!result) {
      await new Promise((r) => setTimeout(r, retryDelay));
      retryDelay = Math.min(retryDelay * 1.5, 30_000);
      continue;
    }
    retryDelay = 2000;

    for (const update of result) {
      _lastUpdateId = Math.max(_lastUpdateId, update.update_id);

      const msg = update.message;
      if (msg && String(msg.from?.id) === target && msg.text) {
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
  // Topics mode - each agent has its own topic, no per-agent commands needed.
  // Only register utility commands.
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

// Export for daemon access
export { post, post as _post, _lastUpdateId, apiUrl };
export function setLastUpdateId(id: number): void {
  _lastUpdateId = id;
}
