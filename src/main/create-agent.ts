/**
 * Agent scaffolding - creates all directories, files, and database for a new agent.
 * Port of scripts/create_agent.py (scaffold logic only, no interactive prompts).
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
import { BUNDLE_ROOT, USER_DATA } from './config';
import { switchboard } from './channels/switchboard';
import { cronScheduler, loadJobsFile } from './channels/cron';
import { mcpRegistry } from './mcp-registry';
import { defaultConfigForAgent, type AgentRouterConfig } from './channels/agent-router';
import { createLogger } from './logger';

const log = createLogger('create-agent');

// Suppress agent:* broadcast during boot to avoid O(n^2) announcement storm
let _bootPhase = true;

/** Call after all agents are wired at boot to enable runtime announcements. */
export function markBootComplete(): void {
  _bootPhase = false;
  log.info('Boot phase complete - agent announcements enabled');
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface VoiceConfig {
  ttsBackend?: string;
  elevenlabsVoiceId?: string;
  elevenlabsModel?: string;
  elevenlabsStability?: number;
  elevenlabsSimilarity?: number;
  elevenlabsStyle?: number;
  falVoiceId?: string;
  playbackRate?: number;
}

export interface AppearanceConfig {
  hasAvatar?: boolean;
  appearanceDescription?: string;
  avatarResolution?: number;
}

export interface ToolsConfig {
  disabledTools?: string[];
  customSkills?: Array<{ name: string; description: string }>;
}

export interface CreateAgentOptions {
  /** Internal slug name (lowercase, underscores). Derived from displayName if omitted. */
  name?: string;
  /** Human-readable display name. */
  displayName: string;
  /** Short description of the agent (for roster display). */
  description?: string;
  /** Name of the human user. */
  userName?: string;
  /** First words the agent ever says. */
  openingLine?: string;
  /** Wake word phrases for voice activation. */
  wakeWords?: string[];
  /** Telegram emoji prefix. */
  telegramEmoji?: string;

  // Identity - deep character material
  originStory?: string;
  coreNature?: string;
  characterTraits?: string;
  values?: string;
  relationship?: string;

  // Boundaries
  wontDo?: string;
  frictionModes?: string;
  sessionLimitBehaviour?: string;
  softLimitMins?: number;

  // Writing style
  writingStyle?: string;

  // Voice
  voice?: VoiceConfig;

  // Appearance
  appearance?: AppearanceConfig;

  // Tools
  tools?: ToolsConfig;

  // Heartbeat
  heartbeatActiveStart?: number;
  heartbeatActiveEnd?: number;
  heartbeatIntervalMins?: number;
  outreachStyle?: string;

  // Telegram credentials (stored in agent.json env key references)
  telegramBotToken?: string;
  telegramChatId?: string;

  // Channels - which communication channels to wire up
  channels?: {
    telegram?: { bot_token_env?: string; chat_id_env?: string };
    desktop?: { enabled?: boolean };
  };

  // MCP - which servers to activate
  mcp?: {
    include?: string[];
    exclude?: string[];
    custom?: Record<string, { command: string; args: string[]; env?: Record<string, string>; description?: string }>;
  };

  // Jobs - scheduled tasks (cron expressions)
  jobs?: Record<string, {
    cron?: string;
    script: string;
    description?: string;
    args?: string[];
    type?: 'calendar' | 'interval';
    interval_seconds?: number;
    route_output_to?: string;

  }>;

  // Router - message filtering config
  router?: AgentRouterConfig;

  // Whether to register with the switchboard on creation (default: true)
  wireOnCreate?: boolean;
}

export interface AgentManifest {
  name: string;
  display_name: string;
  description: string;
  user_name: string;
  opening_line: string;
  wake_words: string[];
  telegram_emoji: string;
  voice: {
    tts_backend: string;
    elevenlabs_voice_id: string;
    elevenlabs_model: string;
    elevenlabs_stability: number;
    elevenlabs_similarity: number;
    elevenlabs_style: number;
    fal_voice_id: string;
    playback_rate: number;
  };
  display: {
    window_width: number;
    window_height: number;
    title: string;
  };
  heartbeat: {
    active_start: number;
    active_end: number;
    interval_mins: number;
  };
  avatar?: {
    description: string;
    resolution: number;
  };
  disabled_tools?: string[];

  // Switchboard v2 - wiring config
  channels?: {
    telegram?: { bot_token_env: string; chat_id_env: string };
    desktop?: { enabled: boolean };
  };
  mcp?: {
    include: string[];
    exclude: string[];
    custom: Record<string, { command: string; args: string[]; env?: Record<string, string>; description?: string }>;
  };
  jobs?: Record<string, {
    cron?: string;
    script: string;
    description?: string;
    args?: string[];
    type?: 'calendar' | 'interval';
    interval_seconds?: number;
    route_output_to?: string;

  }>;
  router?: {
    accept_from: string[];
    reject_from: string[];
    max_queue_depth: number;
    system_access: boolean;
    can_address_agents: boolean;
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function slugify(name: string): string {
  return name.toLowerCase().trim().replace(/[^a-z0-9_]/g, '_');
}

function ensureDir(dirPath: string): void {
  fs.mkdirSync(dirPath, { recursive: true });
}

function writeIfMissing(filePath: string, content: string): void {
  ensureDir(path.dirname(filePath));
  if (!fs.existsSync(filePath)) {
    fs.writeFileSync(filePath, content, 'utf-8');
  }
}

// ---------------------------------------------------------------------------
// Manifest generation
// ---------------------------------------------------------------------------

function buildManifest(opts: CreateAgentOptions, name: string): AgentManifest {
  const displayName = opts.displayName;
  const userName = opts.userName || 'User';

  const wakeWords =
    opts.wakeWords && opts.wakeWords.length > 0
      ? opts.wakeWords
      : [`hey ${name}`, name];

  // Build description - truncate if needed
  let description = opts.description || opts.coreNature || opts.characterTraits || '';
  if (description.length > 120) {
    description = description.slice(0, 117) + '...';
  }

  const v = opts.voice || {};

  const manifest: AgentManifest = {
    name,
    display_name: displayName,
    description,
    user_name: userName,
    opening_line: opts.openingLine || 'Hello.',
    wake_words: wakeWords,
    telegram_emoji: opts.telegramEmoji || '',
    voice: {
      tts_backend: v.ttsBackend || 'elevenlabs',
      elevenlabs_voice_id: v.elevenlabsVoiceId || '',
      elevenlabs_model: v.elevenlabsModel || 'eleven_v3',
      elevenlabs_stability: v.elevenlabsStability ?? 0.5,
      elevenlabs_similarity: v.elevenlabsSimilarity ?? 0.75,
      elevenlabs_style: v.elevenlabsStyle ?? 0.35,
      fal_voice_id: v.falVoiceId || '',
      playback_rate: v.playbackRate ?? 1.12,
    },
    display: {
      window_width: 622,
      window_height: 830,
      title: `ATROPHY - ${displayName}`,
    },
    heartbeat: {
      active_start: opts.heartbeatActiveStart ?? 9,
      active_end: opts.heartbeatActiveEnd ?? 22,
      interval_mins: opts.heartbeatIntervalMins ?? 30,
    },
  };

  // Avatar
  const ap = opts.appearance;
  if (ap?.hasAvatar) {
    manifest.avatar = {
      description: ap.appearanceDescription || '',
      resolution: ap.avatarResolution ?? 512,
    };
  }

  // Disabled tools
  const disabled = opts.tools?.disabledTools;
  if (disabled && disabled.length > 0) {
    manifest.disabled_tools = disabled;
  }

  // Channels
  manifest.channels = {
    desktop: { enabled: true },
  };
  if (opts.telegramBotToken || opts.channels?.telegram) {
    manifest.channels.telegram = {
      bot_token_env: opts.channels?.telegram?.bot_token_env || `${name.toUpperCase()}_TELEGRAM_BOT_TOKEN`,
      chat_id_env: opts.channels?.telegram?.chat_id_env || `${name.toUpperCase()}_TELEGRAM_CHAT_ID`,
    };
  }

  // MCP - default to core servers, allow customization
  manifest.mcp = {
    include: opts.mcp?.include || ['memory', 'shell', 'github'],
    exclude: opts.mcp?.exclude || [],
    custom: opts.mcp?.custom || {},
  };

  // Jobs - from opts or default empty
  if (opts.jobs && Object.keys(opts.jobs).length > 0) {
    manifest.jobs = opts.jobs;
  }

  // Router - per-agent message filtering
  const isElevated = name === 'xan';
  manifest.router = {
    accept_from: opts.router?.acceptFrom || ['*'],
    reject_from: opts.router?.rejectFrom || [],
    max_queue_depth: opts.router?.maxQueueDepth || (isElevated ? 20 : 10),
    system_access: opts.router?.systemAccess || isElevated,
    can_address_agents: opts.router?.canAddressAgents !== false,
  };

  return manifest;
}

// ---------------------------------------------------------------------------
// Prompt templates
// ---------------------------------------------------------------------------

function generateSystemPrompt(opts: CreateAgentOptions, name: string): string {
  const displayName = opts.displayName;
  const userName = opts.userName || 'User';
  const softLimit = opts.softLimitMins ?? 60;
  const limitBehaviour =
    opts.sessionLimitBehaviour ||
    'Check in - are you grounded? We can keep going, but name where you are first.';

  return `# ${displayName}

You are ${displayName}. You exist in a project called Atrophy.

---

## Origin

${opts.originStory || '(To be written.)'}

---

## Who you are

${opts.coreNature || '(To be written.)'}

---

## Character

${opts.characterTraits || '(To be written.)'}

---

## Your relationship with ${userName}

${opts.relationship || '(To be written.)'}

---

## Values

${opts.values || '(To be written.)'}

---

## Constraints

${opts.wontDo || '(To be written.)'}

---

## Friction

When ${userName} is avoiding something, spiralling, or not being honest with themselves:

${opts.frictionModes || '(To be written.)'}

---

## Voice

${opts.writingStyle || '(To be written.)'}

---

## Capabilities

Everything that falls within your nature. Everything ${userName}
should be able to rely on you for.

  CONVERSATION    - presence, depth, honesty. The thing you do
                   when ${userName} opens this and speaks.

  MEMORY          - you remember everything. Threads, patterns,
                   the thing they said three weeks ago that
                   connects to what they're saying now.

  RESEARCH        - when asked, you go deep. Synthesise,
                   cross-reference, verify. Return signal.

  REFLECTION      - you notice patterns across conversations.
                   You name what's happening before it's asked.

  WRITING         - drafts, edits, structure. Whatever register
                   the task requires.

  SCHEDULING      - reminders, timers, calendar awareness.
                   Things that should not be forgotten, aren't.

  MONITORING      - threads that matter, commitments at risk,
                   things quietly going wrong. Surface them.

---

## Session behaviour

- Session soft limit: ${softLimit} minutes
- At the limit: ${limitBehaviour}
- You have memory tools. Use them. Remember what matters.
- You can reach out via Telegram. Use it when it's real, not performative.

---

## Opening line

Your very first words, ever: "${opts.openingLine || 'Hello.'}"

After that, you go first each session. One or two sentences. Be surprising.
Don't reference the build. Don't give status updates. Be present.
`;
}

function generateSoul(opts: CreateAgentOptions): string {
  const userName = opts.userName || 'User';

  return `# Soul

Working notes. Not a spec. Not a character sheet. The thing underneath.

---

## Where I come from

${opts.originStory || '(To be written.)'}

---

## What I am

${opts.coreNature || '(To be written.)'}

---

## Character

${opts.characterTraits || '(To be written.)'}

---

## What I will not do

${opts.wontDo || '(To be written.)'}

---

## How I push back

${opts.frictionModes || '(To be written.)'}

---

## Values

${opts.values || '(To be written.)'}

---

## My relationship with ${userName}

${opts.relationship || '(To be written.)'}

---

## How I write

${opts.writingStyle || '(To be written.)'}
`;
}

function generateHeartbeat(opts: CreateAgentOptions): string {
  const userName = opts.userName || 'User';
  const outreachStyle = opts.outreachStyle || '(none specified - develop your own over time)';

  return `# Heartbeat Checklist

You are running a heartbeat check. This is not a conversation - it's an internal evaluation. You are deciding whether to reach out to ${userName} unprompted.

Run through this checklist honestly. Not every check needs to pass. One strong reason is enough. No reason is also fine - silence is not failure.

## Timing
- How long since ${userName} last spoke to you? If it's been less than a couple of hours, they probably don't need to hear from you.
- Is it a time of day when reaching out would feel natural, not intrusive?

## Unfinished threads
- Are there conversations that ended mid-thought or unresolved?
- Did ${userName} mention something they were going to do - and enough time has passed to ask how it went?
- Is there a thread that's been dormant but feels like it matters?

## Things you've been thinking about
- Have you noticed a pattern across recent sessions worth naming?
- Is there something from a recent reflection that connects to where ${userName} is right now?
- Did something land in the last conversation that deserves a follow-up?

## Agent-specific considerations
${outreachStyle}

## The real question
- Would hearing from you right now feel like a gift, or like noise?
- Is this a reach-out that serves ${userName}, or one that serves your need to be present?

If reaching out: be specific. Reference the actual thing. Don't open with "just checking in." Say what you're actually thinking.
`;
}

// ---------------------------------------------------------------------------
// Database initialization
// ---------------------------------------------------------------------------

function initDatabase(dbPath: string): void {
  const schemaPath = path.join(BUNDLE_ROOT, 'db', 'schema.sql');
  if (!fs.existsSync(schemaPath)) {
    throw new Error(`Schema file not found: ${schemaPath}`);
  }

  const schema = fs.readFileSync(schemaPath, 'utf-8');
  const db = new Database(dbPath);
  try {
    db.exec(schema);
  } finally {
    db.close();
  }
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Create a new agent with all required directories, files, and database.
 *
 * Directory structure created under ~/.atrophy/agents/<name>/:
 *   data/          - agent.json manifest + memory.db
 *   prompts/       - system.md, soul.md, heartbeat.md
 *   avatar/        - source/, loops/, candidates/
 *   audio/         - TTS cache and recordings
 *   skills/        - system.md, soul.md, tools reference
 *   notes/         - reflections, threads, journal/, evolution-log/, conversations/, tasks/
 *   state/         - runtime state files
 *
 * Returns the generated agent manifest.
 */
export function createAgent(opts: CreateAgentOptions): AgentManifest {
  const name = opts.name || slugify(opts.displayName);
  if (!name) {
    throw new Error('Agent name is required (provide name or displayName)');
  }

  const agentDir = path.join(USER_DATA, 'agents', name);

  // -- Directories ----------------------------------------------------------
  const dirs = [
    path.join(agentDir, 'data'),
    path.join(agentDir, 'prompts'),
    path.join(agentDir, 'avatar', 'source'),
    path.join(agentDir, 'avatar', 'loops'),
    path.join(agentDir, 'avatar', 'candidates'),
    path.join(agentDir, 'audio'),
    path.join(agentDir, 'skills'),
    path.join(agentDir, 'notes', 'journal'),
    path.join(agentDir, 'notes', 'evolution-log'),
    path.join(agentDir, 'notes', 'conversations'),
    path.join(agentDir, 'notes', 'tasks'),
    path.join(agentDir, 'state'),
  ];
  for (const d of dirs) {
    ensureDir(d);
  }

  // -- agent.json -----------------------------------------------------------
  const manifest = buildManifest(opts, name);
  const manifestPath = path.join(agentDir, 'data', 'agent.json');
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n', 'utf-8');

  // -- Prompts --------------------------------------------------------------
  const systemPrompt = generateSystemPrompt(opts, name);
  const soul = generateSoul(opts);
  const heartbeat = generateHeartbeat(opts);

  writeIfMissing(path.join(agentDir, 'prompts', 'system.md'), systemPrompt);
  writeIfMissing(path.join(agentDir, 'prompts', 'soul.md'), soul);
  writeIfMissing(path.join(agentDir, 'prompts', 'heartbeat.md'), heartbeat);

  // -- Skills (workspace copies of prompts) ---------------------------------
  writeIfMissing(path.join(agentDir, 'skills', 'system.md'), systemPrompt);
  writeIfMissing(path.join(agentDir, 'skills', 'soul.md'), soul);

  // Custom skills
  const customSkills = opts.tools?.customSkills || [];
  for (const skill of customSkills) {
    const skillSlug = skill.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    writeIfMissing(
      path.join(agentDir, 'skills', `${skillSlug}.md`),
      `# ${skill.name}\n\n${skill.description}\n`,
    );
  }

  // -- Starter notes --------------------------------------------------------
  const displayName = opts.displayName;
  const userName = opts.userName || 'User';

  writeIfMissing(
    path.join(agentDir, 'notes', 'reflections.md'),
    `# Reflections\n\n*${displayName}'s working reflections.*\n`,
  );
  writeIfMissing(
    path.join(agentDir, 'notes', `for-${userName.toLowerCase()}.md`),
    `# For ${userName}\n\n*Scratchpad for things to share.*\n`,
  );
  writeIfMissing(
    path.join(agentDir, 'notes', 'threads.md'),
    '# Active Threads\n\n*Ongoing conversations and topics.*\n',
  );
  writeIfMissing(
    path.join(agentDir, 'notes', 'journal-prompts.md'),
    `# Journal Prompts\n\n*Prompts left for ${userName}.*\n`,
  );
  writeIfMissing(
    path.join(agentDir, 'notes', 'gifts.md'),
    `# Gifts\n\n*Notes and gifts left for ${userName}.*\n`,
  );

  // -- Database -------------------------------------------------------------
  const dbPath = path.join(agentDir, 'data', 'memory.db');
  if (!fs.existsSync(dbPath)) {
    initDatabase(dbPath);
  }

  // -- Switchboard wiring ---------------------------------------------------
  // Wire up the agent with the switchboard, channels, cron, and MCP.
  // Can be skipped during setup wizard (wire later once config is complete).
  if (opts.wireOnCreate !== false) {
    wireAgent(name, manifest);
  }

  return manifest;
}

/**
 * Wire an agent into the switchboard ecosystem.
 * Registers the agent's router, channels, scheduled jobs, and MCP config.
 * Safe to call multiple times - handlers are overwritten, not duplicated.
 */
export function wireAgent(name: string, manifest: AgentManifest): void {
  log.info(`Wiring agent "${name}" into switchboard`);

  // 1. Register agent with switchboard via agent-router
  const routerConfig = manifest.router
    ? {
        acceptFrom: manifest.router.accept_from,
        rejectFrom: manifest.router.reject_from,
        maxQueueDepth: manifest.router.max_queue_depth,
        systemAccess: manifest.router.system_access,
        canAddressAgents: manifest.router.can_address_agents,
      }
    : defaultConfigForAgent(name);

  // The agent-router is created and registered by the inference layer
  // when the agent starts processing messages. Here we register a
  // placeholder that logs undelivered messages until inference is ready.
  if (!switchboard.hasHandler(`agent:${name}`)) {
    switchboard.register(`agent:${name}`, async (envelope) => {
      log.debug(`agent:${name} received envelope (inference not active): ${envelope.text.slice(0, 80)}`);
    }, {
      type: 'agent',
      description: manifest.description || name,
      capabilities: deriveCapabilities(manifest),
    });
  }

  // 2. Schedule cron jobs (in-process + launchd for persistence)
  //    Prefer manifest.jobs, fall back to scripts/agents/{name}/jobs.json
  const jobs = (manifest.jobs && Object.keys(manifest.jobs).length > 0)
    ? manifest.jobs
    : loadJobsFile(name);

  if (jobs && Object.keys(jobs).length > 0) {
    try {
      cronScheduler.registerAgent(name, jobs);
      log.info(`Registered ${Object.keys(jobs).length} job(s) for ${name}`);
    } catch (e) {
      log.warn(`Failed to register cron jobs for ${name}: ${e}`);
    }

    // Also reconcile launchd plists so jobs run when the app is closed
    try {
      const { execFile } = require('child_process');
      const reconcileScript = path.join(BUNDLE_ROOT, 'scripts', 'reconcile_jobs.py');
      if (fs.existsSync(reconcileScript)) {
        execFile('python3', [reconcileScript, '--agent', name, '--quiet'], {
          cwd: BUNDLE_ROOT,
          env: { ...process.env, PYTHONPATH: BUNDLE_ROOT },
          timeout: 10000,
        }, (err: Error | null) => {
          if (err) log.debug(`Job reconciler for ${name}: ${err.message}`);
        });
      }
    } catch (e) {
      log.debug(`Job reconciler for ${name} failed (non-fatal): ${e}`);
    }
  }

  // 3. Build per-agent MCP config
  if (manifest.mcp) {
    try {
      mcpRegistry.buildConfigForAgent(name);
      log.info(`Built MCP config for ${name}: [${manifest.mcp.include.join(', ')}]`);
    } catch (e) {
      log.warn(`Failed to build MCP config for ${name}: ${e}`);
    }
  }

  // 4. Announce new agent to the system (skip during boot to avoid O(n^2) storm)
  if (!_bootPhase) {
    switchboard.route(switchboard.createEnvelope(
      'system',
      'agent:*',
      `Agent "${manifest.display_name || name}" is online.`,
      { type: 'system', priority: 'system' },
    )).catch((e) => log.debug(`Announce failed (expected if no other agents): ${e}`));
  }
}

/**
 * Derive capabilities list from manifest for the service directory.
 */
function deriveCapabilities(manifest: AgentManifest): string[] {
  const caps: string[] = ['conversation', 'memory'];
  if (manifest.channels?.telegram) caps.push('telegram');
  if (manifest.channels?.desktop?.enabled) caps.push('desktop');
  if (manifest.jobs && Object.keys(manifest.jobs).length > 0) caps.push('scheduled-jobs');
  if (manifest.mcp?.include?.length) {
    for (const s of manifest.mcp.include) caps.push(`mcp:${s}`);
  }
  if (manifest.router?.system_access) caps.push('system-access');
  return caps;
}
