# src/main/usage.ts - Usage and Activity Tracking

**Dependencies:** `better-sqlite3`, `fs`, `path`, `./config`  
**Purpose:** Query usage and activity across all agent databases for Settings modal

## Overview

This module queries `tool_calls`, `heartbeats`, and `usage_log` tables across all agent databases to populate the Settings modal's Usage and Activity tabs. It's read-only - the canonical usage write path is `memory.ts:logUsage()`.

## Types

### UsageSummary

```typescript
export interface UsageSummary {
  agent_name: string;
  display_name: string;
  total_calls: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_tokens: number;
  total_duration_ms: number;
  total_tools: number;
  by_source: {
    source: string;
    calls: number;
    tokens_in: number;
    tokens_out: number;
    duration_ms: number;
  }[];
}
```

**Purpose:** Aggregated usage statistics per agent

### ActivityItem

```typescript
export interface ActivityItem {
  agent: string;
  category: 'tool_call' | 'heartbeat' | 'inference';
  timestamp: string;
  action: string;
  detail: string;
  flagged: boolean;
}
```

**Purpose:** Individual activity feed entries

## getUsageSummary

```typescript
export function getUsageSummary(
  dbPath: string,
  days?: number,
): Omit<UsageSummary, 'agent_name' | 'display_name'> {
  if (!fs.existsSync(dbPath)) {
    return { total_calls: 0, total_tokens_in: 0, /* ... */ };
  }

  const db = new Database(dbPath, { readonly: true });

  let where = '';
  const params: unknown[] = [];
  if (days) {
    const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
    where = 'WHERE timestamp >= ?';
    params.push(cutoff);
  }

  // Get totals
  let row: Record<string, number>;
  try {
    row = db.prepare(`
      SELECT
        COUNT(*) as total_calls,
        COALESCE(SUM(tokens_in), 0) as total_tokens_in,
        COALESCE(SUM(tokens_out), 0) as total_tokens_out,
        COALESCE(SUM(duration_ms), 0) as total_duration_ms,
        COALESCE(SUM(tool_count), 0) as total_tools
      FROM usage_log ${where}
    `).get(...params) as Record<string, number>;
  } catch {
    db.close();
    return { /* zeros */ };
  }

  // Get breakdown by source
  let sources: { source: string; calls: number; tokens_in: number; tokens_out: number; duration_ms: number }[] = [];
  try {
    sources = db.prepare(`
      SELECT source, COUNT(*) as calls,
             COALESCE(SUM(tokens_in), 0) as tokens_in,
             COALESCE(SUM(tokens_out), 0) as tokens_out,
             COALESCE(SUM(duration_ms), 0) as duration_ms
      FROM usage_log ${where}
      GROUP BY source ORDER BY calls DESC
    `).all(...params) as typeof sources;
  } catch { /* noop */ }

  db.close();

  return {
    total_calls: row.total_calls || 0,
    total_tokens_in: row.total_tokens_in || 0,
    total_tokens_out: row.total_tokens_out || 0,
    total_tokens: (row.total_tokens_in || 0) + (row.total_tokens_out || 0),
    total_duration_ms: row.total_duration_ms || 0,
    total_tools: row.total_tools || 0,
    by_source: sources,
  };
}
```

**Purpose:** Get usage summary for a single agent database

**Parameters:**
- `dbPath`: Path to agent's memory.db
- `days`: Optional filter for recent usage only

**Read-only:** Opens database with `{ readonly: true }`

## getAllAgentsUsage

```typescript
export function getAllAgentsUsage(days?: number): UsageSummary[] {
  const agentsDir = path.join(USER_DATA, 'agents');
  if (!fs.existsSync(agentsDir)) return [];

  const results: UsageSummary[] = [];
  for (const name of fs.readdirSync(agentsDir).sort()) {
    const dbPath = path.join(agentsDir, name, 'data', 'memory.db');
    if (!fs.existsSync(dbPath)) continue;

    // Load display name (check user data then bundle)
    let displayName = name.charAt(0).toUpperCase() + name.slice(1);
    const manifestPaths = [
      path.join(agentsDir, name, 'data', 'agent.json'),
      path.join(BUNDLE_ROOT, 'agents', name, 'data', 'agent.json'),
    ];
    for (const mp of manifestPaths) {
      try {
        if (fs.existsSync(mp)) {
          const manifest = JSON.parse(fs.readFileSync(mp, 'utf-8'));
          if (manifest.display_name) {
            displayName = manifest.display_name;
            break;
          }
        }
      } catch { /* use default */ }
    }

    const summary = getUsageSummary(dbPath, days);
    results.push({
      agent_name: name,
      display_name: displayName,
      ...summary,
    });
  }

  return results;
}
```

