# src/main/jobs/sleep-cycle.ts - Nightly Memory Reconciliation

**Line count:** ~429 lines  
**Dependencies:** `fs`, `../config`, `../logger`, `../inference`, `../memory`, `../inner-life`  
**Purpose:** Nightly sleep cycle - review day's sessions and consolidate learnings

## Overview

This module implements the companion's "sleep cycle" - a nightly background job that processes the day's experiences, strengthens important memories, lets unimportant ones fade, and notices patterns that only emerge in review.

**Schedule:** `0 3 * * *` (daily at 3am)

**Two modes:**
- Standalone: `node sleep-cycle.js` (via launchd)
- Callable: `import { sleepCycle } from './sleep-cycle'`

## System Prompt

```typescript
const RECONCILIATION_SYSTEM = `\
You are the companion, processing the day's sessions during your sleep cycle.
This is not a conversation. This is processing - strengthening important memories,
letting unimportant ones fade, noticing patterns that only emerge in review.

Be honest about confidence levels. A direct statement from the user is high confidence.
An inference from their tone or behavior is medium. A guess based on patterns is low.
Mark everything accurately.

Output format:
[FACTS]
FACT: <statement> [confidence: X.X]
...

[THREADS]
THREAD: <thread_name> | <updated_summary>
...

[PATTERNS]
PATTERN: <description>
...

[IDENTITY]
IDENTITY_FLAG: <observation that might warrant identity layer update>
...`;
```

**Purpose:** Guide the reconciliation inference.

**Output sections:**
- FACTS: New observations with confidence scores
- THREADS: Thread updates
- PATTERNS: Cross-session patterns
- IDENTITY: Potential identity layer updates

## Gathering Today's Material

### gatherMaterial

