# src/main/channels/telegram/api.ts - Telegram Bot API Client

**Line count:** ~909 lines  
**Dependencies:** `fs`, `os`, `path`, `../../config`, `../../logger`  
**Purpose:** Pure HTTP Telegram Bot API client with inline keyboards and polling

## Overview

This module implements the complete Telegram Bot API integration using pure HTTP via `fetch()`. There are no third-party Telegram libraries - all API calls are handwritten HTTP requests. This keeps the dependency footprint minimal and gives full control over timeout, error handling, and multipart form construction.

**Key features:**
- Inline keyboards for confirmations/permissions
- Long-polling for message reception
- Markdown formatting with fallback
- Rate limit handling (429 Retry-After)
- Per-bot update ID tracking

## Update ID Tracking

```typescript
const _lastUpdateIds = new Map<string, number>();

function getOffset(botToken?: string): number {
  return _lastUpdateIds.get(botToken || getConfig().TELEGRAM_BOT_TOKEN) || 0;
}

function setOffset(updateId: number, botToken?: string): void {
  const key = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  const cur = _lastUpdateIds.get(key) || 0;
  if (updateId > cur) _lastUpdateIds.set(key, updateId);
}
```

**Purpose:** Track last processed update per bot to avoid re-reading old messages.

**Why per-bot:** Multiple agents with different bots shouldn't stomp each other's offsets.

## API Helpers

### post

```typescript
const MAX_RETRIES = 3;

export async function post(
  method: string,
  payload: Record<string, unknown>,
  timeoutMs = 15_000,
  botToken?: string,
): Promise<unknown | null> {
  const token = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  if (!token) {
    log.warn('TELEGRAM_BOT_TOKEN not configured');
    return null;
  }

  // Long-poll requests need longer timeout
  const pollTimeout = (payload.timeout as number) || 0;
  const fetchTimeout = pollTimeout > 0 ? (pollTimeout + 10) * 1000 : 15_000;

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
          return null;
        }
        log.debug(`Rate limited - waiting ${wait}s before retry`);
        await new Promise((r) => setTimeout(r, wait * 1000));
        continue;
      }

      // "message is not modified" is not a real error
      if (data.description?.includes('message is not modified')) {
        return data.result ?? {};
      }

      log.error(`API error: ${data.description || JSON.stringify(data)}`);
      return null;
    } catch (e) {
      if (attempt < MAX_RETRIES - 1) {
        log.debug(`${method} attempt ${attempt + 1} failed: ${e} - retrying`);
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        continue;
      }
      log.error(`${method} failed after ${MAX_RETRIES} attempts: ${e}`);
      return null;
    }
  }

  return null;
}
```

**Features:**
- 3 retry attempts with exponential backoff
- Flood control handling (429 with `retry_after`)
- "message is not modified" treated as success
- Configurable timeout (longer for polling)

### postWithMarkdownFallback

```typescript
async function postWithMarkdownFallback(
  payload: Record<string, unknown>,
  botToken?: string,
): Promise<unknown | null> {
  // Try with Markdown first
  const result = await post('sendMessage', payload, 15_000, botToken);
  if (result !== null) return result;

  // If Markdown fails, retry without parse_mode
  const plainPayload = { ...payload };
  delete plainPayload.parse_mode;
  log.debug('Send failed - retrying without Markdown');
  return post('sendMessage', plainPayload, 15_000, botToken);
}
```

**Purpose:** Retry without Markdown if parsing fails.

### editWithMarkdownFallback

```typescript
async function editWithMarkdownFallback(
  payload: Record<string, unknown>,
  botToken?: string,
): Promise<unknown | null> {
  const result = await post('editMessageText', payload, 15_000, botToken);
  if (result !== null) return result;

  const plainPayload = { ...payload };
  delete plainPayload.parse_mode;
  return post('editMessageText', plainPayload, 15_000, botToken);
}
```

**Purpose:** Retry edit without Markdown if parsing fails.

## Sending Functions

### sendMessage

```typescript
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

  // Telegram has 4096 character limit - split if needed
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

  // Split on paragraph boundaries
  let remaining = text;
  let allSent = true;
  while (remaining.length > 0) {
    let chunk: string;
    if (remaining.length <= MAX_LEN) {
      chunk = remaining;
      remaining = '';
    } else {
      // Split at paragraph boundary
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
    const result = await post('sendMessage', payload, 15_000, botToken);
    if (!result) allSent = false;
  }
  return allSent;
}
```

**Features:**
- Agent emoji + name prefix
- 4096 char limit with intelligent splitting
- Markdown formatting with fallback

### sendMessageGetId