**Purpose:** Get usage summary for all agents

**Returns:** Array of UsageSummary, sorted by agent name

## getAllActivity

```typescript
export function getAllActivity(days = 7, limit = 500): ActivityItem[] {
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
  const allItems: ActivityItem[] = [];

  const agentsDir = path.join(USER_DATA, 'agents');
  if (!fs.existsSync(agentsDir)) return [];

  for (const name of fs.readdirSync(agentsDir)) {
    const dbPath = path.join(agentsDir, name, 'data', 'memory.db');
    if (!fs.existsSync(dbPath)) continue;

    let db: Database.Database;
    try {
      db = new Database(dbPath, { readonly: true });
    } catch {
      continue;
    }

    // Tool calls
    try {
      const rows = db.prepare(
        'SELECT timestamp, tool_name, input_json, flagged FROM tool_calls WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?',
      ).all(cutoff, limit) as { timestamp: string; tool_name: string; input_json: string | null; flagged: number }[];
      for (const r of rows) {
        allItems.push({
          agent: name,
          category: 'tool_call',
          timestamp: r.timestamp,
          action: r.tool_name,
          detail: r.input_json || '',
          flagged: !!r.flagged,
        });
      }
    } catch { /* table may not exist */ }

    // Heartbeats
    try {
      const rows = db.prepare(
        'SELECT timestamp, decision, reason, message FROM heartbeats WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?',
      ).all(cutoff, limit) as { timestamp: string; decision: string; reason: string | null; message: string | null }[];
      for (const r of rows) {
        let detail = r.reason || '';
        if (r.message) detail += `\n${r.message}`;
        allItems.push({
          agent: name,
          category: 'heartbeat',
          timestamp: r.timestamp,
          action: r.decision,
          detail: detail.trim(),
          flagged: false,
        });
      }
    } catch { /* table may not exist */ }

    // Usage log (inference calls)
    try {
      const rows = db.prepare(/* ... */).all(/* ... */);
      for (const r of rows) {
        allItems.push({
          agent: name,
          category: 'inference',
          timestamp: r.timestamp,
          action: r.source,
          detail: `${r.tokens_in + r.tokens_out} tokens, ${r.duration_ms}ms`,
          flagged: false,
        });
      }
    } catch { /* table may not exist */ }

    db.close();
  }

  // Sort by timestamp descending and limit
  allItems.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  return allItems.slice(0, limit);
}
```

**Purpose:** Get activity feed across all agents

**Activity categories:**
1. **tool_call:** MCP tool invocations from `tool_calls` table
2. **heartbeat:** Autonomous check-ins from `heartbeats` table
3. **inference:** Inference calls from `usage_log` table

**Default filters:**
- `days = 7`: Last 7 days
- `limit = 500`: Max 500 items

**Sorting:** By timestamp descending (newest first)

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/agents/<name>/data/memory.db` | All queries |
| Read | `~/.atrophy/agents/<name>/data/agent.json` | Display name lookup |
| Read | `<bundle>/agents/<name>/data/agent.json` | Display name fallback |

## Exported API

| Function | Purpose |
|----------|---------|
| `getUsageSummary(dbPath, days)` | Get usage for single agent |
| `getAllAgentsUsage(days)` | Get usage for all agents |
| `getAllActivity(days, limit)` | Get activity feed |
| `UsageSummary` | Usage summary interface |
| `ActivityItem` | Activity feed item interface |

## See Also

- `src/main/memory.ts` - logUsage() write path
- `src/main/ipc/system.ts` - usage:all, activity:all IPC handlers
- `src/renderer/components/Settings.svelte` - Usage/Activity tabs
