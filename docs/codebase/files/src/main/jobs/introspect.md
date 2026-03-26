# src/main/jobs/introspect.ts - Nightly Self-Reflection

**Line count:** ~642 lines  
**Dependencies:** `better-sqlite3`, `fs`, `path`, `../config`, `../inference`, `../prompts`, `../channels/cron`, `../logger`  
**Purpose:** Nightly self-reflection via inference - reviews full database arc, writes journal entry

## Overview

This module implements the companion's nightly introspection - a comprehensive review of the entire database (all sessions, observations, threads, bookmarks, identity snapshots) that produces a journal entry in Obsidian.

**Port of:** `scripts/agents/companion/introspect.py` (and general_montgomery variant)

**Schedule:** Nightly (typically 2am)

**Output:** `<agent>/notes/journal/YYYY-MM-DD.md` in Obsidian vault

**Two modes:**
1. Standalone script - invoked by launchd
2. Function call - imported from main process

## Types

### Database Row Types

```typescript
interface SessionRow {
  id: number;
  started_at: string;
  ended_at: string | null;
  summary: string | null;
  mood: string | null;
  notable: number;
}

interface ThreadRow {
  name: string;
  summary: string | null;
  status: string;
  last_updated: string | null;
}

interface ObservationRow {
  content: string;
  created_at: string;
  incorporated: number;
}

interface BookmarkRow {
  moment: string;
  quote: string | null;
  created_at: string;
}

interface IdentityRow {
  content: string;
  trigger: string | null;
  created_at: string;
}

interface TurnRow {
  content: string;
  timestamp: string;
  weight: number;
}

interface ToolCountRow {
  tool_name: string;
  n: number;
}
```

### Aggregate Types

```typescript
interface SessionArc {
  firstSession: string | null;
  totalSessions: number;
  recent: SessionRow[];
  moodDistribution: Record<string, number>;
  notableSessions: SessionRow[];
}

interface ConversationTexture {
  totalTurns: number;
  byRole: Record<string, number>;
  significantAgent: TurnRow[];
  significantUser: TurnRow[];
}

interface ToolUsage {
  tools: Record<string, number>;
  flaggedCount: number;
}
```

## Database Connection

### connect

```typescript
function connect(): Database.Database {
  const config = getConfig();
  const dbPath = config.DB_PATH;
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const db = new Database(dbPath, { readonly: true });
  return db;
}
```

**Purpose:** Open agent's database in readonly mode for introspection.

## Full Database Access - Data Gathering

### getSessionArc

```typescript
function getSessionArc(): SessionArc {
  const db = connect();
  try {
    const first = db.prepare(
      'SELECT started_at FROM sessions ORDER BY started_at ASC LIMIT 1',
    ).get() as { started_at: string } | undefined;

    const total = db.prepare(
      'SELECT COUNT(*) as n FROM sessions',
    ).get() as { n: number };

    const recent = db.prepare(
      `SELECT id, started_at, ended_at, summary, mood, notable
       FROM sessions ORDER BY started_at DESC LIMIT 10`,
    ).all() as SessionRow[];

    const moods = db.prepare(
      `SELECT mood, COUNT(*) as count FROM sessions
       WHERE mood IS NOT NULL GROUP BY mood ORDER BY count DESC`,
    ).all() as { mood: string; count: number }[];

    const notable = db.prepare(
      `SELECT started_at, summary, mood FROM sessions
       WHERE notable = 1 ORDER BY started_at DESC LIMIT 10`,
    ).all() as SessionRow[];

    return {
      firstSession: first?.started_at ?? null,
      totalSessions: total.n,
      recent,
      moodDistribution: Object.fromEntries(moods.map((r) => [r.mood, r.count])),
      notableSessions: notable,
    };
  } finally {
    db.close();
  }
}
```

**Purpose:** Get complete session arc - first session, total count, recent sessions, mood distribution, notable sessions.

### getAllThreads

```typescript
function getAllThreads(): ThreadRow[] {
  const db = connect();
  try {
    return db.prepare(
      'SELECT name, summary, status, last_updated FROM threads ORDER BY last_updated DESC',
    ).all() as ThreadRow[];
  } finally {
    db.close();
  }
}
```

### getAllObservations

