/**
 * Agent manifest validator. Validates agent.json against known constraints
 * and logs warnings on boot. Does NOT block loading - just warns.
 *
 * Called from config.ts after loadAgentManifest() resolves the merged manifest.
 * Follows the same "warn, don't crash" philosophy as the rest of the config system.
 */

export interface ManifestWarning {
  field: string;
  message: string;
  severity: 'error' | 'warn';
}

const NAME_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/;
const CRON_PATTERN = /^[0-9*,/-]+ [0-9*,/-]+ [0-9*,/-]+ [0-9*,/-]+ [0-9*,/-]+$/;

const TTS_BACKENDS = new Set(['elevenlabs', 'fal', 'piper', 'disabled']);
const JOB_TYPES = new Set(['calendar', 'interval']);
const NOTIFY_VIA_ROOT = new Set(['auto', 'telegram', 'both']);
const NOTIFY_VIA_JOB = new Set(['telegram', 'db']);

function checkRange(val: unknown, min: number, max: number, field: string, warnings: ManifestWarning[]): void {
  if (typeof val !== 'number') return;
  if (val < min || val > max) {
    warnings.push({ field, message: `${val} is outside range [${min}, ${max}]`, severity: 'warn' });
  }
}

function checkEnum(val: unknown, allowed: Set<string>, field: string, warnings: ManifestWarning[]): void {
  if (typeof val !== 'string') return;
  if (!allowed.has(val)) {
    warnings.push({ field, message: `"${val}" is not one of: ${Array.from(allowed).join(', ')}`, severity: 'warn' });
  }
}

function checkType(val: unknown, expected: string, field: string, warnings: ManifestWarning[]): boolean {
  if (val === undefined || val === null) return false;
  if (typeof val !== expected) {
    warnings.push({ field, message: `expected ${expected}, got ${typeof val}`, severity: 'warn' });
    return false;
  }
  return true;
}

