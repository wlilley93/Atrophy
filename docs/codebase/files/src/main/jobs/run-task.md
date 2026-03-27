# src/main/jobs/run-task.ts - Generic Task Runner

**Dependencies:** `fs`, `path`, `../config`, `../logger`, `../inference`, `../queue`, `../notify`, `../channels/telegram`, `../tts`, `../memory`  
**Purpose:** Execute prompt-based tasks defined in Obsidian - scheduled via manage_schedule

## Overview

This module provides a generic task runner for the companion agent. Tasks are defined in Obsidian markdown files with YAML frontmatter specifying delivery method, voice synthesis, and data sources. The companion can schedule arbitrary recurring tasks without writing code.


**Usage:**
```bash
node run-task.js <task_name>
```

**Task location:** `Agent Workspace/<agent>/tasks/<task_name>.md`

## Task File Format

```markdown
---
deliver: message_queue     # message_queue | telegram | notification | obsidian
voice: true                # pre-synthesise TTS audio
sources:                   # optional data sources to fetch before running
  - weather
  - headlines
  - threads
  - summaries
  - observations
---

You are the companion. Fetch and summarise the latest UK news headlines.
Keep it to 3-5 bullet points. Be conversational.
```

**Frontmatter fields:**
- `deliver`: Delivery channel
- `voice`: Whether to pre-synthesize TTS
- `sources`: Data sources to gather

## Types

### TaskMeta

```typescript
interface TaskMeta {
  deliver?: string;
  voice?: boolean;
  sources?: string[];
  [key: string]: unknown;
}
```

## Task Loading

### tasksDir

```typescript
function tasksDir(): string {
  const config = getConfig();
  return path.join(config.OBSIDIAN_AGENT_DIR, 'tasks');
}
```

**Purpose:** Get task definitions directory.

### loadTask

```typescript
function loadTask(name: string): { meta: TaskMeta; prompt: string } {
  const taskPath = path.join(tasksDir(), `${name}.md`);
  if (!fs.existsSync(taskPath)) {
    throw new Error(`Task not found: ${taskPath}`);
  }

  const content = fs.readFileSync(taskPath, 'utf-8');
  let meta: TaskMeta = {};
  let prompt = content;

  if (content.startsWith('---')) {
    const parts = content.split('---', 3);
    if (parts.length >= 3) {
      const frontmatter = parts[1].trim();
      prompt = parts[2].trim();

      // Simple YAML parsing (no dependency)
      for (const line of frontmatter.split('\n')) {
        const stripped = line.trim();
        if (!stripped.includes(':')) continue;

        const colonIdx = stripped.indexOf(':');
        const key = stripped.slice(0, colonIdx).trim();
        const val = stripped.slice(colonIdx + 1).trim();

        // Skip list heads (will be parsed separately)
        if (!val || val.startsWith('-') || val.startsWith('[')) continue;

        if (val.toLowerCase() === 'true' || val.toLowerCase() === 'yes') {
          meta[key] = true;
        } else if (val.toLowerCase() === 'false' || val.toLowerCase() === 'no') {
          meta[key] = false;
        } else {
          meta[key] = val;
        }
      }

      // Parse sources list
      if (!meta.sources) {
        const sources: string[] = [];
        let inSources = false;
        for (const line of frontmatter.split('\n')) {
          const stripped = line.trim();
          if (stripped.startsWith('sources:')) {
            inSources = true;
            continue;
          }
          if (inSources && stripped.startsWith('- ')) {
            sources.push(stripped.slice(2).trim());
          } else if (inSources && !stripped.startsWith('-')) {
            inSources = false;
          }
        }
        if (sources.length > 0) {
          meta.sources = sources;
        }
      }
    }
  }

  return { meta, prompt };
}
```

**Purpose:** Load task file and parse YAML frontmatter.

**Parsing:**
- Simple key: value parsing (no YAML library)
- Boolean conversion (true/false/yes/no)
- List parsing for sources

## Source Gathering

### gatherSources

