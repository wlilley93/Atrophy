/**
 * Migrate legacy .env format to config.json.
 * Port of scripts/migrate_env.py.
 *
 * Reads ~/.atrophy/.env, parses key=value pairs, identifies secrets vs settings,
 * and writes non-secret settings into ~/.atrophy/config.json. Secrets stay in .env.
 *
 * Safe to run multiple times - only migrates keys not already in config.json.
 */

import * as fs from 'fs';
import * as path from 'path';
import { USER_DATA } from './config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MigrationResult {
  /** Keys successfully moved to config.json */
  migrated: string[];
  /** Keys skipped because they already exist in config.json */
  skipped: string[];
  /** Secret keys left in .env */
  secretsKept: string[];
  /** True if config.json was written */
  configWritten: boolean;
  /** True if .env was rewritten */
  envRewritten: boolean;
}

interface EnvEntry {
  key: string;
  value: string;
  rawLine: string;
}

// ---------------------------------------------------------------------------
// Secret detection
// ---------------------------------------------------------------------------

const SECRET_KEYS = new Set([
  'ELEVENLABS_API_KEY',
  'FAL_KEY',
  'TELEGRAM_BOT_TOKEN',
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
]);

const SECRET_PATTERNS = [
  /_KEY$/,
  /_SECRET$/,
  /_TOKEN$/,
  /_PASSWORD$/,
];

function isSecret(key: string): boolean {
  if (SECRET_KEYS.has(key)) return true;
  return SECRET_PATTERNS.some((p) => p.test(key));
}

// ---------------------------------------------------------------------------
// .env parser
// ---------------------------------------------------------------------------

const ENV_LINE_RE = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/;

function parseEnv(filePath: string): EnvEntry[] {
  if (!fs.existsSync(filePath)) return [];

  const text = fs.readFileSync(filePath, 'utf-8');
  const entries: EnvEntry[] = [];

  for (const line of text.split('\n')) {
    const stripped = line.trim();
    if (!stripped || stripped.startsWith('#')) {
      entries.push({ key: '', value: '', rawLine: line });
      continue;
    }
    const match = ENV_LINE_RE.exec(stripped);
    if (match) {
      entries.push({ key: match[1], value: match[2], rawLine: line });
    } else {
      entries.push({ key: '', value: '', rawLine: line });
    }
  }

  return entries;
}

// ---------------------------------------------------------------------------
// Migration
// ---------------------------------------------------------------------------

/**
 * Migrate non-secret settings from ~/.atrophy/.env into ~/.atrophy/config.json.
 *
 * - Reads .env, separates secrets from settings
 * - Writes new settings into config.json (does not overwrite existing keys)
 * - Rewrites .env to contain only secrets and comments
 *
 * Returns a summary of what was done.
 */
export function migrateEnv(): MigrationResult {
  const envPath = path.join(USER_DATA, '.env');
  const configPath = path.join(USER_DATA, 'config.json');

  const result: MigrationResult = {
    migrated: [],
    skipped: [],
    secretsKept: [],
    configWritten: false,
    envRewritten: false,
  };

  const entries = parseEnv(envPath);
  if (entries.length === 0) {
    return result;
  }

  // Load existing config.json
  let config: Record<string, unknown> = {};
  try {
    if (fs.existsSync(configPath)) {
      config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    }
  } catch {
    config = {};
  }

  const remainingLines: string[] = [];

  for (const entry of entries) {
    if (!entry.key) {
      remainingLines.push(entry.rawLine);
      continue;
    }

    if (isSecret(entry.key)) {
      result.secretsKept.push(entry.key);
      remainingLines.push(entry.rawLine);
      continue;
    }

    // Non-secret setting - migrate if not already present
    if (!(entry.key in config)) {
      config[entry.key] = entry.value;
      result.migrated.push(entry.key);
    } else {
      result.skipped.push(entry.key);
    }
  }

  if (result.migrated.length > 0) {
    fs.mkdirSync(path.dirname(configPath), { recursive: true });
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + '\n', { mode: 0o600 });
    result.configWritten = true;

    // Rewrite .env with only secrets and comments
    const newEnvContent = remainingLines.join('\n').trim() + '\n';
    fs.writeFileSync(envPath, newEnvContent);
    result.envRewritten = true;
  }

  return result;
}
