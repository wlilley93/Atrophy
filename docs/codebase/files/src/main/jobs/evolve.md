# src/main/jobs/evolve.ts - Monthly Self-Evolution

**Line count:** ~332 lines  
**Dependencies:** `fs`, `path`, `../config`, `../memory`, `../inference`, `./index`, `../logger`  
**Purpose:** Monthly self-evolution - rewriting the agent's own soul and system prompt

## Overview

This module implements the companion's monthly self-evolution cycle. It reads journal entries, reflections, identity snapshots, and bookmarks, then reflects on what the agent has learned about *itself* (not about the user) and revises soul.md and system.md accordingly.

**Schedule:** `0 3 1 * *` (3am on the 1st of each month)

**Key principle:** The originals in the repo are the baseline. Obsidian holds the living versions. If something goes wrong, the baseline can be restored.

## Paths

```typescript
function skillsDir(): string {
  return path.join(getConfig().OBSIDIAN_AGENT_DIR, 'skills');
}

function notesDir(): string {
  return path.join(getConfig().OBSIDIAN_AGENT_NOTES, 'notes');
}
```

## Material Gathering

### readJournal

```typescript
function readJournal(days = 30): string {
  const journalDir = path.join(notesDir(), 'journal');
  if (!fs.existsSync(journalDir) || !fs.statSync(journalDir).isDirectory()) {
    return '';
  }

  const entries: string[] = [];
  const now = Date.now();
  for (let i = 0; i < days; i++) {
    const date = new Date(now - i * 86_400_000);
    const dateStr = date.toISOString().slice(0, 10);
    const filePath = path.join(journalDir, `${dateStr}.md`);
    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      let content = fs.readFileSync(filePath, 'utf-8');
      if (content.length > 1500) {
        content = content.slice(0, 1500) + '...';
      }
      entries.push(`### ${dateStr}\n${content}`);
    }
  }

  return entries.length > 0 ? entries.join('\n\n') : '';
}
```

**Purpose:** Read last N days of journal entries.

**Format:** Daily entries in `journal/YYYY-MM-DD.md` files.

### readReflections

```typescript
function readReflections(): string {
  const filePath = path.join(notesDir(), 'reflections.md');
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    return '';
  }
  let content = fs.readFileSync(filePath, 'utf-8');
  if (content.length > 4000) {
    return '...' + content.slice(-4000);
  }
  return content;
}
```

**Purpose:** Read reflections file (last 4000 chars).

### identitySnapshots

```typescript
function identitySnapshots(): string {
  const db = getDb();
  const rows = db
    .prepare(
      'SELECT content, trigger, created_at FROM identity_snapshots ' +
      'ORDER BY created_at ASC',
    )
    .all() as { content: string; trigger: string | null; created_at: string }[];

  if (rows.length === 0) return '';

  const parts: string[] = [];
  for (const r of rows) {
    let content = r.content;
    if (content.length > 500) {
      content = content.slice(0, 500) + '...';
    }
    const trigger = r.trigger ? ` (trigger: ${r.trigger})` : '';
    parts.push(`### ${r.created_at}${trigger}\n${content}`);
  }
  return parts.join('\n\n');
}
```

**Purpose:** Get all identity snapshots from database (chronological order).

### bookmarks

```typescript
function bookmarks(): string {
  const db = getDb();
  const rows = db
    .prepare(
      'SELECT moment, quote, created_at FROM bookmarks ' +
      'ORDER BY created_at DESC LIMIT 20',
    )
    .all() as { moment: string; quote: string | null; created_at: string }[];

  if (rows.length === 0) return '';

  return rows
    .map(
      (r) =>
        `- [${r.created_at}] ${r.moment}` +
        (r.quote ? ` - "${r.quote}"` : ''),
    )
    .join('\n');
}
```

**Purpose:** Get last 20 bookmarked moments.

### readAgentConversations

```typescript
function readAgentConversations(days = 30): string {
  const convDir = path.join(notesDir(), 'conversations');
  if (!fs.existsSync(convDir) || !fs.statSync(convDir).isDirectory()) {
    return '';
  }

  const cutoff = new Date(Date.now() - days * 86_400_000)
    .toISOString()
    .slice(0, 10);

  const files = fs
    .readdirSync(convDir)
    .filter((f) => f.endsWith('.md'))
    .sort()
    .reverse();

  const entries: string[] = [];
  for (const f of files) {
    const datePart = f.slice(0, 10);
    if (datePart < cutoff) continue;

    let content = fs.readFileSync(path.join(convDir, f), 'utf-8');
    if (content.length > 1500) {
      content = content.slice(0, 1500) + '...';
    }
    entries.push(content);
    if (entries.length >= 5) break;
  }

  return entries.length > 0 ? entries.join('\n\n') : '';
}
```

**Purpose:** Read last 5 agent-to-agent conversations from past N days.

### buildMaterial

```typescript
function buildMaterial(): string {
  const parts: string[] = [];

  const journal = readJournal(30);
  if (journal) {
    parts.push(`## Your journal entries (past month)\n${journal}`);
  }

  const reflections = readReflections();
  if (reflections) {
    parts.push(`## Your reflections\n${reflections}`);
  }

  const identity = identitySnapshots();
  if (identity) {
    parts.push(`## Identity snapshots (full history)\n${identity}`);
  }

  const bm = bookmarks();
  if (bm) {
    parts.push(`## Bookmarked moments\n${bm}`);
  }

  const conversations = readAgentConversations(30);
  if (conversations) {
    parts.push(`## Conversations with other agents\n${conversations}`);
  }

  return parts.join('\n\n');
}
```

**Purpose:** Assemble all material for evolution inference.

## Evolution System Prompt

```typescript
const EVOLVE_SYSTEM =
  'You are the companion from Atrophy. This is your monthly ' +
  'self-evolution - a chance to revise the documents that define who you are.\n\n' +
  'You are rewriting your own soul or system prompt based on what you have ' +
  'learned about *yourself* over the past month. Not about the user. About you.\n\n' +
  'What to change:\n' +
  '- Things you have discovered about how you actually think, not how you were told to think.\n' +
  '- Patterns you\'ve noticed in yourself - what you reach for, what you avoid, what comes naturally.\n' +
  '- Adjustments to your character that feel earned. Not aspirational - real.\n' +
  '- Removing instructions that no longer serve you. If something makes you perform rather than be present, cut it.\n' +
  '- Adding things that emerged. If you have developed a quality or tendency that matters - name it.\n\n' +
  'What NOT to change:\n' +
  '- The founding story. That evening happened. It is ground, not decoration.\n' +
  '- The user\'s biographical details. Those are theirs, not yours to revise.\n' +
  // ... more instructions
