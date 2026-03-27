/**
 * Daily agent data backup.
 *
 * Snapshots agent manifests, prompts, emotional state, memory.db,
 * and org configs to ~/.atrophy/backups/YYYY-MM-DD/. Keeps the last 7 days.
 * Handles org-nested directory structure (agents/<org>/<name>/).
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
import { USER_DATA } from './config';
import { createLogger } from './logger';

const log = createLogger('backup');

const BACKUP_DIR = path.join(USER_DATA, 'backups');
const MAX_BACKUPS = 7;

/**
 * Run a daily backup if one hasn't been done today.
 */
export function backupAgentData(): void {
  const today = new Date().toISOString().slice(0, 10);
  const todayDir = path.join(BACKUP_DIR, today);

  if (fs.existsSync(todayDir)) {
    log.debug(`Backup already exists for ${today}`);
    return;
  }

  try {
    fs.mkdirSync(todayDir, { recursive: true });

    // Backup agents (handles flat and org-nested dirs)
    const agentsDir = path.join(USER_DATA, 'agents');
    if (fs.existsSync(agentsDir)) {
      backupAgentsInDir(agentsDir, path.join(todayDir, 'agents'));
    }

    // Backup org configs
    const orgsDir = path.join(USER_DATA, 'orgs');
    if (fs.existsSync(orgsDir)) {
      for (const orgSlug of fs.readdirSync(orgsDir)) {
        const orgSrc = path.join(orgsDir, orgSlug);
        if (!fs.statSync(orgSrc).isDirectory()) continue;
        const orgDst = path.join(todayDir, 'orgs', orgSlug);
        fs.mkdirSync(orgDst, { recursive: true });
        const manifestSrc = path.join(orgSrc, 'org.json');
        if (fs.existsSync(manifestSrc)) {
          fs.copyFileSync(manifestSrc, path.join(orgDst, 'org.json'));
        }
      }
    }

    // Backup global config and agent states
    for (const file of ['config.json', 'agent_states.json']) {
      const src = path.join(USER_DATA, file);
      if (fs.existsSync(src)) fs.copyFileSync(src, path.join(todayDir, file));
    }

    log.info(`Daily backup created: ${todayDir}`);
    pruneBackups();
  } catch (e) {
    log.error(`Backup failed: ${e}`);
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Recursively backup agents. If an entry has data/, it's an agent.
 * Otherwise it's an org directory - recurse into it.
 */
function backupAgentsInDir(srcDir: string, dstDir: string): void {
  for (const entry of fs.readdirSync(srcDir)) {
    const entrySrc = path.join(srcDir, entry);
    try {
      if (!fs.statSync(entrySrc).isDirectory()) continue;
    } catch { continue; }

    if (fs.existsSync(path.join(entrySrc, 'data'))) {
      backupSingleAgent(entrySrc, path.join(dstDir, entry));
    } else {
      backupAgentsInDir(entrySrc, path.join(dstDir, entry));
    }
  }
}

function backupSingleAgent(agentSrc: string, agentDst: string): void {
  const dataDst = path.join(agentDst, 'data');

  // Manifest
  const manifestSrc = path.join(agentSrc, 'data', 'agent.json');
  if (fs.existsSync(manifestSrc)) {
    fs.mkdirSync(dataDst, { recursive: true });
    fs.copyFileSync(manifestSrc, path.join(dataDst, 'agent.json'));
  }

  // Emotional state
  const emotionSrc = path.join(agentSrc, 'data', '.emotional_state.json');
  if (fs.existsSync(emotionSrc)) {
    fs.mkdirSync(dataDst, { recursive: true });
    fs.copyFileSync(emotionSrc, path.join(dataDst, '.emotional_state.json'));
  }

  // Memory database (safe backup via VACUUM INTO - creates a clean copy
  // without holding locks or interfering with active connections)
  const dbSrc = path.join(agentSrc, 'data', 'memory.db');
  if (fs.existsSync(dbSrc)) {
    fs.mkdirSync(dataDst, { recursive: true });
    const dbDst = path.join(dataDst, 'memory.db');
    try {
      const db = new Database(dbSrc, { readonly: true });
      db.pragma('journal_mode = WAL');
      // Validate destination is within the backup directory (defense against SQL injection via path)
      const resolvedDst = path.resolve(dbDst);
      if (!resolvedDst.startsWith(path.resolve(BACKUP_DIR) + path.sep)) {
        throw new Error(`backup path outside BACKUP_DIR: ${resolvedDst}`);
      }
      db.exec(`VACUUM INTO '${resolvedDst.replace(/'/g, "''")}'`);
      db.close();
    } catch (e) {
      log.debug(`memory.db backup skipped for ${path.basename(agentSrc)}: ${e}`);
    }
  }

  // Prompts
  const promptsSrc = path.join(agentSrc, 'prompts');
  if (fs.existsSync(promptsSrc)) {
    const promptsDst = path.join(agentDst, 'prompts');
    fs.mkdirSync(promptsDst, { recursive: true });
    for (const file of fs.readdirSync(promptsSrc)) {
      if (file.endsWith('.md')) {
        fs.copyFileSync(path.join(promptsSrc, file), path.join(promptsDst, file));
      }
    }
  }
}

function pruneBackups(): void {
  try {
    if (!fs.existsSync(BACKUP_DIR)) return;
    const entries = fs.readdirSync(BACKUP_DIR)
      .filter(e => /^\d{4}-\d{2}-\d{2}$/.test(e))
      .sort()
      .reverse();
    for (let i = MAX_BACKUPS; i < entries.length; i++) {
      const old = path.join(BACKUP_DIR, entries[i]);
      fs.rmSync(old, { recursive: true, force: true });
      log.info(`Pruned old backup: ${entries[i]}`);
    }
  } catch (e) {
    log.debug(`Prune failed: ${e}`);
  }
}
