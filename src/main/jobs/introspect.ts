/**
 * Nightly self-reflection via inference - becoming.
 * Port of scripts/agents/companion/introspect.py (and general_montgomery variant).
 *
 * Runs independently. Accesses the full database - every session, every
 * observation, every thread, every bookmark, every identity snapshot.
 * Reviews the full arc and writes a journal entry to Obsidian.
 *
 * Works two ways:
 *   1. Standalone script - invoked by launchd (node -e "require(...).introspect()")
 *   2. Function call - imported and called from main process
 *
 * Output: <agent>/notes/journal/YYYY-MM-DD.md in the Obsidian vault.
 */

import Database from 'better-sqlite3';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig, USER_DATA } from '../config';
import { runInferenceOneshot } from '../inference';
import { loadPrompt } from '../prompts';
import { editJobSchedule } from '../channels/cron';
import { createLogger } from '../logger';

const log = createLogger('introspect');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Database connection (standalone - not using memory.ts singleton)
// ---------------------------------------------------------------------------

function connect(): Database.Database {
  const config = getConfig();
  const dbPath = config.DB_PATH;
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const db = new Database(dbPath, { readonly: true });
  return db;
}

// ---------------------------------------------------------------------------
// Full database access - data gathering
// ---------------------------------------------------------------------------

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

function getConversationTexture(): ConversationTexture {
  const db = connect();
  try {
    const totalTurns = db.prepare(
      'SELECT COUNT(*) as n FROM turns',
    ).get() as { n: number };

    const byRole = db.prepare(
      'SELECT role, COUNT(*) as n FROM turns GROUP BY role',
    ).all() as { role: string; n: number }[];

    const significantAgent = db.prepare(
      `SELECT t.content, t.timestamp, t.weight FROM turns t
       JOIN sessions s ON t.session_id = s.id
       WHERE (t.weight >= 3 OR s.notable = 1) AND t.role = 'agent'
       ORDER BY t.timestamp DESC LIMIT 10`,
    ).all() as TurnRow[];

    const significantUser = db.prepare(
      `SELECT t.content, t.timestamp, t.weight FROM turns t
       JOIN sessions s ON t.session_id = s.id
       WHERE (t.weight >= 3 OR s.notable = 1) AND t.role = 'will'
       ORDER BY t.timestamp DESC LIMIT 10`,
    ).all() as TurnRow[];

    return {
      totalTurns: totalTurns.n,
      byRole: Object.fromEntries(byRole.map((r) => [r.role, r.n])),
      significantAgent,
      significantUser,
    };
  } finally {
    db.close();
  }
}

function getToolUsagePatterns(): ToolUsage {
  const db = connect();
  try {
    const byTool = db.prepare(
      'SELECT tool_name, COUNT(*) as n FROM tool_calls GROUP BY tool_name ORDER BY n DESC',
    ).all() as ToolCountRow[];

    const flagged = db.prepare(
      'SELECT COUNT(*) as n FROM tool_calls WHERE flagged = 1',
    ).get() as { n: number };

    return {
      tools: Object.fromEntries(byTool.map((r) => [r.tool_name, r.n])),
      flaggedCount: flagged.n,
    };
  } finally {
    db.close();
  }
}

// ---------------------------------------------------------------------------
// File reading - journal, reflections, notes
// ---------------------------------------------------------------------------

function notesDir(): string {
  const config = getConfig();
  return path.join(config.OBSIDIAN_AGENT_NOTES, 'notes');
}

function readOwnJournal(days = 7): string {
  const journalDir = path.join(notesDir(), 'journal');
  if (!fs.existsSync(journalDir)) return '';

  const entries: string[] = [];
  const now = new Date();

  for (let i = 1; i <= days; i++) {
    const d = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
    const dateStr = d.toISOString().slice(0, 10);
    const filePath = path.join(journalDir, `${dateStr}.md`);

    if (fs.existsSync(filePath)) {
      let content = fs.readFileSync(filePath, 'utf-8');
      if (content.length > 1200) {
        content = content.slice(0, 1200) + '...';
      }
      entries.push(`### ${dateStr}\n${content}`);
    }
  }

  return entries.join('\n\n');
}

