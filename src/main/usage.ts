/**
 * Usage and activity tracking across agents.
 * Port of core/usage.py.
 *
 * Queries tool_calls, heartbeats, and usage across all agent databases
 * for the settings modal's Usage and Activity tabs.
 */

import Database from 'better-sqlite3';
import * as fs from 'fs';
import * as path from 'path';
import { BUNDLE_ROOT } from './config';
import { discoverAgents, getAgentDir } from './agent-manager';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UsageSummary {
  agent_name: string;
  display_name: string;
  total_calls: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_tokens: number;
  total_duration_ms: number;
  total_tools: number;
  by_source: { source: string; calls: number; tokens_in: number; tokens_out: number; duration_ms: number }[];
}

export interface ActivityItem {
  agent: string;
  category: 'tool_call' | 'heartbeat' | 'inference';
  timestamp: string;
  action: string;
  detail: string;
  flagged: boolean;
}

// ---------------------------------------------------------------------------
// Per-agent usage summary
// ---------------------------------------------------------------------------
// NOTE: The canonical usage write path is memory.ts:logUsage().
// Inference calls memory.logUsage() directly - this module is read-only.

export function getUsageSummary(dbPath: string, days?: number): Omit<UsageSummary, 'agent_name' | 'display_name'> {
  if (!fs.existsSync(dbPath)) {
    return { total_calls: 0, total_tokens_in: 0, total_tokens_out: 0, total_tokens: 0, total_duration_ms: 0, total_tools: 0, by_source: [] };
  }

  const db = new Database(dbPath, { readonly: true });

  let where = '';
  const params: unknown[] = [];
  if (days) {
    const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
    where = 'WHERE timestamp >= ?';
    params.push(cutoff);
  }

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
    return { total_calls: 0, total_tokens_in: 0, total_tokens_out: 0, total_tokens: 0, total_duration_ms: 0, total_tools: 0, by_source: [] };
  }

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

// ---------------------------------------------------------------------------
// Cross-agent usage
// ---------------------------------------------------------------------------

export function getAllAgentsUsage(days?: number): UsageSummary[] {
  const results: UsageSummary[] = [];
  for (const agent of discoverAgents()) {
    const dbPath = path.join(getAgentDir(agent.name), 'data', 'memory.db');
    if (!fs.existsSync(dbPath)) continue;

    // discoverAgents already resolved the display name from the manifest,
    // but fall back to bundle manifest if the agent is bundle-only.
    let displayName = agent.display_name;
    if (!displayName || displayName === agent.name.charAt(0).toUpperCase() + agent.name.slice(1)) {
      const bundleManifest = path.join(BUNDLE_ROOT, 'agents', agent.name, 'data', 'agent.json');
      try {
        if (fs.existsSync(bundleManifest)) {
          const manifest = JSON.parse(fs.readFileSync(bundleManifest, 'utf-8'));
          if (manifest.display_name) displayName = manifest.display_name;
        }
      } catch { /* use default */ }
    }

    const summary = getUsageSummary(dbPath, days);
    results.push({
      agent_name: agent.name,
      display_name: displayName,
      ...summary,
    });
  }

  return results;
}

// ---------------------------------------------------------------------------
// Daily usage breakdown (for bar charts)
// ---------------------------------------------------------------------------

export interface DailyUsageRow {
  date: string;        // YYYY-MM-DD
  agent_name: string;
  display_name: string;
  tokens_in: number;
  tokens_out: number;
  tokens: number;
  calls: number;
}

export function getDailyUsage(days = 14): DailyUsageRow[] {
  const results: DailyUsageRow[] = [];
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

  for (const agent of discoverAgents()) {
    const dbPath = path.join(getAgentDir(agent.name), 'data', 'memory.db');
    if (!fs.existsSync(dbPath)) continue;

    let displayName = agent.display_name;
    if (!displayName || displayName === agent.name.charAt(0).toUpperCase() + agent.name.slice(1)) {
      const bundleManifest = path.join(BUNDLE_ROOT, 'agents', agent.name, 'data', 'agent.json');
      try {
        if (fs.existsSync(bundleManifest)) {
          const manifest = JSON.parse(fs.readFileSync(bundleManifest, 'utf-8'));
          if (manifest.display_name) displayName = manifest.display_name;
        }
      } catch { /* use default */ }
    }

    let db: Database.Database;
    try {
      db = new Database(dbPath, { readonly: true });
    } catch { continue; }

    try {
      const rows = db.prepare(`
        SELECT date(timestamp) as date,
               COALESCE(SUM(tokens_in), 0) as tokens_in,
               COALESCE(SUM(tokens_out), 0) as tokens_out,
               COUNT(*) as calls
        FROM usage_log
        WHERE timestamp >= ?
        GROUP BY date(timestamp)
        ORDER BY date ASC
      `).all(cutoff) as { date: string; tokens_in: number; tokens_out: number; calls: number }[];
      for (const r of rows) {
        results.push({
          date: r.date,
          agent_name: agent.name,
          display_name: displayName,
          tokens_in: r.tokens_in,
          tokens_out: r.tokens_out,
          tokens: r.tokens_in + r.tokens_out,
          calls: r.calls,
        });
      }
    } catch { /* table may not exist */ }

    db.close();
  }

  return results;
}

