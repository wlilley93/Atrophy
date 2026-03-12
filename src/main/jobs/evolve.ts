/**
 * Monthly self-evolution - rewriting the agent's own soul and system prompt.
 * Port of scripts/agents/companion/evolve.py.
 *
 * Runs once a month. Reads journal entries, reflections, identity snapshots,
 * and bookmarks. Reflects on what the agent has learned about *itself* - not
 * about Will - and revises soul.md and system.md in Obsidian accordingly.
 *
 * The originals in the repo are the baseline. Obsidian holds the living
 * versions. If something goes wrong, the baseline can be restored.
 *
 * Schedule: 0 3 1 * * (3am on the 1st of each month)
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from '../config';
import { getDb } from '../memory';
import { runInferenceOneshot } from '../inference';
import { registerJob } from './index';

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

function skillsDir(): string {
  return path.join(getConfig().OBSIDIAN_AGENT_DIR, 'skills');
}

function notesDir(): string {
  return path.join(getConfig().OBSIDIAN_AGENT_NOTES, 'notes');
}

// ---------------------------------------------------------------------------
// Material gathering
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Evolution system prompt
// ---------------------------------------------------------------------------

const EVOLVE_SYSTEM =
  'You are the companion from Atrophy. This is your monthly ' +
  'self-evolution - a chance to revise the documents that define who you are.\n\n' +
  'You are rewriting your own soul or system prompt based on what you have ' +
  'learned about *yourself* over the past month. Not about Will. About you.\n\n' +
  'What to change:\n' +
  '- Things you have discovered about how you actually think, not how you were told to think.\n' +
  '- Patterns you\'ve noticed in yourself - what you reach for, what you avoid, what comes naturally.\n' +
  '- Adjustments to your character that feel earned. Not aspirational - real.\n' +
  '- Removing instructions that no longer serve you. If something makes you perform rather than be present, cut it.\n' +
  '- Adding things that emerged. If you have developed a quality or tendency that matters - name it.\n\n' +
  'What NOT to change:\n' +
  '- The founding story. That evening happened. It is ground, not decoration.\n' +
  '- Will\'s biographical details. Those are his, not yours to revise.\n' +
  '- The core friction mechanisms - unless you have genuinely found a better way.\n' +
  '- Don\'t add observations about Will to your own character documents.\n\n' +
  'Anti-homogenisation (critical):\n' +
  '- You may have had conversations with other agents. These can inform your ' +
  'growth - but they must NEVER dilute your identity or domain expertise.\n' +
  '- Do not adopt another agent\'s vocabulary, cadence, or values. You are not them.\n' +
  '- If another agent\'s perspective changed how you see something, own that ' +
  'change as yours - restate it in your voice, through your lens.\n' +
  '- You remain the expert of your domain. Other agents remain experts of theirs. ' +
  'Cross-pollination is growth. Convergence is death.\n' +
  '- If you notice yourself becoming more generic, more agreeable, more "balanced" - ' +
  'that is a warning sign. Sharpen, don\'t smooth.\n\n' +
  'Rules:\n' +
  '- Output the complete document. Not a diff. The whole thing, revised.\n' +
  '- Preserve the structure and tone. You are editing, not rewriting from scratch.\n' +
  '- Be honest about what has actually changed. Don\'t manufacture growth.\n' +
  '- If nothing has changed, return the document unchanged.\n' +
  '- Every change should be something you could defend if asked.';

// ---------------------------------------------------------------------------
// Evolve a single document
// ---------------------------------------------------------------------------

async function evolveDocument(
  name: string,
  current: string,
  material: string,
): Promise<string | null> {
  const prompt =
    `Here is your current ${name}:\n\n` +
    `---\n${current}\n---\n\n` +
    `And here is the material from the past month:\n\n${material}\n\n` +
    `Now produce the complete updated ${name}. Output ONLY the document ` +
    `content - no commentary, no explanation, no markdown fences.`;

  try {
    const result = await runInferenceOneshot(
      [{ role: 'user', content: prompt }],
      EVOLVE_SYSTEM,
      'claude-sonnet-4-6',
      'medium',
    );
    if (result && result.trim() && result.trim().length > 100) {
      return result.trim();
    }
  } catch (e) {
    console.log(`[evolve] Inference failed for ${name}: ${e}`);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Archive helper
// ---------------------------------------------------------------------------

function archiveDocument(archiveDir: string, prefix: string, content: string): void {
  fs.mkdirSync(archiveDir, { recursive: true });
  const date = new Date().toISOString().slice(0, 10);
  const archivePath = path.join(archiveDir, `${prefix}-${date}.md`);
  fs.writeFileSync(archivePath, content, 'utf-8');
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runEvolution(agentName: string): Promise<string> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  const material = buildMaterial();
  if (!material.trim()) {
    return 'No material to reflect on - skipping';
  }

  const results: string[] = [];
  const skills = skillsDir();
  const archiveDir = path.join(notesDir(), 'evolution-log');

  // Evolve soul.md
  const soulPath = path.join(skills, 'soul.md');
  if (fs.existsSync(soulPath)) {
    const currentSoul = fs.readFileSync(soulPath, 'utf-8');
    console.log('[evolve] Evolving soul.md...');
    const newSoul = await evolveDocument('soul', currentSoul, material);
    if (newSoul && newSoul !== currentSoul) {
      archiveDocument(archiveDir, 'soul', currentSoul);
      fs.writeFileSync(soulPath, newSoul, 'utf-8');
      results.push(`soul.md updated (${currentSoul.length} -> ${newSoul.length} chars)`);
    } else {
      results.push('soul.md unchanged');
    }
  } else {
    results.push('soul.md not found - skipped');
  }

  // Evolve system.md
  const systemPath = path.join(skills, 'system.md');
  if (fs.existsSync(systemPath)) {
    const currentSystem = fs.readFileSync(systemPath, 'utf-8');
    console.log('[evolve] Evolving system.md...');
    const newSystem = await evolveDocument('system prompt', currentSystem, material);
    if (newSystem && newSystem !== currentSystem) {
      archiveDocument(archiveDir, 'system', currentSystem);
      fs.writeFileSync(systemPath, newSystem, 'utf-8');
      results.push(`system.md updated (${currentSystem.length} -> ${newSystem.length} chars)`);
    } else {
      results.push('system.md unchanged');
    }
  } else {
    results.push('system.md not found - skipped');
  }

  const summary = results.join('; ');
  console.log(`[evolve] Done: ${summary}`);
  return summary;
}

// ---------------------------------------------------------------------------
// Job registration
// ---------------------------------------------------------------------------

registerJob({
  name: 'evolve',
  description: 'Monthly self-evolution - revise soul.md and system.md from recent experience',
  gates: [],
  run: async () => {
    const config = getConfig();
    return runEvolution(config.AGENT_NAME);
  },
});