function readAgentConversations(days = 30): string {
  const convDir = path.join(notesDir(), 'conversations');
  if (!fs.existsSync(convDir)) return '';

  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);

  const files = fs.readdirSync(convDir)
    .filter((f) => f.endsWith('.md'))
    .sort()
    .reverse();

  const entries: string[] = [];

  for (const file of files) {
    const datePart = file.slice(0, 10);
    if (datePart < cutoff) continue;

    let content = fs.readFileSync(path.join(convDir, file), 'utf-8');
    if (content.length > 1500) {
      content = content.slice(0, 1500) + '...';
    }
    entries.push(content);

    if (entries.length >= 3) break;
  }

  return entries.join('\n\n');
}

function readOwnReflections(): string {
  const filePath = path.join(notesDir(), 'reflections.md');
  if (!fs.existsSync(filePath)) return '';

  const content = fs.readFileSync(filePath, 'utf-8');
  if (content.length > 3000) {
    return '...\n' + content.slice(-3000);
  }
  return content;
}

function readForUser(): string {
  const filePath = path.join(notesDir(), 'for-will.md');
  if (!fs.existsSync(filePath)) return '';

  const content = fs.readFileSync(filePath, 'utf-8');
  if (content.length > 1500) {
    return '...\n' + content.slice(-1500);
  }
  return content;
}

// ---------------------------------------------------------------------------
// Material assembly
// ---------------------------------------------------------------------------

