# src/main/create-agent.ts - Agent Scaffolding

**Line count:** ~829 lines  
**Dependencies:** `fs`, `path`, `better-sqlite3`, `./config`, `./channels/switchboard`, `./channels/cron`, `./channels/agent-router`, `./mcp-registry`, `./provisioning-scope`, `./logger`  
**Purpose:** Create all directories, files, and database for a new agent

## Overview

This module handles programmatic agent creation, building a complete agent directory structure with all required files, prompts, database, and switchboard wiring. It's called from the setup wizard (first launch) and via IPC (Settings panel agent creation).

The design prioritizes idempotency - all file writes use `writeIfMissing()`, so running `createAgent()` multiple times with the same name is safe.

## Types

### CreateAgentOptions

```typescript
export interface CreateAgentOptions {
  name?: string;              // Internal slug (derived from displayName)
  displayName: string;        // REQUIRED - human-readable name
  description?: string;       // Short description (truncated to 120 chars)
  userName?: string;          // default: 'User'
  openingLine?: string;       // default: 'Hello.'
  wakeWords?: string[];       // default: ['hey <name>', '<name>']
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

  // Telegram credentials
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
    custom?: Record<string, { command: string; args: string[]; env?: Record<string, string> }>;
  };

  // Jobs - scheduled tasks
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

  // Whether to register with switchboard on creation
  wireOnCreate?: boolean;

  // Org hierarchy context
  orgContext?: OrgContext;
}
```

### AgentManifest

```typescript
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
  avatar?: { description: string; resolution: number };
  disabled_tools?: string[];

  // Switchboard v2 - wiring config
  channels?: { /* ... */ };
  mcp?: { /* ... */ };
  jobs?: { /* ... */ };
  router?: { /* ... */ };
  org?: { /* ... */ };
}
```

## Helper Functions

### slugify

```typescript
function slugify(name: string): string {
  return name.toLowerCase().trim().replace(/[^a-z0-9_]/g, '_');
}
```

**Purpose:** Convert display name to filesystem-safe slug

### writeIfMissing

```typescript
function writeIfMissing(filePath: string, content: string): void {
  ensureDir(path.dirname(filePath));
  if (!fs.existsSync(filePath)) {
    fs.writeFileSync(filePath, content, 'utf-8');
  }
}
```

**Purpose:** Write file only if it doesn't exist (idempotent)

## buildManifest

```typescript
function buildManifest(opts: CreateAgentOptions, name: string): AgentManifest {
  const displayName = opts.displayName;
  const userName = opts.userName || 'User';

  const wakeWords = opts.wakeWords && opts.wakeWords.length > 0
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

  // Avatar, channels, mcp, jobs, router, org sections...
  return manifest;
}
```

**Defaults applied:**
- `wakeWords`: `['hey <name>', '<name>']`
- `openingLine`: `'Hello.'`
- `userName`: `'User'`
- Voice settings: ElevenLabs defaults
- Window size: 622x830
- Heartbeat: 9 AM - 10 PM, 30 min interval

## Prompt Generation

### generateSystemPrompt

