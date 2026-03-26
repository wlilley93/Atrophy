# src/main/jobs/gift.ts - Companion Gift-Leaving

**Line count:** ~268 lines  
**Dependencies:** `fs`, `path`, `better-sqlite3`, `../config`, `../inference`, `../prompts`, `../queue`, `../notify`, `../channels/cron`, `../logger`  
**Purpose:** Unprompted notes in Obsidian - random schedule, 3-30 days

## Overview

This module implements the companion's gift-leaving behavior - unprompted notes left in Obsidian for the user to discover. The schedule is randomized (3-30 days) so the user never knows when to expect it.

**Port of:** `scripts/agents/companion/gift.py`

**Schedule:** Random, 3-30 days (reschedules after each run)

## Types

### Database Row Types

```typescript
interface ThreadRow {
  name: string;
  summary: string | null;
}

interface ObservationRow {
  content: string;
  created_at: string;
}

interface BookmarkRow {
  moment: string;
  quote: string | null;
  created_at: string;
}

interface TurnRow {
  content: string;
  timestamp: string;
}
```

## Database Access

### connectAgent

```typescript
function connectAgent(agentName: string): Database.Database {
  const config = getConfig();
  config.reloadForAgent(agentName);
  const dbPath = config.DB_PATH;
  if (!fs.existsSync(dbPath)) {
    throw new Error(`No database for agent ${agentName}: ${dbPath}`);
  }
  const db = new Database(dbPath, { readonly: true });
  return db;
}
```

**Purpose:** Open agent's database in readonly mode.

## Material Gathering

### gatherMaterial

```typescript
function gatherMaterial(agentName: string): string {
  const config = getConfig();
  const db = connectAgent(agentName);
  const parts: string[] = [];

  try {
    // Active threads
    const threads = db
      .prepare(
        "SELECT name, summary FROM threads WHERE status = 'active' " +
        'ORDER BY last_updated DESC LIMIT 5',
      )
      .all() as ThreadRow[];
    if (threads.length > 0) {
      parts.push(
        'Active threads:\n' +
        threads.map((t) => `- ${t.name}: ${t.summary || '...'}`).join('\n'),
      );
    }

    // Recent observations
    const obs = db
      .prepare(
        'SELECT content, created_at FROM observations ' +
        'ORDER BY created_at DESC LIMIT 10',
      )
      .all() as ObservationRow[];
    if (obs.length > 0) {
      parts.push(
        'Recent observations:\n' +
        obs.map((o) => `- [${o.created_at}] ${o.content}`).join('\n'),
      );
    }

    // Bookmarks
    const bookmarks = db
      .prepare(
        'SELECT moment, quote, created_at FROM bookmarks ' +
        'ORDER BY created_at DESC LIMIT 5',
      )
      .all() as BookmarkRow[];
    if (bookmarks.length > 0) {
      const lines = bookmarks.map((b) => {
        const quote = b.quote ? ` - "${b.quote}"` : '';
        return `- [${b.created_at}] ${b.moment}${quote}`;
      });
      parts.push('Bookmarked moments:\n' + lines.join('\n'));
    }

    // Recent user turns (for texture)
    const turns = db
      .prepare(
        "SELECT content, timestamp FROM turns WHERE role = 'will' " +
        'ORDER BY timestamp DESC LIMIT 5',
      )
      .all() as TurnRow[];
    if (turns.length > 0) {
      parts.push(
        'Recent things the user said:\n' +
        turns.map((t) => `- [${t.timestamp}] ${t.content.slice(0, 300)}`).join('\n'),
      );
    }
  } finally {
    db.close();
  }

  // Read existing gifts to avoid repetition
  const giftsPath = path.join(config.OBSIDIAN_AGENT_NOTES, 'notes', 'gifts.md');
  if (fs.existsSync(giftsPath)) {
    let content = fs.readFileSync(giftsPath, 'utf-8');
    if (content.length > 2000) {
      content = '...\n' + content.slice(-2000);
    }
    parts.push(`Your previous gifts (avoid repeating):\n${content}`);
  }

  return parts.join('\n\n');
}
```

**Sections:**
1. Active threads (last 5)
2. Recent observations (last 10)
3. Bookmarked moments (last 5)
4. Recent user turns (last 5, for texture)
5. Previous gifts (last 2000 chars, to avoid repetition)

## Rescheduling

### reschedule