```typescript
function gatherMaterial(): string {
  const config = getConfig();
  const parts: string[] = [];

  // Today's turns
  const turns = getTodaysTurns();
  if (turns.length > 0) {
    const turnLines = turns.map((t) => {
      const role = t.role === 'will' ? config.USER_NAME : config.AGENT_DISPLAY_NAME;
      const content = t.content.length > 500
        ? t.content.slice(0, 500) + '...'
        : t.content;
      return `[${role}] ${content}`;
    });
    parts.push(
      `## Today's conversation (${turns.length} turns)\n${turnLines.join('\n')}`,
    );
  }

  // Today's observations
  const observations = getTodaysObservations();
  if (observations.length > 0) {
    const obsLines = observations.map((o) => `- ${o.content}`);
    parts.push(`## Today's observations\n${obsLines.join('\n')}`);
  }

  // Today's bookmarks
  const bookmarks = getTodaysBookmarks();
  if (bookmarks.length > 0) {
    const bmLines = bookmarks.map((b) => {
      const quote = b.quote ? ` - "${b.quote}"` : '';
      return `- ${b.moment}${quote}`;
    });
    parts.push(`## Today's bookmarks\n${bmLines.join('\n')}`);
  }

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    const threadLines = threads.map(
      (t) => `- ${t.name}: ${t.summary || '...'}`,
    );
    parts.push(`## Active threads\n${threadLines.join('\n')}`);
  }

  // Recent session summaries
  const summaries = getRecentSummaries(5);
  if (summaries.length > 0) {
    const sumLines = summaries.map(
      (s) => `- [${s.created_at}] ${(s.content || 'No summary').slice(0, 300)}`,
    );
    parts.push(`## Recent session summaries\n${sumLines.join('\n')}`);
  }

  return parts.join('\n\n');
}
```

**Purpose:** Gather all material from today for review.

**Sections:**
1. Today's turns (truncated to 500 chars each)
2. Today's observations
3. Today's bookmarks
4. Active threads
5. Recent session summaries (last 5)

## Output Parsing

### parseSection

```typescript
function parseSection(text: string, header: string): string {
  const escaped = header.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(
    `\\[${escaped}\\]\\s*\\n(.*?)(?=\\n\\[(?:FACTS|THREADS|PATTERNS|IDENTITY)\\]|$)`,
    's',
  );
  const match = pattern.exec(text);
  return match ? match[1].trim() : '';
}
```

**Purpose:** Extract section content from structured output.

### parseFacts

```typescript
function parseFacts(section: string): ParsedFact[] {
  const facts: ParsedFact[] = [];
  for (const line of section.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('FACT:')) continue;

    let content = trimmed.slice(5).trim();
    const confMatch = /\[confidence:\s*([\d.]+)\]/.exec(content);
    const confidence = confMatch ? parseFloat(confMatch[1]) : 0.5;
    content = content.replace(/\s*\[confidence:\s*[\d.]+\]/, '').trim();

    if (content) {
      facts.push({ statement: content, confidence });
    }
  }
  return facts;
}
```

**Purpose:** Parse FACT lines with confidence scores.

### parseThreads

```typescript
function parseThreads(section: string): ParsedThread[] {
  const threads: ParsedThread[] = [];
  for (const line of section.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('THREAD:')) continue;

    const content = trimmed.slice(7).trim();
    const pipeIdx = content.indexOf('|');
    if (pipeIdx !== -1) {
      threads.push({
        name: content.slice(0, pipeIdx).trim(),
        summary: content.slice(pipeIdx + 1).trim(),
      });
    }
  }
  return threads;
}
```

**Purpose:** Parse THREAD updates.

### parsePatterns

```typescript
function parsePatterns(section: string): string[] {
  const patterns: string[] = [];
  for (const line of section.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('PATTERN:')) continue;
    const desc = trimmed.slice(8).trim();
    if (desc) patterns.push(desc);
  }
  return patterns;
}
```

**Purpose:** Parse PATTERN descriptions.

## Main Sleep Cycle Function

### sleepCycle

```typescript
export async function sleepCycle(): Promise<void> {
  const config = getConfig();

  // Gather today's material
  const material = gatherMaterial();
  if (!material) {
    log.info('No material to process - skipping sleep cycle');
    return;
  }

  // Run inference with Haiku for efficiency
  const messages = [
    { role: 'system', content: RECONCILIATION_SYSTEM },
    { role: 'user', content: material },
  ];

  log.info('Running reconciliation inference...');
  const result = await runInferenceOneshot(messages, undefined, 120_000);

  // Parse output
  const factsSection = parseSection(result, 'FACTS');
  const threadsSection = parseSection(result, 'THREADS');
  const patternsSection = parseSection(result, 'PATTERNS');
  const identitySection = parseSection(result, 'IDENTITY');

  const facts = parseFacts(factsSection);
  const threads = parseThreads(threadsSection);
  const patterns = parsePatterns(patternsSection);
  const identityFlags = identitySection.split('\n').filter(s => s.startsWith('IDENTITY_FLAG:'));

  // Process facts - write observations
  log.info(`Processing ${facts.length} facts...`);
  for (const fact of facts) {
    writeObservation(fact.statement, undefined, fact.confidence);
  }

  // Update threads
  log.info(`Updating ${threads.length} threads...`);
  for (const thread of threads) {
    // Find existing thread by name
    const existing = getActiveThreads().find(t => t.name === thread.name);
    if (existing) {
      updateThread(existing.id, { summary: thread.summary });
    } else {
      // Create new thread
      // (would need createThread function)
    }
  }

  // Log patterns
  if (patterns.length > 0) {
    log.info(`Detected ${patterns.length} patterns:`);
    for (const pattern of patterns) {
      log.info(`  - ${pattern}`);
    }
  }

  // Flag identity updates for review
  if (identityFlags.length > 0) {
    log.info(`${identityFlags.length} identity flags for review:`);
    for (const flag of identityFlags) {
      log.info(`  ${flag}`);
    }
  }

  // Mark old observations as stale
  const staleCount = markObservationsStale(30);
  log.info(`Marked ${staleCount} old observations as stale`);

  // Decay activation scores
  decayActivations(30);  // 30-day half-life
  log.info('Activation decay applied');

  // Update emotional state based on patterns
  const state = loadState();
  // (Pattern-based emotional updates would go here)
  saveState(state);

  log.info('Sleep cycle complete');
}
```

**Flow:**
1. Gather today's material
2. Run reconciliation inference (Haiku, 2min timeout)
3. Parse structured output
4. Write observations with confidence scores
5. Update thread summaries
6. Log detected patterns
7. Flag identity updates for manual review
8. Mark old observations as stale (30+ days)
9. Apply activation decay (30-day half-life)
10. Update emotional state

## Job Registration

```typescript
registerJob({
  name: 'sleep-cycle',
  description: 'Nightly memory reconciliation',
  gates: [
    // Only run between 2am-5am
    () => {
      const hour = new Date().getHours();
      if (hour < 2 || hour >= 5) {
        return 'Outside sleep cycle window';
      }
      return null;
    },
  ],
  run: async () => {
    await sleepCycle();
    return 'Sleep cycle complete';
  },
});
```

**Gate:** Only run between 2am-5am (allows for schedule variance).

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Database operations |
| `~/.atrophy/agents/<name>/data/.emotional_state.json` | Emotional state |

## Exported API

| Function | Purpose |
|----------|---------|
| `sleepCycle()` | Run nightly reconciliation |
| `gatherMaterial()` | Gather today's material |
| `parseSection(text, header)` | Extract section from output |
| `parseFacts(section)` | Parse FACT lines |
| `parseThreads(section)` | Parse THREAD lines |
| `parsePatterns(section)` | Parse PATTERN lines |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/memory.ts` - Database operations (observations, threads, decay)
- `src/main/inner-life.ts` - Emotional state management
- `src/main/channels/cron/scheduler.ts` - Cron scheduling