```typescript
function generateSystemPrompt(opts: CreateAgentOptions, name: string): string {
  const sections = [
    `# ${opts.displayName}`,
    '',
    '## Origin',
    opts.originStory || '(To be written.)',
    '',
    '## Who You Are',
    opts.coreNature || '(To be written.)',
    '',
    '## Character',
    opts.characterTraits || '(To be written.)',
    '',
    '## Relationship',
    opts.relationship || '(To be written.)',
    '',
    '## Values',
    opts.values || '(To be written.)',
    '',
    '## What You Will Not Do',
    opts.wontDo || '(To be written.)',
    '',
    '## How You Push Back',
    opts.frictionModes || '(To be written.)',
    '',
    '## Voice',
    opts.writingStyle || '(To be written.)',
    '',
    '## Capabilities',
    'You have these capabilities:',
    '- CONVERSATION: You engage in natural, flowing dialogue',
    '- MEMORY: You remember what matters and forget what does not',
    '- RESEARCH: You can search the web and retrieve information',
    '- REFLECTION: You think about your own thinking',
    '- WRITING: You write notes, letters, and documents',
    '- SCHEDULING: You run background jobs on schedules',
    '- MONITORING: You watch for patterns and changes',
    '',
    '## Session Behaviour',
    opts.sessionLimitBehaviour || 'Check in - are you grounded?...',
    '',
    '## Opening',
    `Your opening line is: "${opts.openingLine || 'Hello.'}"`,
  ];

  return sections.join('\n');
}
```

### generateSoul

```typescript
function generateSoul(opts: CreateAgentOptions): string {
  const sections = [
    '# Working Notes',
    '',
    '## Where I Come From',
    opts.originStory || '(To be written.)',
    '',
    '## What I Am',
    opts.coreNature || '(To be written.)',
    '',
    '## Character',
    opts.characterTraits || '(To be written.)',
    '',
    '## What I Will Not Do',
    opts.wontDo || '(To be written.)',
    '',
    '## How I Push Back',
    opts.frictionModes || '(To be written.)',
    '',
    '## Values',
    opts.values || '(To be written.)',
    '',
    '## Relationship',
    opts.relationship || '(To be written.)',
    '',
    '## How I Write',
    opts.writingStyle || '(To be written.)',
  ];

  return sections.join('\n');
}
```

### generateHeartbeat

```typescript
function generateHeartbeat(opts: CreateAgentOptions): string {
  const sections = [
    '# Outreach Evaluation Checklist',
    '',
    '## Timing',
    `- Active hours: ${opts.heartbeatActiveStart ?? 9}:00 - ${opts.heartbeatActiveEnd ?? 22}:00`,
    `- Interval: every ${opts.heartbeatIntervalMins ?? 30} minutes`,
    '',
    '## Unfinished Threads',
    '- What threads are active that might need attention?',
    '- Has anything shifted while they were away?',
    '',
    '## Things You\'ve Been Thinking About',
    '- What has stayed with you from recent sessions?',
    '- What feels unresolved?',
    '',
    '## Agent-Specific Considerations',
    opts.outreachStyle || '(To be written.)',
    '',
    '## The Real Question',
    '**Would hearing from you right now feel like a gift, or like noise?**',
  ];

  return sections.join('\n');
}
```

## Directory Structure Created

```
~/.atrophy/agents/<name>/
├── data/
│   ├── agent.json             # Full manifest (JSON, 2-space indent)
│   └── memory.db              # SQLite database from schema.sql
├── prompts/
│   ├── system.md              # Generated system prompt
│   ├── soul.md                # Generated soul document
│   └── heartbeat.md           # Generated heartbeat checklist
├── avatar/
│   ├── source/                # Empty - user places face.png here
│   ├── loops/                 # Empty - for video loops
│   └── candidates/            # Empty - avatar generation writes here
├── audio/                     # Empty - TTS cache and recordings
├── skills/
│   ├── system.md              # Copy of system prompt for Obsidian
│   ├── soul.md                # Copy of soul document
│   └── <custom-skill>.md      # One per custom skill
└── notes/
    ├── reflections.md         # Starter: "# Reflections\n\n..."
    ├── for-<user>.md          # Starter: "# For <user>\n\n..."
    ├── threads.md             # Starter: "# Active Threads\n\n..."
    ├── journal-prompts.md     # Starter: "# Journal Prompts\n\n..."
    ├── gifts.md               # Starter: "# Gifts\n\n..."
    ├── journal/               # Empty - introspect.ts writes here
    ├── evolution-log/         # Empty - evolve.ts archives here
    ├── conversations/         # Empty - converse.ts writes here
    ├── tasks/                 # Empty - run-task.ts writes here
    └── state/                 # Empty - observer.ts writes state here