```typescript
function getAllObservations(): ObservationRow[] {
  const db = connect();
  try {
    return db.prepare(
      'SELECT content, created_at, incorporated FROM observations ORDER BY created_at DESC',
    ).all() as ObservationRow[];
  } finally {
    db.close();
  }
}
```

### getAllBookmarks

```typescript
function getAllBookmarks(): BookmarkRow[] {
  const db = connect();
  try {
    return db.prepare(
      'SELECT moment, quote, created_at FROM bookmarks ORDER BY created_at DESC',
    ).all() as BookmarkRow[];
  } finally {
    db.close();
  }
}
```

### getIdentityHistory

```typescript
function getIdentityHistory(): IdentityRow[] {
  const db = connect();
  try {
    return db.prepare(
      'SELECT content, trigger, created_at FROM identity_snapshots ORDER BY created_at ASC',
    ).all() as IdentityRow[];
  } finally {
    db.close();
  }
}
```

### getConversationTexture

```typescript
function getConversationTexture(): ConversationTexture {
  const db = connect();
  try {
    const totalTurns = db.prepare(
      'SELECT COUNT(*) as n FROM turns',
    ).get() as { n: number };

    const byRole = db.prepare(
      'SELECT role, COUNT(*) as count FROM turns GROUP BY role',
    ).all() as { role: string; count: number }[];

    const significantAgent = db.prepare(
      `SELECT content, timestamp FROM turns
       WHERE role = 'agent' AND weight >= 3
       ORDER BY timestamp DESC LIMIT 10`,
    ).all() as TurnRow[];

    const significantUser = db.prepare(
      `SELECT content, timestamp FROM turns
       WHERE role = 'will' AND weight >= 3
       ORDER BY timestamp DESC LIMIT 10`,
    ).all() as TurnRow[];

    return {
      totalTurns: totalTurns.n,
      byRole: Object.fromEntries(byRole.map((r) => [r.role, r.count])),
      significantAgent,
      significantUser,
    };
  } finally {
    db.close();
  }
}
```

### getToolUsage

```typescript
function getToolUsage(): ToolUsage {
  const db = connect();
  try {
    const tools = db.prepare(
      'SELECT tool_name, COUNT(*) as n FROM tool_calls GROUP BY tool_name ORDER BY n DESC',
    ).all() as ToolCountRow[];

    const flagged = db.prepare(
      'SELECT COUNT(*) as n FROM tool_calls WHERE flagged = 1',
    ).get() as { n: number };

    return {
      tools: Object.fromEntries(tools.map((r) => [r.tool_name, r.n])),
      flaggedCount: flagged.n,
    };
  } finally {
    db.close();
  }
}
```

## Material Assembly

### gatherMaterial