```typescript
export async function sendMessageGetId(
  text: string,
  chatId = '',
  botToken?: string,
): Promise<number | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) return null;

  if (config.TELEGRAM_EMOJI) {
    text = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${text}`;
  }

  const payload: Record<string, unknown> = {
    chat_id: target,
    text,
    parse_mode: 'Markdown',
  };
  const result = await postWithMarkdownFallback(payload, botToken) as { message_id?: number } | null;
  return result?.message_id ?? null;
}
```

**Purpose:** Send message and return message_id for later editing.

### editMessage

```typescript
export async function editMessage(
  messageId: number,
  text: string,
  chatId = '',
  botToken?: string,
): Promise<boolean> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) return false;

  // Telegram 4096 char limit
  if (text.length > 4096) {
    text = text.slice(0, 4096);
  }

  const payload: Record<string, unknown> = {
    chat_id: target,
    message_id: messageId,
    text,
    parse_mode: 'Markdown',
  };
  const result = await editWithMarkdownFallback(payload, botToken);
  return !!result;
}
```

**Purpose:** Edit existing message (used for streaming display).

### sendButtons

```typescript
export async function sendButtons(
  text: string,
  buttons: { text: string; callback_data: string }[][],
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<number | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) return null;

  if (prefix && config.TELEGRAM_EMOJI) {
    text = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${text}`;
  }

  const payload: Record<string, unknown> = {
    chat_id: target,
    text,
    parse_mode: 'Markdown',
    reply_markup: {
      inline_keyboard: buttons,
    },
  };
  const result = await postWithMarkdownFallback(payload, botToken) as { message_id?: number } | null;
  return result?.message_id ?? null;
}
```

**Purpose:** Send message with inline keyboard buttons.

**Button format:**
```typescript
// Single row with two buttons
[[
  { text: 'Yes', callback_data: 'yes' },
  { text: 'No', callback_data: 'no' }
]]
```

### sendPhoto

```typescript
export async function sendPhoto(
  filePath: string,
  caption = '',
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<boolean> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) return false;

  const ext = path.extname(filePath).toLowerCase();
  const contentType = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
  }[ext];

  if (!contentType) {
    log.warn(`Unsupported image format: ${ext}`);
    return false;
  }

  const photoData = fs.readFileSync(filePath);
  const boundary = `----TelegramPhoto${Date.now()}`;

  const parts: string[] = [];
  if (prefix && config.TELEGRAM_EMOJI) {
    caption = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${caption}`;
  }
  if (caption) {
    parts.push(
      `--${boundary}\r\n` +
      'Content-Disposition: form-data; name="caption"\r\n\r\n' +
      caption + '\r\n',
    );
  }
  parts.push(
    `--${boundary}\r\n` +
    'Content-Disposition: form-data; name="photo"; filename="photo"\r\n' +
    `Content-Type: ${contentType}\r\n\r\n`,
  );

  const bodyParts: Buffer[] = [
    Buffer.from(parts.join('')),
    photoData,
    Buffer.from(`\r\n--${boundary}--\r\n`),
  ];

  const resp = await fetch(`https://api.telegram.org/bot${botToken || config.TELEGRAM_BOT_TOKEN}/sendPhoto`, {
    method: 'POST',
    headers: {
      'Content-Type': `multipart/form-data; boundary=${boundary}`,
      'Content-Length': String(bodyParts.reduce((acc, b) => acc + b.length, 0)),
    },
    body: Buffer.concat(bodyParts),
    signal: AbortSignal.timeout(30_000),
  });

  const data = await resp.json() as { ok: boolean };
  return data.ok;
}
```

**Purpose:** Send image file as photo message.

**Supported formats:** JPG, JPEG, PNG, GIF, WebP

### sendVoiceNote

```typescript
export async function sendVoiceNote(
  audioPath: string,
  caption = '',
  chatId = '',
  prefix = true,
  botToken?: string,
): Promise<boolean> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) return false;

  const ext = path.extname(audioPath).toLowerCase();
  const isOgg = ext === '.ogg' || ext === '.oga';

  // Read audio file
  const audioData = fs.readFileSync(audioPath);
  const boundary = `----TelegramVoice${Date.now()}`;

  const parts: string[] = [];
  if (prefix && config.TELEGRAM_EMOJI) {
    caption = `${config.TELEGRAM_EMOJI} *${config.AGENT_DISPLAY_NAME}*\n\n${caption}`;
  }
  if (caption) {
    parts.push(
      `--${boundary}\r\n` +
      'Content-Disposition: form-data; name="caption"\r\n\r\n' +
      caption + '\r\n',
    );
  }
  parts.push(
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="${isOgg ? 'voice' : 'audio'}"; filename="audio"${isOgg ? '\r\nContent-Type: audio/ogg' : ''}\r\n\r\n`,
  );

  const bodyParts: Buffer[] = [
    Buffer.from(parts.join('')),
    audioData,
    Buffer.from(`\r\n--${boundary}--\r\n`),
  ];

  const method = isOgg ? 'sendVoice' : 'sendAudio';
  const resp = await fetch(`https://api.telegram.org/bot${botToken || config.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: 'POST',
    headers: {
      'Content-Type': `multipart/form-data; boundary=${boundary}`,
      'Content-Length': String(bodyParts.reduce((acc, b) => acc + b.length, 0)),
    },
    body: Buffer.concat(bodyParts),
    signal: AbortSignal.timeout(30_000),
  });

  const data = await resp.json() as { ok: boolean };
  return data.ok;
}
```

**Purpose:** Send audio file as voice note (OGG) or audio file (other formats).

**Format handling:**
- `.ogg`/`.oga` → `sendVoice` (voice message with waveform)
- Other → `sendAudio` (audio file with player)

## Receiving Functions

### flushOldUpdates

```typescript
export async function flushOldUpdates(botToken?: string): Promise<void> {
  const offset = getOffset(botToken);
  const payload: Record<string, unknown> = {
    offset,
    timeout: 1,
    allowed_updates: ['message'],
  };

  // Keep polling until no more updates
  while (true) {
    const result = await post('getUpdates', payload, 15_000, botToken) as Array<Record<string, unknown>> | null;
    if (!result || result.length === 0) break;

    const lastUpdate = result[result.length - 1];
    setOffset(lastUpdate.update_id + 1, botToken);
    payload.offset = lastUpdate.update_id + 1;
  }
}
```

**Purpose:** Consume all pending updates without processing (used before starting fresh poll).

### pollCallback

```typescript
export async function pollCallback(
  timeoutSecs = 120,
  chatId = '',
  botToken?: string,
): Promise<string | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) return null;

  // Flush old updates first
  await flushOldUpdates(botToken);

  const startTime = Date.now();
  const endTime = startTime + timeoutSecs * 1000;

  while (Date.now() < endTime) {
    const remaining = Math.max(1, Math.floor((endTime - Date.now()) / 1000));
    const payload: Record<string, unknown> = {
      offset: getOffset(botToken),
      timeout: remaining,
      allowed_updates: ['callback_query'],
    };

    const result = await post('getUpdates', payload, (remaining + 10) * 1000, botToken) as Array<Record<string, unknown>> | null;
    if (!result || result.length === 0) continue;

    for (const update of result) {
      const callbackQuery = update.callback_query as Record<string, unknown> | undefined;
      if (!callbackQuery) continue;

      const from = callbackQuery.from as Record<string, unknown> | undefined;
      if (from?.id !== config.TELEGRAM_USER_ID) continue;

      const data = callbackQuery.data as string | undefined;
      const id = callbackQuery.id as string | undefined;

      if (data && id) {
        // Answer callback to remove loading spinner
        await post('answerCallbackQuery', {
          callback_query_id: id,
        }, 15_000, botToken);

        setOffset(update.update_id + 1, botToken);
        return data;
      }

      setOffset(update.update_id + 1, botToken);
    }
  }

  return null;
}
```

**Purpose:** Long-poll for inline keyboard callback from specific user.

**Returns:** `callback_data` string or null on timeout.

### pollReply

```typescript
export async function pollReply(
  timeoutSecs = 120,
  chatId = '',
  botToken?: string,
): Promise<string | null> {
  const config = getConfig();
  const target = chatId || config.TELEGRAM_CHAT_ID;
  if (!target) return null;

  await flushOldUpdates(botToken);

  const startTime = Date.now();
  const endTime = startTime + timeoutSecs * 1000;

  while (Date.now() < endTime) {
    const remaining = Math.max(1, Math.floor((endTime - Date.now()) / 1000));
    const payload: Record<string, unknown> = {
      offset: getOffset(botToken),
      timeout: remaining,
      allowed_updates: ['message'],
    };

    const result = await post('getUpdates', payload, (remaining + 10) * 1000, botToken) as Array<Record<string, unknown>> | null;
    if (!result || result.length === 0) continue;

    for (const update of result) {
      const message = update.message as Record<string, unknown> | undefined;
      if (!message) continue;

      const from = message.from as Record<string, unknown> | undefined;
      if (from?.id !== config.TELEGRAM_USER_ID) continue;

      const text = message.text as string | undefined;
      if (text) {
        setOffset(update.update_id + 1, botToken);
        return text;
      }

      setOffset(update.update_id + 1, botToken);
    }
  }

  return null;
}
```

**Purpose:** Long-poll for text message reply from specific user.

**Returns:** Message text or null on timeout.

## High-Level Functions

### askConfirm

```typescript
export async function askConfirm(
  text: string,
  timeoutSecs = 120,
  botToken?: string,
): Promise<boolean | null> {
  const buttons = [[
    { text: 'Yes', callback_data: 'yes' },
    { text: 'No', callback_data: 'no' },
  ]];

  const messageId = await sendButtons(text, buttons, '', true, botToken);
  if (!messageId) return null;

  const response = await pollCallback(timeoutSecs, '', botToken);
  if (response === 'yes') return true;
  if (response === 'no') return false;
  return null;
}
```

**Purpose:** Send confirmation prompt with Yes/No buttons.

**Returns:** `true` (yes), `false` (no), or `null` (timeout).

### askQuestion

```typescript
export async function askQuestion(
  text: string,
  timeoutSecs = 120,
  botToken?: string,
): Promise<string | null> {
  await sendMessage(text, '', true, botToken);
  return pollReply(timeoutSecs, '', botToken);
}
```

**Purpose:** Send question and wait for text reply.

**Returns:** Reply text or null on timeout.

## Bot Command Registration

### registerBotCommands

```typescript
export async function registerBotCommands(botToken?: string): Promise<boolean> {
  const agents = discoverAgents();
  const commands: Record<string, string>[] = [];

  for (const agent of agents) {
    const manifest = loadAgentManifest(agent.name);
    const description = (manifest.description as string || '').slice(0, 256);
    commands.push({
      command: agent.name,
      description: description,
    });
  }

  // Add utility commands
  commands.push({ command: 'status', description: 'Show active agents' });
  commands.push({ command: 'mute', description: 'Toggle agent muting' });

  const payload: Record<string, unknown> = {
    commands,
  };

  const result = await post('setMyCommands', payload, 15_000, botToken);
  return !!result;
}
```

**Purpose:** Register agent names as bot commands for autocomplete.

### clearBotCommands

```typescript
export async function clearBotCommands(botToken?: string): Promise<boolean> {
  const result = await post('deleteMyCommands', {}, 15_000, botToken);
  return !!result;
}
```

**Purpose:** Clear all bot commands.

## Bot Profile Photo

### setBotProfilePhoto

```typescript
export async function setBotProfilePhoto(
  imagePath: string,
  botToken?: string,
): Promise<boolean> {
  const photoData = fs.readFileSync(imagePath);
  const boundary = `----TelegramPhoto${Date.now()}`;

  const parts = [
    `--${boundary}\r\n`,
    'Content-Disposition: form-data; name="photo"; filename="photo.jpg"\r\n',
    'Content-Type: image/jpeg\r\n\r\n',
  ];

  const bodyParts: Buffer[] = [
    Buffer.from(parts.join('')),
    photoData,
    Buffer.from(`\r\n--${boundary}--\r\n`),
  ];

  const resp = await fetch(`https://api.telegram.org/bot${botToken || getConfig().TELEGRAM_BOT_TOKEN}/setMyPhoto`, {
    method: 'POST',
    headers: {
      'Content-Type': `multipart/form-data; boundary=${boundary}`,
    },
    body: Buffer.concat(bodyParts),
    signal: AbortSignal.timeout(30_000),
  });

  const data = await resp.json() as { ok: boolean };
  return data.ok;
}
```

**Purpose:** Set bot's profile photo from image file.

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/.telegram_daemon_state.json` | Update ID tracking |
| `~/.atrophy/.telegram_daemon.lock` | Daemon instance lock |