// ---------------------------------------------------------------------------
// Cross-agent activity feed
// ---------------------------------------------------------------------------

export function getAllActivity(days = 7, limit = 500): ActivityItem[] {
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
  const allItems: ActivityItem[] = [];

  for (const agent of discoverAgents()) {
    const name = agent.name;
    const dbPath = path.join(getAgentDir(name), 'data', 'memory.db');
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

    // Usage log
    try {
      const rows = db.prepare(
        'SELECT timestamp, source, tokens_in, tokens_out, duration_ms, tool_count FROM usage_log WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?',
      ).all(cutoff, limit) as { timestamp: string; source: string; tokens_in: number; tokens_out: number; duration_ms: number; tool_count: number }[];
      for (const r of rows) {
        const tokIn = r.tokens_in || 0;
        const tokOut = r.tokens_out || 0;
        const dur = r.duration_ms || 0;
        let detail = `~${(tokIn + tokOut).toLocaleString()} tokens (${tokIn.toLocaleString()} in, ${tokOut.toLocaleString()} out)`;
        if (dur) detail += ` | ${(dur / 1000).toFixed(1)}s`;
        if (r.tool_count) detail += ` | ${r.tool_count} tools`;
        allItems.push({
          agent: name,
          category: 'inference',
          timestamp: r.timestamp,
          action: r.source,
          detail,
          flagged: false,
        });
      }
    } catch { /* table may not exist */ }

    db.close();
  }

  allItems.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  return allItems.slice(0, limit);
}

// ---------------------------------------------------------------------------
// Per-agent usage detail (individual entries with conversation context)
// ---------------------------------------------------------------------------

export interface UsageDetailEntry {
  id: number;
  timestamp: string;
  source: string;
  tokens_in: number;
  tokens_out: number;
  duration_ms: number;
  tool_count: number;
  context: { role: string; content: string; timestamp: string }[];
}

export function getAgentUsageDetail(agentName: string, days?: number, limit = 50): UsageDetailEntry[] {
  const dbPath = path.join(getAgentDir(agentName), 'data', 'memory.db');
  if (!fs.existsSync(dbPath)) return [];

  const db = new Database(dbPath, { readonly: true });

  let where = '';
  const params: unknown[] = [];
  if (days) {
    const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
    where = 'WHERE timestamp >= ?';
    params.push(cutoff);
  }

  let rows: { id: number; timestamp: string; source: string; tokens_in: number; tokens_out: number; duration_ms: number; tool_count: number }[];
  try {
    rows = db.prepare(
      `SELECT id, timestamp, source, tokens_in, tokens_out, duration_ms, tool_count
       FROM usage_log ${where} ORDER BY id DESC LIMIT ?`,
    ).all(...params, limit) as typeof rows;
  } catch {
    db.close();
    return [];
  }

  // For each usage entry, find nearby turns (within 60s before and after)
  let turnStmt: Database.Statement | null = null;
  try {
    turnStmt = db.prepare(
      `SELECT role, substr(content, 1, 300) as content, timestamp
       FROM turns
       WHERE timestamp BETWEEN datetime(?, '-60 seconds') AND datetime(?, '+60 seconds')
       ORDER BY timestamp ASC LIMIT 6`,
    );
  } catch { /* turns table may not exist */ }

  const results: UsageDetailEntry[] = [];
  for (const r of rows) {
    let context: UsageDetailEntry['context'] = [];
    if (turnStmt) {
      try {
        context = turnStmt.all(r.timestamp, r.timestamp) as typeof context;
      } catch { /* noop */ }
    }
    results.push({
      id: r.id,
      timestamp: r.timestamp,
      source: r.source,
      tokens_in: r.tokens_in || 0,
      tokens_out: r.tokens_out || 0,
      duration_ms: r.duration_ms || 0,
      tool_count: r.tool_count || 0,
      context,
    });
  }

  db.close();
  return results;
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function formatDuration(ms: number): string {
  if (ms >= 3_600_000) return `${(ms / 3_600_000).toFixed(1)}h`;
  if (ms >= 60_000) return `${Math.round(ms / 60_000)}m`;
  if (ms >= 1_000) return `${Math.round(ms / 1_000)}s`;
  return `${ms}ms`;
}