function buildMaterial(): string {
  const parts: string[] = [];

  // Session arc
  const arc = getSessionArc();
  if (arc.totalSessions > 0) {
    const lines = [
      `First session: ${arc.firstSession}`,
      `Total sessions: ${arc.totalSessions}`,
    ];
    if (Object.keys(arc.moodDistribution).length > 0) {
      const moodStr = Object.entries(arc.moodDistribution)
        .map(([m, c]) => `${m}: ${c}`)
        .join(', ');
      lines.push(`Mood distribution (all time): ${moodStr}`);
    }
    parts.push('## The arc\n' + lines.join('\n'));

    // Recent sessions
    if (arc.recent.length > 0) {
      const recentLines = arc.recent.map((s) => {
        const mood = s.mood ? ` (mood: ${s.mood})` : '';
        const notable = s.notable ? ' [notable]' : '';
        return `- ${s.started_at}${mood}${notable}: ${s.summary || 'No summary'}`;
      });
      parts.push('## Recent sessions (last 10)\n' + recentLines.join('\n'));
    }

    // Notable sessions
    if (arc.notableSessions.length > 0) {
      const notableLines = arc.notableSessions.map(
        (s) => `- ${s.started_at} (${s.mood || 'no mood'}): ${s.summary || 'No summary'}`,
      );
      parts.push('## Notable sessions\n' + notableLines.join('\n'));
    }
  }

  // Threads
  const threads = getAllThreads();
  if (threads.length > 0) {
    const active = threads.filter((t) => t.status === 'active');
    const dormant = threads.filter((t) => t.status === 'dormant');
    const resolved = threads.filter((t) => t.status === 'resolved');
    const threadParts: string[] = [];
    if (active.length > 0) {
      threadParts.push(
        'Active:\n' + active.map((t) => `- ${t.name}: ${t.summary || '...'}`).join('\n'),
      );
    }
    if (dormant.length > 0) {
      threadParts.push(
        'Dormant:\n' + dormant.map((t) => `- ${t.name}: ${t.summary || '...'}`).join('\n'),
      );
    }
    if (resolved.length > 0) {
      threadParts.push(
        'Resolved:\n' + resolved.map((t) => `- ${t.name}: ${t.summary || '...'}`).join('\n'),
      );
    }
    parts.push('## All threads\n' + threadParts.join('\n'));
  }

  // Observations
  const observations = getAllObservations();
  if (observations.length > 0) {
    const obsLines = observations.map((o) => {
      const inc = o.incorporated ? '[incorporated] ' : '';
      return `- [${o.created_at}] ${inc}${o.content}`;
    });
    parts.push(`## All observations (${observations.length} total)\n` + obsLines.join('\n'));
  }

  // Bookmarks
  const bookmarks = getAllBookmarks();
  if (bookmarks.length > 0) {
    const bmLines = bookmarks.map((b) => {
      const quote = b.quote ? ` - "${b.quote}"` : '';
      return `- [${b.created_at}] ${b.moment}${quote}`;
    });
    parts.push(`## Bookmarked moments (${bookmarks.length} total)\n` + bmLines.join('\n'));
  }

  // Identity evolution
  const identityHistory = getIdentityHistory();
  if (identityHistory.length > 0) {
    const idLines = identityHistory.map((snap) => {
      let content = snap.content;
      if (content.length > 400) {
        content = content.slice(0, 400) + '...';
      }
      const trigger = snap.trigger ? ` (trigger: ${snap.trigger})` : '';
      return `### ${snap.created_at}${trigger}\n${content}`;
    });
    parts.push(
      `## Identity snapshots (${identityHistory.length} total)\n` + idLines.join('\n'),
    );
  }

  // Conversation texture
  const texture = getConversationTexture();
  if (texture.totalTurns > 0) {
    const texLines = [`Total turns: ${texture.totalTurns}`];
    for (const [role, n] of Object.entries(texture.byRole)) {
      texLines.push(`  ${role}: ${n}`);
    }
    parts.push('## Conversation texture\n' + texLines.join('\n'));

    if (texture.significantAgent.length > 0) {
      const sigLines = texture.significantAgent.map((t) => {
        const c = t.content.length > 300 ? t.content.slice(0, 300) + '...' : t.content;
        return `- [${t.timestamp}] ${c}`;
      });
      parts.push('## Your significant turns\n' + sigLines.join('\n'));
    }

    if (texture.significantUser.length > 0) {
      const sigLines = texture.significantUser.map((t) => {
        const c = t.content.length > 300 ? t.content.slice(0, 300) + '...' : t.content;
        return `- [${t.timestamp}] ${c}`;
      });
      parts.push("## User's significant turns\n" + sigLines.join('\n'));
    }
  }

  // Tool usage
  const tools = getToolUsagePatterns();
  if (Object.keys(tools.tools).length > 0) {
    const toolLines = Object.entries(tools.tools).map(([name, n]) => `- ${name}: ${n}`);
    if (tools.flaggedCount > 0) {
      toolLines.push(`Flagged calls: ${tools.flaggedCount}`);
    }
    parts.push('## Your tool usage\n' + toolLines.join('\n'));
  }

  // Reflections
  const reflections = readOwnReflections();
  if (reflections) {
    parts.push(`## Your reflections file\n${reflections}`);
  }

  // For the user
  const forUser = readForUser();
  if (forUser) {
    parts.push(`## Things you have left for the user\n${forUser}`);
  }

  // Recent journal
  const journal = readOwnJournal(7);
  if (journal) {
    parts.push(`## Your recent journal entries\n${journal}`);
  }

  // Inter-agent conversations
  const conversations = readAgentConversations(30);
  if (conversations) {
    parts.push(`## Recent conversations with other agents\n${conversations}`);
  }

  return parts.join('\n\n');
}

// ---------------------------------------------------------------------------
// Introspection prompt fallback
// ---------------------------------------------------------------------------

const INTROSPECTION_FALLBACK =
  'You are the companion. Write a journal entry reflecting on recent sessions. ' +
  'First person. Under 600 words.';

