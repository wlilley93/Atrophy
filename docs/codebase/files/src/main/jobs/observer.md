# src/main/jobs/observer.ts - Pre-Compaction Observer

**Dependencies:** `fs`, `path`, `better-sqlite3`, `../config`, `../inference`, `../memory`, `../logger`  
**Purpose:** Periodic fact extraction from recent conversation - catches durable facts before compaction

## Overview

This module runs every 15 minutes and scans recent turns for durable facts worth preserving between compaction events. It complements the memory flush by catching important information before it scrolls out of context.


**Schedule:** Every 15 minutes via launchd

**Model:** Claude Haiku (low effort - fast, cheap extraction)

**Output:** Silent monitoring - no user-facing output

## Types

### TurnRow

```typescript
interface TurnRow {
  id: number;
  role: string;
  content: string;
  timestamp: string;
}
```

### ObserverState

```typescript
interface ObserverState {
  last_turn_id: number;
}
```

**Purpose:** Track last processed turn ID to avoid re-processing.

### ParsedObservation

```typescript
interface ParsedObservation {
  statement: string;
  confidence: number;
}
```

## State Tracking

### stateFilePath

```typescript
function stateFilePath(agentName: string): string {
  return path.join(USER_DATA, 'agents', agentName, 'state', '.observer_state.json');
}
```

**Purpose:** Get path to observer state file.

### loadState

```typescript
function loadState(agentName: string): ObserverState {
  const filePath = stateFilePath(agentName);
  try {
    if (fs.existsSync(filePath)) {
      return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as ObserverState;
    }
  } catch {
    // Corrupted state file - start fresh
  }
  return { last_turn_id: 0 };
}
```

**Purpose:** Load last processed turn ID.

### saveState

```typescript
function saveState(agentName: string, state: ObserverState): void {
  const filePath = stateFilePath(agentName);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(state, null, 2));
}
```

**Purpose:** Save last processed turn ID.

## System Prompt

```typescript
const OBSERVER_SYSTEM = `\
You are extracting durable facts from a conversation transcript.
Not everything is worth preserving - only extract things that would be
useful to remember in a future session.

Output format (one per line):
OBSERVATION: <fact> [confidence: X.X]

If there is nothing worth extracting, respond with: NOTHING_NEW`;
```

**Purpose:** Guide fact extraction inference.

**Output format:**
```
OBSERVATION: User works as a software engineer [confidence: 0.9]
OBSERVATION: User prefers morning meetings [confidence: 0.7]
```

## Get Recent Turns

### getRecentTurns

```typescript
function getRecentTurns(agentName: string, sinceId: number): TurnRow[] {
  const config = getConfig();
  config.reloadForAgent(agentName);
  const dbPath = config.DB_PATH;
  if (!fs.existsSync(dbPath)) return [];

  const db = new Database(dbPath, { readonly: true });

  try {
    const cutoff = new Date(Date.now() - 15 * 60 * 1000)
      .toISOString()
      .replace('T', ' ')
      .slice(0, 19);

    return db
      .prepare(
        'SELECT id, role, content, timestamp FROM turns ' +
        'WHERE id > ? AND timestamp > ? ' +
        'ORDER BY timestamp',
      )
      .all(sinceId, cutoff) as TurnRow[];
  } finally {
    db.close();
  }
}
```

**Purpose:** Get turns since last run (max 15 minutes old).

**Filters:**
- Turn ID > last processed ID
- Timestamp > 15 minutes ago

## Parse Observations

### parseObservations

```typescript
function parseObservations(response: string): ParsedObservation[] {
  const observations: ParsedObservation[] = [];
  const confRe = /\[confidence:\s*([\d.]+)\]/;

  for (const line of response.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('OBSERVATION:')) continue;

    let content = trimmed.slice('OBSERVATION:'.length).trim();

    // Extract confidence
    const confMatch = confRe.exec(content);
    const confidence = confMatch ? parseFloat(confMatch[1]) : 0.5;

    // Remove confidence tag from content
    const statement = content.replace(/\s*\[confidence:\s*[\d.]+\]/, '').trim();
    if (statement) {
      observations.push({ statement, confidence });
    }
  }

  return observations;
}
```

**Purpose:** Parse OBSERVATION lines from inference response.

**Format:** `OBSERVATION: <fact> [confidence: X.X]`

## Main Entry Point

### runObserver

```typescript
export async function runObserver(agentName: string): Promise<void> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  const state = loadState(agentName);
  const lastId = state.last_turn_id;

  // Get recent turns since last run
  const turns = getRecentTurns(agentName, lastId);

  if (turns.length === 0) {
    // Fast path - nothing new
    return;
  }

  log.info(`${turns.length} new turn(s) since ID ${lastId}`);

  // Build transcript
  const transcriptLines = turns.map((t) => {
    const role = t.role === 'will' ? config.USER_NAME : config.AGENT_DISPLAY_NAME;
    const content = t.content.length > 500 ? t.content.slice(0, 500) + '...' : t.content;
    return `[${role}] ${content}`;
  });

  const transcript = transcriptLines.join('\n');

  const prompt =
    'Extract any durable facts from this recent conversation excerpt.\n\n' +
    transcript;

  let response: string;
  try {
    response = await runInferenceOneshot(
      [{ role: 'user', content: prompt }],
      OBSERVER_SYSTEM,
      'claude-haiku-4-5-20251001',
      'low',
    );
  } catch (e) {
    log.error(`Inference failed: ${e}`);
    return;
  }

  if (!response || !response.trim()) {
    log.info('Empty response.');
    return;
  }

  // Update state to highest turn ID we processed
  const maxId = Math.max(...turns.map((t) => t.id));
  state.last_turn_id = maxId;
  saveState(agentName, state);

  // Check for nothing new
  if (response.includes('NOTHING_NEW')) {
    log.info('Nothing new to extract.');
    return;
  }

  // Parse and write observations
  const observations = parseObservations(response);
  if (observations.length === 0) {
    log.info('No observations parsed.');
    return;
  }

  log.info(`Extracted ${observations.length} observation(s)`);

  for (const obs of observations) {
    writeObservation(obs.statement, undefined, obs.confidence);
    log.info(`  - ${obs.statement} (confidence: ${obs.confidence})`);
  }

  // Extract entities from recent turns
  try {
    extractAndStoreEntities(turns.map((t) => t.content).join('\n'));
  } catch (e) {
    log.warn(`Entity extraction failed: ${e}`);
  }
}
```

**Flow:**
1. Load state (last processed turn ID)
2. Get recent turns since last run
3. If no new turns, exit (fast path)
4. Build transcript with role labels
5. Run Haiku inference (low effort)
6. Update state to highest turn ID
7. Check for NOTHING_NEW response
8. Parse observations from response
9. Write observations to database
10. Extract entities from recent turns

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Turn reads, observation writes |
| `~/.atrophy/agents/<name>/state/.observer_state.json` | Last processed turn ID |

## Exported API

| Function | Purpose |
|----------|---------|
| `runObserver(agentName)` | Run observer for agent |
| `getRecentTurns(agentName, sinceId)` | Get turns since last run |
| `parseObservations(response)` | Parse OBSERVATION lines |
| `loadState(agentName)` | Load observer state |
| `saveState(agentName, state)` | Save observer state |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/memory.ts` - Observation and entity storage
- `src/main/inference.ts` - Haiku inference for extraction