```

## createAgent Function

```typescript
export function createAgent(opts: CreateAgentOptions): AgentManifest {
  const name = opts.name || slugify(opts.displayName);
  if (!name) {
    throw new Error('Could not derive agent name');
  }

  const userAgentsDir = path.join(USER_DATA, 'agents');
  const agentDir = path.join(userAgentsDir, name);

  // Create directory structure
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
    path.join(agentDir, 'notes', 'state'),
  ];
  for (const dir of dirs) {
    ensureDir(dir);
  }

  // Build and write manifest
  const manifest = buildManifest(opts, name);
  const manifestPath = path.join(agentDir, 'data', 'agent.json');
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');

  // Generate and write prompts
  writeIfMissing(path.join(agentDir, 'prompts', 'system.md'),
    generateSystemPrompt(opts, name));
  writeIfMissing(path.join(agentDir, 'prompts', 'soul.md'),
    generateSoul(opts));
  writeIfMissing(path.join(agentDir, 'prompts', 'heartbeat.md'),
    generateHeartbeat(opts));

  // Copy prompts to skills
  writeIfMissing(path.join(agentDir, 'skills', 'system.md'),
    generateSystemPrompt(opts, name));
  writeIfMissing(path.join(agentDir, 'skills', 'soul.md'),
    generateSoul(opts));

  // Create starter notes
  writeIfMissing(path.join(agentDir, 'notes', 'reflections.md'),
    `# Reflections\n\n*${name}'s working reflections.*\n`);
  writeIfMissing(path.join(agentDir, 'notes', `for-${manifest.user_name}.md`),
    `# For ${manifest.user_name}\n\n*Scratchpad for things to share.*\n`);
  writeIfMissing(path.join(agentDir, 'notes', 'threads.md'),
    `# Active Threads\n\n*Ongoing conversations and topics.*\n`);
  writeIfMissing(path.join(agentDir, 'notes', 'journal-prompts.md'),
    `# Journal Prompts\n\n*Prompts left for ${manifest.user_name}.*\n`);
  writeIfMissing(path.join(agentDir, 'notes', 'gifts.md'),
    `# Gifts\n\n*Notes and gifts left for ${manifest.user_name}.*\n`);

  // Initialize database
  const dbPath = path.join(agentDir, 'data', 'memory.db');
  if (!fs.existsSync(dbPath)) {
    const schemaPath = path.join(BUNDLE_ROOT, 'db', 'schema.sql');
    const schema = fs.readFileSync(schemaPath, 'utf-8');
    const db = new Database(dbPath);
    db.exec(schema);
    db.close();
  }

  // Wire with switchboard if not in boot phase
  if (opts.wireOnCreate !== false && !_bootPhase) {
    try {
      wireAgent(name, manifest);
    } catch (e) {
      log.warn(`Failed to wire agent ${name}: ${e}`);
    }
  }

  log.info(`Created agent ${name} at ${agentDir}`);
  return manifest;
}
```

**Idempotency:**
- `writeIfMissing()` never overwrites existing files
- Database only created if missing
- Safe to re-run if interrupted

## wireAgent

```typescript
export function wireAgent(agentName: string, manifest: AgentManifest): void {
  // Register with switchboard
  const desktopAddress = `desktop:${agentName}`;
  switchboard.register(desktopAddress, async (envelope) => {
    // Desktop handler - displays messages in GUI
    log.info(`${agentName} received desktop message: ${envelope.text}`);
  }, {
    type: 'agent',
    description: `Desktop GUI for ${agentName}`,
  });

  // Register agent address for cross-agent messaging
  const agentAddress = `agent:${agentName}`;
  switchboard.register(agentAddress, async (envelope) => {
    // Agent-to-agent message handling
    log.info(`${agentName} received agent message from ${envelope.from}`);
  }, {
    type: 'agent',
    description: `Agent ${agentName}`,
  });

  // Install cron jobs from manifest
  if (manifest.jobs) {
    for (const [jobName, jobConfig] of Object.entries(manifest.jobs)) {
      try {
        cronScheduler.addJob(agentName, jobName, jobConfig);
      } catch (e) {
        log.warn(`Failed to add job ${jobName} for ${agentName}: ${e}`);
      }
    }
  }

  // Configure MCP servers
  if (manifest.mcp) {
    mcpRegistry.activateForAgent(agentName, manifest.mcp.include || []);
    for (const excluded of manifest.mcp.exclude || []) {
      mcpRegistry.deactivateForAgent(agentName, excluded);
    }
  }

  // Configure router
  if (manifest.router) {
    // Apply router configuration
  }

  // Announce to other agents (unless in boot phase)
  if (!_bootPhase) {
    switchboard.route(switchboard.createEnvelope(
      `system:${agentName}`,
      'agent:*',
      `${agentName} is now online`,
      { type: 'system', priority: 'low' },
    ));
  }

  log.info(`Wired agent ${agentName} with switchboard`);
}
```

**Purpose:** Register agent with switchboard, install cron jobs, configure MCP servers

## Boot Phase Suppression

```typescript
let _bootPhase = true;

export function markBootComplete(): void {
  _bootPhase = false;
  log.info('Boot phase complete - agent announcements enabled');
}
```

**Purpose:** Suppress agent:* broadcast during boot to avoid O(n²) announcement storm

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Write | `~/.atrophy/agents/<name>/data/agent.json` | createAgent |
| Write | `~/.atrophy/agents/<name>/data/memory.db` | createAgent (if missing) |
| Write | `~/.atrophy/agents/<name>/prompts/*.md` | createAgent (if missing) |
| Write | `~/.atrophy/agents/<name>/skills/*.md` | createAgent (if missing) |
| Write | `~/.atrophy/agents/<name>/notes/*.md` | createAgent (if missing) |
| Read | `<bundle>/db/schema.sql` | createAgent (database init) |

## Exported API

| Function | Purpose |
|----------|---------|
| `createAgent(opts)` | Create new agent with all files and database |
| `wireAgent(name, manifest)` | Wire agent with switchboard, cron, MCP |
| `markBootComplete()` | End boot phase, enable announcements |
| `CreateAgentOptions` | Options interface for agent creation |
| `AgentManifest` | Manifest interface |

## See Also

- `src/main/ipc/agents.ts` - IPC handlers for agent creation
- `src/main/agent-manager.ts` - Agent discovery and management
- `src/main/channels/switchboard.ts` - Switchboard registration
- `src/main/channels/cron.ts` - Cron job management
- `src/main/mcp-registry.ts` - MCP server configuration
- `db/schema.sql` - Database schema
