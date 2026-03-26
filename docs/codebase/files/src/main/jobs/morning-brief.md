# src/main/jobs/morning-brief.ts - Morning Brief Job

**Line count:** ~250 lines  
**Dependencies:** `fs`, `path`, `../config`, `../logger`, `../inference`, `../prompts`, `../queue`, `../notify`, `../tts`, `../channels/telegram`, `../memory`  
**Purpose:** Daily morning brief with weather, headlines, threads, and observations

## Overview

This module generates a natural morning brief for the user, queued for next app launch. It gathers weather, headlines, active threads, recent session summaries, and observations, then composes a brief via oneshot inference.

**Schedule:** `0 7 * * *` (daily at 7am)

**Two modes:**
- Standalone: `node morning-brief.js` (via launchd)
- Callable: `import { morningBrief } from './morning-brief'`

## Weather Fetch

```typescript
async function fetchWeather(location = 'Leeds'): Promise<string> {
  try {
    const resp = await fetch(
      `https://wttr.in/${encodeURIComponent(location)}?format=%C+%t+%w+%h`,
      {
        headers: { 'User-Agent': 'curl/7.0' },
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (!resp.ok) return '';
    return (await resp.text()).trim();
  } catch (e) {
    log.warn(`weather fetch failed: ${e}`);
    return '';
  }
}
```

**Purpose:** Fetch weather from wttr.in (plain text, no dependencies).

**Format:** `%C+%t+%w+%h` = Condition + Temperature + Wind + Humidity

**Example output:** `☀️+15°C+↑15km/h+62%`

## Headlines Fetch

```typescript
async function fetchHeadlines(): Promise<string> {
  try {
    const resp = await fetch('https://feeds.bbci.co.uk/news/rss.xml', {
      headers: { 'User-Agent': 'curl/7.0' },
      signal: AbortSignal.timeout(10_000),
    });
    if (!resp.ok) return '';
    const xml = await resp.text();

    // Lightweight RSS title extraction - no XML parser needed
    const items: string[] = [];
    const itemRe = /<item>[\s\S]*?<\/item>/g;
    const titleRe = /<title><!\[CDATA\[(.*?)\]\]><\/title>|<title>(.*?)<\/title>/;
    let match: RegExpExecArray | null;
    let count = 0;

    while ((match = itemRe.exec(xml)) !== null && count < 5) {
      const titleMatch = titleRe.exec(match[0]);
      const title = titleMatch?.[1] || titleMatch?.[2];
      if (title) {
        items.push(`- ${title}`);
        count++;
      }
    }

    return items.join('\n');
  } catch (e) {
    log.warn(`headlines fetch failed: ${e}`);
    return '';
  }
}
```

**Purpose:** Extract top 5 headlines from BBC RSS feed.

**Technique:** Regex-based extraction (no XML parser dependency).

## Context Assembly

### gatherContext

```typescript
async function gatherContext(): Promise<string> {
  const config = getConfig();
  const parts: string[] = [];

  // Weather
  const weather = await fetchWeather();
  if (weather) {
    parts.push(`## Weather in Leeds\n${weather}`);
  }

  // Headlines
  const headlines = await fetchHeadlines();
  if (headlines) {
    parts.push(`## UK headlines\n${headlines}`);
  }

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    const lines = threads.slice(0, 5).map(
      (t) => `- ${t.name}: ${t.summary || '...'}`,
    );
    parts.push(`## Active threads\n${lines.join('\n')}`);
  }

  // Recent sessions (last 2 days)
  const summaries = getRecentSummaries(3);
  if (summaries.length > 0) {
    const lines = summaries.map(
      (s) => `- ${s.created_at}: ${(s.content || 'No summary').slice(0, 200)}`,
    );
    parts.push(`## Recent sessions\n${lines.join('\n')}`);
  }

  // Recent observations
  const observations = getRecentObservations(5);
  if (observations.length > 0) {
    const lines = observations.map((o) => `- ${o.content}`);
    parts.push(`## Recent observations\n${lines.join('\n')}`);
  }

  // Companion reflections (latest from Obsidian)
  const reflectionsPath = path.join(
    config.OBSIDIAN_AGENT_NOTES,
    'notes',
    'reflections.md',
  );
  try {
    if (fs.existsSync(reflectionsPath)) {
      let content = fs.readFileSync(reflectionsPath, 'utf-8');
      if (content.length > 800) {
        content = '...' + content.slice(-800);
      }
      parts.push(`## Your recent reflections\n${content}`);
    }
  } catch { /* non-critical */ }

  return parts.join('\n\n');
}
```

**Sections:**
1. Weather (wttr.in)
2. UK headlines (BBC RSS)
3. Active threads (up to 5)
4. Recent sessions (last 3 summaries)
5. Recent observations (last 5)
6. Companion reflections (last 800 chars)

## TTS Pre-Synthesis

```typescript
async function synthesiseAudio(text: string): Promise<string> {
  try {
    const audioPath = await synthesiseSync(text);
    if (audioPath) {
      const stat = fs.statSync(audioPath);
      if (stat.size > 100) return audioPath;
    }
  } catch (e) {
    log.warn(`TTS failed: ${e}`);
  }
  return '';
}
```

**Purpose:** Pre-synthesize brief audio for instant playback on launch.

**Validation:** Check file size > 100 bytes (avoid empty/corrupt files).

## Main Function

### morningBrief

```typescript
export async function morningBrief(): Promise<void> {
  // Ensure DB is initialised (needed when running standalone via launchd)
  initDb();

  const context = await gatherContext();
  if (!context.trim()) {
    log.info('No context gathered. Skipping.');
    return;
  }

  log.info('Generating morning brief...');

  let brief: string;
  try {
    brief = await runInferenceOneshot(
      [{ role: 'user', content: context }],
      loadPrompt('morning-brief', BRIEF_FALLBACK),
      60_000,  // 1 minute timeout
    );
  } catch (e) {
    log.error(`Brief generation failed: ${e}`);
    return;
  }

  if (!brief.trim()) {
    log.info('Empty brief generated. Skipping.');
    return;
  }

  log.info(`Brief generated (${brief.length} chars)`);

  // Queue message for next launch
  const audioPath = await synthesiseAudio(brief);
  await queueMessage(brief, 'morning-brief', audioPath);
  log.info('Brief queued');

  // Send via Telegram
  try {
    await sendTelegram(brief);
    log.info('Brief sent via Telegram');
  } catch (e) {
    log.warn(`Telegram send failed: ${e}`);
  }

  // Send macOS notification
  sendNotification('Morning Brief', brief.slice(0, 200));
  log.info('Notification sent');
}
```

**Flow:**
1. Initialize database
2. Gather context (weather, headlines, threads, etc.)
3. Generate brief via oneshot inference (1 min timeout)
4. Pre-synthesize audio
5. Queue message for next launch
6. Send via Telegram
7. Send macOS notification

## Job Registration

```typescript
registerJob({
  name: 'morning-brief',
  description: 'Morning brief with weather and headlines',
  gates: [
    // Only run between 6am-9am
    () => {
      const hour = new Date().getHours();
      if (hour < 6 || hour >= 9) {
        return 'Outside morning window';
      }
      return null;
    },
  ],
  run: async () => {
    await morningBrief();
    return 'Morning brief delivered';
  },
});
```

**Gate:** Only run between 6am-9am (allows for schedule variance).

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Database queries |
| `~/.atrophy/agents/<name>/data/.message_queue.json` | Queued message |
| `<Obsidian>/notes/reflections.md` | Companion reflections |
| `/tmp/atrophy-tts-*.mp3` | Pre-synthesized audio |

## Exported API

| Function | Purpose |
|----------|---------|
| `morningBrief()` | Generate and deliver morning brief |
| `fetchWeather(location)` | Fetch weather from wttr.in |
| `fetchHeadlines()` | Fetch BBC headlines |
| `gatherContext()` | Gather all context material |
| `synthesiseAudio(text)` | Pre-synthesize brief audio |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/channels/cron/scheduler.ts` - Cron scheduling
- `src/main/queue.ts` - Message queue
- `src/main/channels/telegram/api.ts` - Telegram sending