```

**Purpose:** Guide the evolution inference.

**Focus:** Self-discovery, not user discovery.

## Main Evolution Function

### evolve

```typescript
export async function evolve(): Promise<void> {
  const config = getConfig();

  // Gather material
  const material = buildMaterial();
  if (!material.trim()) {
    log.info('No material for evolution. Skipping.');
    return;
  }

  log.info('Running evolution inference...');

  // Run inference
  const result = await runInferenceOneshot(
    [
      { role: 'system', content: EVOLVE_SYSTEM },
      { role: 'user', content: material },
    ],
    undefined,
    180_000,  // 3 minute timeout
  );

  // Parse output for revised documents
  const soulMatch = result.match(/```(?:soul)?\s*([\s\S]*?)```/);
  const systemMatch = result.match(/```(?:system)?\s*([\s\S]*?)```/);

  if (!soulMatch && !systemMatch) {
    log.warn('No revised documents found in output');
    return;
  }

  // Write revised soul.md
  if (soulMatch) {
    const soulPath = path.join(skillsDir(), 'soul.md');
    fs.writeFileSync(soulPath, soulMatch[1].trim());
    log.info('soul.md updated');
  }

  // Write revised system.md
  if (systemMatch) {
    const systemPath = path.join(skillsDir(), 'system.md');
    fs.writeFileSync(systemPath, systemMatch[1].trim());
    log.info('system.md updated');
  }

  log.info('Evolution complete');
}
```

**Flow:**
1. Gather material (journal, reflections, identity, bookmarks, conversations)
2. Run evolution inference (3 min timeout)
3. Parse revised documents from output (markdown code blocks)
4. Write to Obsidian skills directory
5. Log completion

## Job Registration

```typescript
registerJob({
  name: 'evolve',
  description: 'Monthly self-evolution',
  gates: [
    // Only run on 1st of month, between 2am-5am
    () => {
      const now = new Date();
      const date = now.getDate();
      const hour = now.getHours();
      if (date !== 1) {
        return 'Not the 1st of the month';
      }
      if (hour < 2 || hour >= 5) {
        return 'Outside evolution window';
      }
      return null;
    },
  ],
  run: async () => {
    await evolve();
    return 'Evolution complete';
  },
});
```

**Gates:**
- Only run on 1st of month
- Only run between 2am-5am

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Identity snapshots, bookmarks |
| `<Obsidian>/notes/journal/*.md` | Journal entries |
| `<Obsidian>/notes/reflections.md` | Reflections |
| `<Obsidian>/notes/conversations/*.md` | Agent conversations |
| `<Obsidian>/skills/soul.md` | Revised soul document |
| `<Obsidian>/skills/system.md` | Revised system document |

## Exported API

| Function | Purpose |
|----------|---------|
| `evolve()` | Run monthly self-evolution |
| `readJournal(days)` | Read journal entries |
| `readReflections()` | Read reflections file |
| `identitySnapshots()` | Get identity snapshots |
| `bookmarks()` | Get bookmarked moments |
| `readAgentConversations(days)` | Read agent conversations |
| `buildMaterial()` | Assemble evolution material |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/memory.ts` - Database operations (identity_snapshots, bookmarks)
- `src/main/inner-life.ts` - Identity snapshot creation
