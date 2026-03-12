/**
 * Telegram channel - send and receive via Bot API.
 * Port of channels/telegram.py.
 *
 * Uses inline keyboards for confirmations/permissions and polls for
 * text replies. Pure HTTP via fetch - no webhooks, no extra dependencies.
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from './config';

// Track last processed update to avoid re-reading old ones
let _lastUpdateId = 0;

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

function apiUrl(method: string): string {
  const config = getConfig();
  return `https://api.telegram.org/bot${config.TELEGRAM_BOT_TOKEN}/${method}`;
}

async function post(method: string, payload: Record<string, unknown>): Promise<unknown | null> {
  const config = getConfig();
  if (!config.TELEGRAM_BOT_TOKEN) {
    console.log('[telegram] TELEGRAM_BOT_TOKEN not configured');
    return null;
  }

  try {
    const resp = await fetch(apiUrl(method), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(15_000),
    });

    const result = await resp.json() as { ok: boolean; result?: unknown };
    if (result.ok) return result.result;

    console.log(`[telegram] API error: ${JSON.stringify(result)}`);
    return null;
  } catch (e) {
    console.log(`[telegram] error: ${e}`);
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
): Promise<boolean> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) {
    console.log('[telegram] TELEGRAM_CHAT_ID not configured');
    return false;
  }

  if (prefix && config.TELEGRAM_EMOJI) {
    text = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${text}`;
  }

  const result = await post('sendMessage', {
    chat_id: target,
    text,
    parse_mode: 'Markdown',
  });

  if (result) {
    console.log(`[telegram] Sent message (${text.length} chars)`);
    return true;
  }
  return false;
}

export async function sendButtons(
  text: string,
  buttons: { text: string; callback_data: string }[][],
  chatId = '',
  prefix = true,
): Promise<number | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) {
    console.log('[telegram] TELEGRAM_CHAT_ID not configured');
    return null;
  }

  if (prefix && config.TELEGRAM_EMOJI) {
    text = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${text}`;
  }

  const result = await post('sendMessage', {
    chat_id: target,
    text,
    parse_mode: 'Markdown',
    reply_markup: { inline_keyboard: buttons },
  }) as { message_id?: number } | null;

  if (result) {
    console.log(`[telegram] Sent buttons (${text.length} chars)`);
    return result.message_id ?? null;
  }
  return null;
}

export async function sendVoiceNote(
  audioPath: string,
  caption = '',
  chatId = '',
  prefix = true,
): Promise<boolean> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) {
    console.log('[telegram] TELEGRAM_CHAT_ID not configured');
    return false;
  }

  if (prefix && config.TELEGRAM_EMOJI && caption) {
    caption = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${caption}`;
  }

  try {
    const fileData = fs.readFileSync(audioPath);
    const filename = path.basename(audioPath);
    const isOgg = audioPath.endsWith('.ogg') || audioPath.endsWith('.oga');
    const method = isOgg ? 'sendVoice' : 'sendAudio';
    const fieldName = isOgg ? 'voice' : 'audio';

    // Build multipart form data
    const boundary = `----FormBoundary${Date.now()}${Math.random().toString(36).slice(2)}`;
    const parts: Buffer[] = [];

    // chat_id
    parts.push(Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n${target}\r\n`));

    // caption
    if (caption) {
      parts.push(Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n${caption}\r\n`));
      parts.push(Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="parse_mode"\r\n\r\nMarkdown\r\n`));
    }

    // file
    parts.push(Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="${fieldName}"; filename="${filename}"\r\n` +
      `Content-Type: ${isOgg ? 'audio/ogg' : 'audio/mpeg'}\r\n\r\n`,
    ));
    parts.push(fileData);
    parts.push(Buffer.from(`\r\n--${boundary}--\r\n`));

    const body = Buffer.concat(parts);

    const resp = await fetch(apiUrl(method), {
      method: 'POST',
      headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` },
      body,
      signal: AbortSignal.timeout(30_000),
    });

    const result = await resp.json() as { ok: boolean };
    if (result.ok) {
      console.log(`[telegram] Sent voice note (${fileData.length} bytes)`);
      return true;
    }
    console.log(`[telegram] Voice note error: ${JSON.stringify(result)}`);
    return false;
  } catch (e) {
    console.log(`[telegram] Voice note error: ${e}`);
    return false;
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

  while (Date.now() < deadline) {
    const remaining = Math.max(1, Math.floor((deadline - Date.now()) / 1000));
    const pollTime = Math.min(remaining, 30);

    const result = await post('getUpdates', {
      offset: _lastUpdateId + 1,
      timeout: pollTime,
      allowed_updates: ['callback_query', 'message'],
    }) as { update_id: number; callback_query?: { id: string; from?: { id: number }; data?: string } }[] | null;

    if (!result) {
      await new Promise((r) => setTimeout(r, 2000));
      continue;
    }

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

  while (Date.now() < deadline) {
    const remaining = Math.max(1, Math.floor((deadline - Date.now()) / 1000));
    const pollTime = Math.min(remaining, 30);

    const result = await post('getUpdates', {
      offset: _lastUpdateId + 1,
      timeout: pollTime,
      allowed_updates: ['message'],
    }) as { update_id: number; message?: { from?: { id: number }; text?: string } }[] | null;

    if (!result) {
      await new Promise((r) => setTimeout(r, 2000));
      continue;
    }

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

// Export for daemon access
export { post as _post, _lastUpdateId };
export function setLastUpdateId(id: number): void {
  _lastUpdateId = id;
}