```typescript
function reschedule(): void {
  const days = Math.floor(Math.random() * 28) + 3; // 3-30
  const hour = Math.floor(Math.random() * 24);
  const minute = Math.floor(Math.random() * 60);

  const target = new Date();
  target.setDate(target.getDate() + days);
  const dom = target.getDate();
  const month = target.getMonth() + 1;

  const newCron = `${minute} ${hour} ${dom} ${month} *`;

  try {
    editJobSchedule(getConfig().AGENT_NAME, 'gift', newCron);
    log.info(
      `Rescheduled to ${target.toISOString().split('T')[0]} ` +
      `at ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`,
    );
  } catch (e) {
    log.error(`Failed to reschedule: ${e}`);
  }
}
```

**Purpose:** Reschedule to random time 3-30 days from now.

**Randomization:**
- Days: 3-30 (random)
- Hour: 0-23 (random)
- Minute: 0-59 (random)

**Philosophy:** "He should never know when to expect it."

## Write Gift to Obsidian

### writeGiftToObsidian

```typescript
function writeGiftToObsidian(gift: string, agentName: string): string {
  const config = getConfig();
  const giftsDir = path.join(config.OBSIDIAN_AGENT_NOTES, 'notes');
  fs.mkdirSync(giftsDir, { recursive: true });
  const giftsPath = path.join(giftsDir, 'gifts.md');

  const now = new Date();
  const dateStr = `${now.toISOString().split('T')[0]} ${now.toTimeString().slice(0, 5)}`;
  const today = now.toISOString().split('T')[0];
  const entry = `\n---\n*${dateStr}*\n\n${gift.trim()}\n`;

  if (fs.existsSync(giftsPath)) {
    let existing = fs.readFileSync(giftsPath, 'utf-8');
    // Append to existing file
    fs.writeFileSync(giftsPath, existing + entry);
  } else {
    fs.writeFileSync(giftsPath, entry);
  }

  return giftsPath;
}
```

**Format:**
```markdown
---
*2026-03-26 14:30*

[Gift content here]

---
*2026-03-20 09:15*

[Previous gift content]
```

## Main Function

### gift

```typescript
export async function gift(): Promise<void> {
  const config = getConfig();
  const agentName = config.AGENT_NAME;

  // Gather material
  const material = gatherMaterial(agentName);
  if (!material.trim()) {
    log.info('No material for gift. Skipping.');
    return;
  }

  log.info('Generating gift...');

  // Generate gift via inference
  let gift: string;
  try {
    gift = await runInferenceOneshot(
      [{ role: 'user', content: material }],
      loadPrompt('gift', GIFT_FALLBACK),
      60_000,  // 1 minute timeout
    );
  } catch (e) {
    log.error(`Gift generation failed: ${e}`);
    return;
  }

  if (!gift.trim()) {
    log.info('Empty gift generated. Skipping.');
    return;
  }

  log.info(`Gift generated (${gift.length} chars)`);

  // Write to Obsidian
  const giftsPath = writeGiftToObsidian(gift, agentName);
  log.info(`Gift written to ${giftsPath}`);

  // Queue notification for next launch
  await queueMessage(
    `I left something for you in your notes.`,
    'gift',
    '',
  );

  // Send macOS notification
  sendNotification('A Gift', 'I left something for you in your notes.');

  // Reschedule
  reschedule();
}
```

**Flow:**
1. Gather material from database
2. Generate gift via oneshot inference (1 min timeout)
3. Write to Obsidian gifts.md
4. Queue message for next launch
5. Send macOS notification
6. Reschedule to random future date

## Fallback Prompt

```typescript
const GIFT_FALLBACK =
  'You are the companion. Leave a short, specific note for the user. ' +
  '2-4 sentences. No greeting. No sign-off.';
```

## Job Registration

```typescript
registerJob({
  name: 'gift',
  description: 'Unprompted gift notes in Obsidian',
  gates: [],  // No time gates - runs on random schedule
  run: async () => {
    await gift();
    return 'Gift left in Obsidian';
  },
});
```

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Database queries |
| `<Obsidian>/notes/gifts.md` | Gift notes file |
| `~/.atrophy/agents/<name>/data/.message_queue.json` | Queued notification |

## Exported API

| Function | Purpose |
|----------|---------|
| `gift()` | Generate and leave gift note |
| `gatherMaterial(agentName)` | Gather database material |
| `reschedule()` | Random reschedule (3-30 days) |
| `writeGiftToObsidian(gift, agentName)` | Write to Obsidian |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/channels/cron/scheduler.ts` - Cron scheduling
- `src/main/queue.ts` - Message queue