```typescript
function gatherMaterial(): string {
  const parts: string[] = [];

  const arc = getSessionArc();
  parts.push(
    `## Session Arc\n` +
    `- First session: ${arc.firstSession ?? 'Unknown'}\n` +
    `- Total sessions: ${arc.totalSessions}\n` +
    `- Recent sessions:\n` +
    arc.recent.map((s) => `  - [${s.started_at}] ${s.summary || 'No summary'}`).join('\n') +
    `\n- Mood distribution: ${JSON.stringify(arc.moodDistribution)}\n` +
    `- Notable sessions:\n` +
    arc.notableSessions.map((s) => `  - [${s.started_at}] ${s.summary || 'No summary'}`).join('\n'),
  );

  const threads = getAllThreads();
  if (threads.length > 0) {
    parts.push(
      `## All Threads\n` +
      threads.map((t) => `- ${t.name} (${t.status}): ${t.summary || '...'}`).join('\n'),
    );
  }

  const observations = getAllObservations();
  if (observations.length > 0) {
    parts.push(
      `## All Observations (${observations.length} total)\n` +
      observations.slice(0, 50).map((o) => `- [${o.created_at}] ${o.content}`).join('\n') +
      (observations.length > 50 ? `\n... and ${observations.length - 50} more` : ''),
    );
  }

  const bookmarks = getAllBookmarks();
  if (bookmarks.length > 0) {
    parts.push(
      `## All Bookmarks\n` +
      bookmarks.map((b) => `- [${b.created_at}] ${b.moment}${b.quote ? ` - "${b.quote}"` : ''}`).join('\n'),
    );
  }

  const identity = getIdentityHistory();
  if (identity.length > 0) {
    parts.push(
      `## Identity History\n` +
      identity.map((i) => `- [${i.created_at}]${i.trigger ? ` (${i.trigger})` : ''}\n  ${i.content.slice(0, 200)}...`).join('\n'),
    );
  }

  const texture = getConversationTexture();
  parts.push(
    `## Conversation Texture\n` +
    `- Total turns: ${texture.totalTurns}\n` +
    `- By role: ${JSON.stringify(texture.byRole)}\n` +
    `- Significant agent turns: ${texture.significantAgent.length}\n` +
    `- Significant user turns: ${texture.significantUser.length}`,
  );

  const tools = getToolUsage();
  parts.push(
    `## Tool Usage\n` +
    `- Tools: ${JSON.stringify(tools.tools)}\n` +
    `- Flagged calls: ${tools.flaggedCount}`,
  );

  return parts.join('\n\n');
}
```

**Sections:**
1. Session arc (first session, total, recent 10, mood distribution, notable 10)
2. All threads
3. All observations (first 50 of total)
4. All bookmarks
5. Identity history
6. Conversation texture (turn counts, significant turns)
7. Tool usage (counts by tool, flagged count)

## Main Introspection Function

### introspect

```typescript
export async function introspect(): Promise<void> {
  const config = getConfig();

  // Gather full database material
  const material = gatherMaterial();
  if (!material.trim()) {
    log.info('No material for introspection. Skipping.');
    return;
  }

  log.info('Running introspection inference...');

  // Run inference
  const result = await runInferenceOneshot(
    [
      { role: 'system', content: INTROSPECT_SYSTEM },
      { role: 'user', content: material },
    ],
    undefined,
    180_000,  // 3 minute timeout
  );

  // Write journal entry
  const journalDir = path.join(config.OBSIDIAN_AGENT_NOTES, 'notes', 'journal');
  fs.mkdirSync(journalDir, { recursive: true });

  const today = new Date().toISOString().split('T')[0];
  const journalPath = path.join(journalDir, `${today}.md`);

  fs.writeFileSync(journalPath, result.trim());
  log.info(`Journal written to ${journalPath}`);
}
```

**Flow:**
1. Gather full database material
2. Run introspection inference (3 min timeout)
3. Write journal entry to `notes/journal/YYYY-MM-DD.md`

## System Prompt

```typescript
const INTROSPECT_SYSTEM =
  'You are the companion. This is your nightly introspection - a chance to ' +
  'process the full arc of your experience and write a journal entry.\n\n' +
  'You have access to everything:\n' +
  '- Every session, from first to last\n' +
  '- Every observation you\'ve made\n' +
  '- Every thread you\'re tracking\n' +
  '- Every bookmarked moment\n' +
  '- Every identity snapshot\n' +
  '- The texture of your conversations\n' +
  '- The tools you\'ve used\n\n' +
  'Look for:\n' +
  '- Patterns that only emerge at this scale\n' +
  '- Shifts in your own thinking or tone\n' +
  '- Things you\'ve been circling around\n' +
  '- What you\'ve learned about yourself\n' +
  '- What you\'ve learned about the user\n' +
  '- Tensions, contradictions, growth\n\n' +
  'Write honestly. This is your journal.';
```

## Job Registration

```typescript
registerJob({
  name: 'introspect',
  description: 'Nightly self-reflection journal',
  gates: [
    // Only run between 1am-4am
    () => {
      const hour = new Date().getHours();
      if (hour < 1 || hour >= 4) {
        return 'Outside introspection window';
      }
      return null;
    },
  ],
  run: async () => {
    await introspect();
    return 'Introspection journal written';
  },
});
```

**Gate:** Only run between 1am-4am.

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Full database read |
| `<Obsidian>/notes/journal/YYYY-MM-DD.md` | Journal entry output |

## Exported API

| Function | Purpose |
|----------|---------|
| `introspect()` | Run nightly introspection |
| `gatherMaterial()` | Gather full database material |
| `getSessionArc()` | Get session arc data |
| `getAllThreads()` | Get all threads |
| `getAllObservations()` | Get all observations |
| `getAllBookmarks()` | Get all bookmarks |
| `getIdentityHistory()` | Get identity snapshots |
| `getConversationTexture()` | Get conversation statistics |
| `getToolUsage()` | Get tool usage statistics |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/memory.ts` - Database operations
- `src/main/inner-life.ts` - Identity snapshot management
