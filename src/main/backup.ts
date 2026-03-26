/**
 * Daily agent data backup.
 *
 * Snapshots agent manifests, prompts, and org configs to
 * ~/.atrophy/backups/YYYY-MM-DD/. Keeps the last 7 days.
 * Memory.db is excluded (too large, has its own WAL journal).
 */

import * as fs from 'fs';
import * as path from 'path';
import { USER_DATA } from './config';
import { createLogger } from './logger';

const log = createLogger('backup');

const BACKUP_DIR = path.join(USER_DATA, 'backups');
const MAX_BACKUPS = 7;

/**
 * Run a daily backup if one hasn't been done today.
 * Copies agent manifests, prompts, emotional state, and org configs.
 */
export function backupAgentData(): void {
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
  const todayDir = path.join(BACKUP_DIR, today);

  // Skip if already backed up today
  if (fs.existsSync(todayDir)) {
    log.debug(`Backup already exists for ${today}`);
    return;
  }

  try {
    fs.mkdirSync(todayDir, { recursive: true });

    // Backup agent data (manifests, prompts, emotional state - NOT memory.db)
    const agentsDir = path.join(USER_DATA, 'agents');
    if (fs.existsSync(agentsDir)) {
      const agentBackupDir = path.join(todayDir, 'agents');
      for (const agentName of fs.readdirSync(agentsDir)) {
        const agentSrc = path.join(agentsDir, agentName);
        if (!fs.statSync(agentSrc).isDirectory()) continue;

        const agentDst = path.join(agentBackupDir, agentName);

        // Copy manifest
        const manifestSrc = path.join(agentSrc, 'data', 'agent.json');
        if (fs.existsSync(manifestSrc)) {
          const manifestDst = path.join(agentDst, 'data');
          fs.mkdirSync(manifestDst, { recursive: true });
          fs.copyFileSync(manifestSrc, path.join(manifestDst, 'agent.json'));
        }

        // Copy emotional state
        const emotionSrc = path.join(agentSrc, 'data', '.emotional_state.json');
        if (fs.existsSync(emotionSrc)) {
          const emotionDst = path.join(agentDst, 'data');
          fs.mkdirSync(emotionDst, { recursive: true });
          fs.copyFileSync(emotionSrc, path.join(emotionDst, '.emotional_state.json'));
        }

        // Copy prompts directory
        const promptsSrc = path.join(agentSrc, 'prompts');
        if (fs.existsSync(promptsSrc)) {
          const promptsDst = path.join(agentDst, 'prompts');
          fs.mkdirSync(promptsDst, { recursive: true });
          for (const file of fs.readdirSync(promptsSrc)) {
            if (file.endsWith('.md')) {
              fs.copyFileSync(
                path.join(promptsSrc, file),
                path.join(promptsDst, file),
              );
            }
          }
        }
      }
    }

    // Backup org configs
    const orgsDir = path.join(USER_DATA, 'orgs');
    if (fs.existsSync(orgsDir)) {
      const orgBackupDir = path.join(todayDir, 'orgs');
      for (const orgSlug of fs.readdirSync(orgsDir)) {
        const orgSrc = path.join(orgsDir, orgSlug);
        if (!fs.statSync(orgSrc).isDirectory()) continue;

        const orgDst = path.join(orgBackupDir, orgSlug);
        fs.mkdirSync(orgDst, { recursive: true });

        const manifestSrc = path.join(orgSrc, 'org.json');
        if (fs.existsSync(manifestSrc)) {
          fs.copyFileSync(manifestSrc, path.join(orgDst, 'org.json'));
        }
      }
    }

    // Backup global config
    const configSrc = path.join(USER_DATA, 'config.json');
    if (fs.existsSync(configSrc)) {
      fs.copyFileSync(configSrc, path.join(todayDir, 'config.json'));
    }

    // Backup agent states
    const statesSrc = path.join(USER_DATA, 'agent_states.json');
    if (fs.existsSync(statesSrc)) {
      fs.copyFileSync(statesSrc, path.join(todayDir, 'agent_states.json'));
    }

    log.info(`Daily backup created: ${todayDir}`);

    // Prune old backups
    pruneBackups();
  } catch (e) {
    log.error(`Backup failed: ${e}`);
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