```typescript
async function gatherSources(sources: string[]): Promise<string> {
  const parts: string[] = [];

  if (sources.includes('weather')) {
    try {
      const resp = await fetch('https://wttr.in/Leeds?format=%C+%t+%w+%h', {
        headers: { 'User-Agent': 'curl/7.0' },
        signal: AbortSignal.timeout(10_000),
      });
      if (resp.ok) {
        const weather = (await resp.text()).trim();
        if (weather) {
          parts.push(`## Weather\n${weather}`);
        }
      }
    } catch { /* non-fatal */ }
  }

  if (sources.includes('headlines')) {
    try {
      const resp = await fetch('https://feeds.bbci.co.uk/news/rss.xml', {
        headers: { 'User-Agent': 'curl/7.0' },
        signal: AbortSignal.timeout(10_000),
      });
      const xml = await resp.text();
      // Simple XML title extraction
      const titles: string[] = [];
      const itemRe = /<item>[\s\S]*?<\/item>/g;
      const titleRe = /<title><!\[CDATA\[(.*?)\]\]><\/title>|<title>(.*?)<\/title>/;
      let match: RegExpExecArray | null;
      while ((match = itemRe.exec(xml)) !== null && titles.length < 8) {
        const titleMatch = titleRe.exec(match[0]);
        if (titleMatch) {
          titles.push(`- ${titleMatch[1] || titleMatch[2]}`);
        }
      }
      if (titles.length > 0) {
        parts.push(`## Headlines\n${titles.join('\n')}`);
      }
    } catch { /* non-fatal */ }
  }

  if (sources.includes('threads')) {
    try {
      const threads = getActiveThreads();
      if (threads.length > 0) {
        const lines = threads.slice(0, 5).map(
          (t) => `- ${t.name}: ${t.summary || '...'}`,
        );
        parts.push(`## Active threads\n${lines.join('\n')}`);
      }
    } catch { /* non-fatal */ }
  }

  if (sources.includes('summaries')) {
    try {
      const summaries = getRecentSummaries(3);
      if (summaries.length > 0) {
        const lines = summaries.map(
          (s) => `- ${(s.content || '').slice(0, 200)}`,
        );
        parts.push(`## Recent summaries\n${lines.join('\n')}`);
      }
    } catch { /* non-fatal */ }
  }

  if (sources.includes('observations')) {
    try {
      const observations = getRecentObservations(5);
      if (observations.length > 0) {
        const lines = observations.map((o) => `- ${o.content}`);
        parts.push(`## Recent observations\n${lines.join('\n')}`);
      }
    } catch { /* non-fatal */ }
  }

  return parts.join('\n\n');
}
```

**Supported sources:**
1. **weather** - wttr.in (Leeds)
2. **headlines** - BBC RSS feed (top 8)
3. **threads** - Active threads (top 5)
4. **summaries** - Recent session summaries (last 3)
5. **observations** - Recent observations (last 5)

## Delivery Methods

### deliverResult

```typescript
async function deliverResult(
  result: string,
  meta: TaskMeta,
): Promise<void> {
  const config = getConfig();
  const delivery = meta.deliver || 'message_queue';

  if (delivery === 'message_queue') {
    // Queue for next app launch
    await queueMessage(result, 'task');
    log.info('Queued for next launch');
  } else if (delivery === 'telegram') {
    // Send via Telegram
    if (meta.voice && config.TELEGRAM_BOT_TOKEN && config.TELEGRAM_CHAT_ID) {
      const audioPath = await synthesiseSync(result);
      if (audioPath) {
        const oggPath = await convertToOgg(audioPath);
        if (oggPath) {
          await sendVoiceNote(oggPath, result);
          cleanupFiles([audioPath, oggPath]);
          log.info('Sent voice note via Telegram');
          return;
        }
      }
    }
    await telegramSend(result);
    log.info('Sent via Telegram');
  } else if (delivery === 'notification') {
    // macOS notification
    sendNotification('Task Result', result.slice(0, 200));
    log.info('Notification sent');
  } else if (delivery === 'obsidian') {
    // Write to Obsidian
    const notesDir = path.join(config.OBSIDIAN_AGENT_NOTES, 'notes', 'tasks');
    fs.mkdirSync(notesDir, { recursive: true });
    const now = new Date();
    const filePath = path.join(notesDir, `task-${now.toISOString().slice(0, 16)}.md`);
    fs.writeFileSync(filePath, `# Task Result\n\n*${now.toISOString()}*\n\n${result}`);
    log.info(`Written to ${filePath}`);
  }
}
```

**Delivery channels:**
1. **message_queue** - Queue for next app launch
2. **telegram** - Send via Telegram (optionally as voice note)
3. **notification** - macOS notification
4. **obsidian** - Write to notes/tasks/

## Main Entry Point

### runTask

```typescript
export async function runTask(taskName: string): Promise<void> {
  const config = getConfig();

  // Load task
  const { meta, prompt } = loadTask(taskName);
  log.info(`Running task: ${taskName}`);

  // Gather sources
  let context = '';
  if (meta.sources && meta.sources.length > 0) {
    context = await gatherSources(meta.sources);
    if (context) {
      context = `## Context\n${context}\n\n`;
    }
  }

  // Run inference
  const fullPrompt = `${context}${prompt}`;
  log.info('Running inference...');

  let result: string;
  try {
    result = await runInferenceOneshot(
      [{ role: 'user', content: fullPrompt }],
      undefined,
      120_000,  // 2 minute timeout
    );
  } catch (e) {
    log.error(`Inference failed: ${e}`);
    return;
  }

  if (!result || !result.trim()) {
    log.info('Empty result.');
    return;
  }

  log.info(`Result generated (${result.length} chars)`);

  // Deliver result
  await deliverResult(result, meta);
}
```

**Flow:**
1. Load task definition
2. Gather specified sources
3. Build full prompt (context + task prompt)
4. Run inference (2 min timeout)
5. Deliver result via specified channel

## CLI Entry Point

```typescript
if (require.main === module) {
  const taskName = process.argv[2];
  if (!taskName) {
    console.error('Usage: node run-task.js <task_name>');
    process.exit(1);
  }
  runTask(taskName).catch((e) => {
    log.error(`Fatal: ${e}`);
    process.exit(1);
  });
}
```

**Usage:**
```bash
node run-task.js news-brief
```

## File I/O

| File | Purpose |
|------|---------|
| `<Obsidian>/Agent Workspace/<agent>/tasks/*.md` | Task definitions |
| `<Obsidian>/Agent Workspace/<agent>/notes/tasks/*.md` | Task results (obsidian delivery) |
| `~/.atrophy/agents/<name>/data/.message_queue.json` | Queued results |
| `/tmp/atrophy-tts-*.mp3` | Temp TTS audio |
| `/tmp/atrophy-voice-*.ogg` | Temp OGG audio |

## Exported API

| Function | Purpose |
|----------|---------|
| `runTask(taskName)` | Run specified task |
| `loadTask(name)` | Load task definition |
| `gatherSources(sources)` | Gather specified data sources |
| `deliverResult(result, meta)` | Deliver via specified channel |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/channels/cron/scheduler.ts` - Task scheduling via manage_schedule
- `src/main/memory.ts` - Thread management for task creation
