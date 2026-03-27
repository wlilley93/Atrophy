# src/main/jobs/check-reminders.ts - Reminder Checker

**Dependencies:** `fs`, `path`, `../config`, `../logger`, `../notify`, `../queue`, `../channels/telegram`  
**Purpose:** Check and fire due reminders - runs every minute via launchd

## Overview

This module reads reminders from the agent's reminder store, fires notifications and queues messages for any that are due, then removes them.


**Schedule:** Every minute via launchd

**Storage:** `agents/<name>/data/.reminders.json`

## Types

### Reminder

```typescript
interface Reminder {
  id: string;
  time: string;        // ISO 8601 datetime
  message: string;
  source: string;      // Who created it (e.g., "will")
  created_at: string;  // ISO 8601 datetime
}
```

## Reminder Storage

### remindersPath

```typescript
function remindersPath(): string {
  const config = getConfig();
  return path.join(config.DATA_DIR, '.reminders.json');
}
```

**Purpose:** Get reminders file path.

### loadReminders

```typescript
function loadReminders(): Reminder[] {
  const p = remindersPath();
  if (!fs.existsSync(p)) return [];
  try {
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch {
    return [];
  }
}
```

**Purpose:** Load all reminders from file.

### saveReminders

```typescript
function saveReminders(reminders: Reminder[]): void {
  const p = remindersPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  // Write to temp file then rename for atomicity
  const tmp = p + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(reminders, null, 2) + '\n');
  fs.renameSync(tmp, p);
}
```

**Purpose:** Save reminders atomically (temp file + rename).

**Why atomic:** Prevents data loss if another process writes between our read and write.

## Main Entry Point

### checkReminders

```typescript
export async function checkReminders(): Promise<void> {
  const config = getConfig();
  const reminders = loadReminders();
  if (reminders.length === 0) return;

  const now = new Date();
  const due: Reminder[] = [];
  const remaining: Reminder[] = [];

  for (const r of reminders) {
    let remindTime: Date;
    try {
      remindTime = new Date(r.time);
      if (isNaN(remindTime.getTime())) {
        remaining.push(r);
        continue;
      }
    } catch {
      remaining.push(r);
      continue;
    }

    if (remindTime <= now) {
      due.push(r);
    } else {
      remaining.push(r);
    }
  }

  if (due.length === 0) return;

  // Fire due reminders
  for (const r of due) {
    const msg = r.message || 'Reminder';
    log.info(`Firing: ${msg}`);

    // macOS notification with sound
    sendNotification(`Reminder - ${config.AGENT_DISPLAY_NAME}`, msg);

    // Queue for next app interaction
    await queueMessage(`Reminder: ${msg}`, 'reminder');

    // Send via Telegram if configured
    try {
      if (config.TELEGRAM_BOT_TOKEN && config.TELEGRAM_CHAT_ID) {
        await telegramSend(`Reminder: ${msg}`);
      }
    } catch { /* non-fatal */ }
  }

  // Re-read to merge any reminders added while we were firing,
  // then remove only the ones we actually fired (by time+message identity)
  const firedSet = new Set(due.map(r => `${r.time}|${r.message}`));
  const fresh = loadReminders();
  const merged = fresh.filter(r => !firedSet.has(`${r.time}|${r.message}`));
  saveReminders(merged);
  log.info(`Fired ${due.length}, ${merged.length} remaining.`);
}
```

**Flow:**
1. Load all reminders
2. Partition into due vs remaining
3. For each due reminder:
   - Send macOS notification
   - Queue message for next app launch
   - Send via Telegram (if configured)
4. Re-read reminders (merge any added during firing)
5. Remove fired reminders (by time+message identity)
6. Save remaining reminders

**Race condition handling:**
- Re-read reminders after firing (may have new additions)
- Use time+message identity set for removal (handles duplicates)

## CLI Entry Point

```typescript
if (require.main === module) {
  checkReminders().catch((e) => {
    log.error(`Fatal: ${e}`);
    process.exit(1);
  });
}
```

**Usage:**
```bash
node check-reminders.js
```

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/.reminders.json` | Reminder storage |
| `~/.atrophy/agents/<name>/data/.reminders.json.tmp` | Atomic write temp file |

## Exported API

| Function | Purpose |
|----------|---------|
| `checkReminders()` | Check and fire due reminders |
| `loadReminders()` | Load all reminders |
| `saveReminders(reminders)` | Save reminders atomically |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/notify.ts` - macOS notifications
- `src/main/queue.ts` - Message queue
- `src/main/channels/telegram/api.ts` - Telegram sending