export function validateManifest(manifest: Record<string, unknown>, agentName: string): ManifestWarning[] {
  const warnings: ManifestWarning[] = [];

  // --- Required fields ---
  if (!manifest.name) {
    warnings.push({ field: 'name', message: 'missing (required)', severity: 'error' });
  } else if (typeof manifest.name === 'string' && !NAME_PATTERN.test(manifest.name)) {
    warnings.push({ field: 'name', message: `"${manifest.name}" does not match pattern [a-zA-Z0-9][a-zA-Z0-9_-]*`, severity: 'error' });
  }

  if (!manifest.display_name) {
    warnings.push({ field: 'display_name', message: 'missing (required)', severity: 'error' });
  }

  if (!manifest.description) {
    warnings.push({ field: 'description', message: 'missing (required)', severity: 'error' });
  }

  // --- Deprecated fields ---
  if (manifest.telegram_bot_token) {
    warnings.push({ field: 'telegram_bot_token', message: 'deprecated - migrate to channels.telegram.bot_token_env', severity: 'warn' });
  }
  if (manifest.telegram_chat_id) {
    warnings.push({ field: 'telegram_chat_id', message: 'deprecated - migrate to channels.telegram.chat_id_env', severity: 'warn' });
  }
  if (manifest.telegram_dm_chat_id) {
    warnings.push({ field: 'telegram_dm_chat_id', message: 'deprecated - migrate to channels.telegram.chat_id_env', severity: 'warn' });
  }
  if (manifest.role !== undefined && typeof manifest.role === 'string') {
    warnings.push({ field: 'role', message: 'deprecated - migrate to org.role', severity: 'warn' });
  }

  // --- Root-level enums ---
  if (manifest.notify_via !== undefined) {
    checkEnum(manifest.notify_via, NOTIFY_VIA_ROOT, 'notify_via', warnings);
  }

  // --- Voice ---
  const voice = manifest.voice as Record<string, unknown> | undefined;
  if (voice && typeof voice === 'object') {
    if (voice.tts_backend !== undefined) checkEnum(voice.tts_backend, TTS_BACKENDS, 'voice.tts_backend', warnings);
    checkRange(voice.elevenlabs_stability, 0, 1, 'voice.elevenlabs_stability', warnings);
    checkRange(voice.elevenlabs_similarity, 0, 1, 'voice.elevenlabs_similarity', warnings);
    checkRange(voice.elevenlabs_style, 0, 1, 'voice.elevenlabs_style', warnings);
    checkRange(voice.playback_rate, 0.1, 3.0, 'voice.playback_rate', warnings);
  }

  // --- Heartbeat ---
  const heartbeat = manifest.heartbeat as Record<string, unknown> | undefined;
  if (heartbeat && typeof heartbeat === 'object') {
    checkRange(heartbeat.active_start, 0, 23, 'heartbeat.active_start', warnings);
    checkRange(heartbeat.active_end, 0, 23, 'heartbeat.active_end', warnings);
    if (typeof heartbeat.interval_mins === 'number' && heartbeat.interval_mins < 1) {
      warnings.push({ field: 'heartbeat.interval_mins', message: 'must be >= 1', severity: 'warn' });
    }
  }

  // --- Jobs ---
  const jobs = manifest.jobs as Record<string, Record<string, unknown>> | undefined;
  if (jobs && typeof jobs === 'object') {
    for (const [jobName, job] of Object.entries(jobs)) {
      if (!job || typeof job !== 'object') continue;

      if (!job.script) {
        warnings.push({ field: `jobs.${jobName}.script`, message: 'missing (required)', severity: 'error' });
      }

      if (job.type !== undefined) checkEnum(job.type, JOB_TYPES, `jobs.${jobName}.type`, warnings);

      if (job.cron !== undefined && typeof job.cron === 'string' && !CRON_PATTERN.test(job.cron)) {
        warnings.push({ field: `jobs.${jobName}.cron`, message: `"${job.cron}" does not look like a 5-field cron expression`, severity: 'warn' });
      }

      if (job.type === 'interval' && !job.interval_seconds) {
        warnings.push({ field: `jobs.${jobName}.interval_seconds`, message: 'required when type is "interval"', severity: 'warn' });
      }

      if (job.timeout_seconds !== undefined) {
        checkRange(job.timeout_seconds, 1, 3600, `jobs.${jobName}.timeout_seconds`, warnings);
      }

      if (job.notify_via !== undefined) {
        checkEnum(job.notify_via, NOTIFY_VIA_JOB, `jobs.${jobName}.notify_via`, warnings);
      }
    }
  }

  // --- Router ---
  const router = manifest.router as Record<string, unknown> | undefined;
  if (router && typeof router === 'object') {
    if (router.max_queue_depth !== undefined) {
      checkRange(router.max_queue_depth, 1, 100, 'router.max_queue_depth', warnings);
    }
  }

  // --- Org ---
  const org = manifest.org as Record<string, unknown> | undefined;
  if (org && typeof org === 'object') {
    if (org.tier !== undefined) checkRange(org.tier, 0, 5, 'org.tier', warnings);
  }

  // --- Personality ---
  const personality = manifest.personality as Record<string, unknown> | undefined;
  if (personality && typeof personality === 'object') {
    for (const [dim, val] of Object.entries(personality)) {
      checkRange(val, 0, 1, `personality.${dim}`, warnings);
    }
  }

  return warnings;
}

/**
 * Log manifest validation warnings. Call after loadAgentManifest().
 * Only logs if there are issues - silent when manifest is clean.
 */
export function logManifestWarnings(manifest: Record<string, unknown>, agentName: string): void {
  if (process.env.NODE_ENV === 'test' || process.env.VITEST) return;

  const warnings = validateManifest(manifest, agentName);
  if (warnings.length === 0) return;

  const errors = warnings.filter(w => w.severity === 'error');
  const warns = warnings.filter(w => w.severity === 'warn');

  if (errors.length > 0) {
    console.error(`[manifest] ${agentName}: ${errors.length} error(s) in agent.json:`);
    for (const e of errors) {
      console.error(`  [ERROR] ${e.field}: ${e.message}`);
    }
  }

  if (warns.length > 0) {
    console.warn(`[manifest] ${agentName}: ${warns.length} warning(s) in agent.json:`);
    for (const w of warns) {
      console.warn(`  [WARN]  ${w.field}: ${w.message}`);
    }
  }
}