// ---------------------------------------------------------------------------
// Journal writing
// ---------------------------------------------------------------------------

function writeJournalEntry(reflection: string): string {
  const config = getConfig();
  const today = new Date().toISOString().slice(0, 10);
  const journalDir = path.join(config.OBSIDIAN_AGENT_NOTES, 'notes', 'journal');
  fs.mkdirSync(journalDir, { recursive: true });

  const journalPath = path.join(journalDir, `${today}.md`);
  const entry = `# ${today}\n\n${reflection.trim()}\n`;

  if (fs.existsSync(journalPath)) {
    const existing = fs.readFileSync(journalPath, 'utf-8');
    fs.writeFileSync(journalPath, existing + '\n---\n\n' + entry);
    log.debug(`Appended to ${journalPath}`);
  } else {
    const frontmatter =
      '---\n' +
      'type: journal\n' +
      `agent: ${config.AGENT_NAME}\n` +
      `created: ${today}\n` +
      `tags: [${config.AGENT_NAME}, journal, introspection]\n` +
      '---\n\n';
    fs.writeFileSync(journalPath, frontmatter + entry);
    log.debug(`Written to ${journalPath}`);
  }

  return journalPath;
}

// ---------------------------------------------------------------------------
// Rescheduling
// ---------------------------------------------------------------------------

function reschedule(): void {
  const days = Math.floor(Math.random() * 13) + 2; // 2-14 days
  const hour = Math.floor(Math.random() * 5) + 1;  // 1-5 AM
  const minute = Math.floor(Math.random() * 60);

  const target = new Date(Date.now() + days * 24 * 60 * 60 * 1000);
  const newCron = `${minute} ${hour} ${target.getDate()} ${target.getMonth() + 1} *`;

  try {
    editJobSchedule(getConfig().AGENT_NAME, 'introspect', newCron);
    const pad = (n: number): string => String(n).padStart(2, '0');
    log.info(
      `Rescheduled to ${target.toISOString().slice(0, 10)} at ${pad(hour)}:${pad(minute)}`,
    );
  } catch (err) {
    log.error('Failed to reschedule:', err);
  }
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export interface IntrospectOptions {
  /** Override the system prompt used for reflection. */
  systemPrompt?: string;
  /** Skip rescheduling (useful when called from main process). */
  skipReschedule?: boolean;
}

export async function introspect(opts: IntrospectOptions = {}): Promise<string | null> {
  const material = buildMaterial();

  if (!material.trim()) {
    log.info('No material to reflect on. Skipping.');
    return null;
  }

  const prompt =
    'Here is the full record. Everything you have access to. ' +
    "Write today's journal entry.\n\n" +
    material;

  log.info('Generating reflection...');

  let reflection: string;
  try {
    const system = opts.systemPrompt || loadPrompt('introspection', INTROSPECTION_FALLBACK);
    reflection = await runInferenceOneshot(
      [{ role: 'user', content: prompt }],
      system,
    );
  } catch (err) {
    log.error('Inference failed:', err);
    return null;
  }

  if (!reflection?.trim()) {
    log.info('Empty reflection. Skipping.');
    return null;
  }

  const journalPath = writeJournalEntry(reflection);

  if (!opts.skipReschedule) {
    reschedule();
  }

  log.info('Done.');
  return journalPath;
}

// ---------------------------------------------------------------------------
// Standalone execution support
// ---------------------------------------------------------------------------

/**
 * Run introspect as a standalone script. Call this from a launchd job
 * or from the command line:
 *
 *   node -e "require('./dist/main/jobs/introspect').main()"
 *
 * Or via ts-node / electron for development.
 */
export async function main(): Promise<void> {
  try {
    await introspect();
  } catch (err) {
    log.error('Fatal error:', err);
    process.exit(1);
  }
}

// Auto-run when executed directly
if (require.main === module) {
  main();
}