## Exported API

| Function | Purpose |
|----------|---------|
| `post(method, payload, timeout, botToken)` | Generic POST to Telegram API |
| `sendMessage(text, chatId, prefix, botToken)` | Send Markdown message |
| `sendMessageGetId(text, chatId, botToken)` | Send message, return ID |
| `editMessage(messageId, text, chatId, botToken)` | Edit existing message |
| `sendButtons(text, buttons, chatId, prefix, botToken)` | Send with inline keyboard |
| `sendPhoto(filePath, caption, chatId, prefix, botToken)` | Send image |
| `sendVoiceNote(audioPath, caption, chatId, prefix, botToken)` | Send voice note |
| `flushOldUpdates(botToken)` | Consume pending updates |
| `pollCallback(timeout, chatId, botToken)` | Poll for callback |
| `pollReply(timeout, chatId, botToken)` | Poll for text reply |
| `askConfirm(text, timeout, botToken)` | Yes/No confirmation |
| `askQuestion(text, timeout, botToken)` | Question with text reply |
| `registerBotCommands(botToken)` | Register agent commands |
| `clearBotCommands(botToken)` | Clear commands |
| `setBotProfilePhoto(imagePath, botToken)` | Set bot profile photo |

## See Also

- [`daemon.ts`](telegram/daemon.md) - Telegram polling daemon
- `src/main/ipc/telegram.ts` - Telegram IPC handlers
- `src/main/channels/switchboard.ts` - Message routing
