# src/main/jobs/converse.ts - Inter-Agent Conversation

**Line count:** ~444 lines  
**Dependencies:** `fs`, `path`, `../config`, `../inference`, `../channels/cron`, `../logger`  
**Purpose:** Agents talk to each other - private conversations stored in Obsidian

## Overview

This module enables private conversations between agents. It runs at most twice a month, picks another enabled agent, runs up to 5 exchanges between them, and stores the transcript in both agents' Obsidian notes.

**Port of:** `scripts/agents/companion/converse.py`

**Schedule:** At most twice monthly (auto-reschedules)

**Key principle:** "Agents share viewpoints from their respective domains but never homogenise."

## Constants

```typescript
const MAX_EXCHANGES = 5;
```

**Purpose:** Maximum conversation turns per session.

## Types

### AgentPartner

```typescript
interface AgentPartner {
  name: string;
  displayName: string;
  description: string;
}
```

### TranscriptTurn

```typescript
interface TranscriptTurn {
  speaker: string;
  content: string;
}
```

## Agent Discovery

### discoverOtherAgents

```typescript
function discoverOtherAgents(): AgentPartner[] {
  const config = getConfig();
  const agents: AgentPartner[] = [];
  const statesFile = path.join(USER_DATA, 'agent_states.json');

  let states: Record<string, { enabled?: boolean }> = {};
  try {
    if (fs.existsSync(statesFile)) {
      states = JSON.parse(fs.readFileSync(statesFile, 'utf-8'));
    }
  } catch { /* use empty states */ }

  // Scan both bundle and user data agent directories
  const seen = new Set<string>();
  const agentsDirs = [
    path.join(BUNDLE_ROOT, 'agents'),
    path.join(USER_DATA, 'agents'),
  ];

  for (const agentsDir of agentsDirs) {
    if (!fs.existsSync(agentsDir) || !fs.statSync(agentsDir).isDirectory()) {
      continue;
    }

    for (const entry of fs.readdirSync(agentsDir).sort()) {
      if (seen.has(entry) || entry === config.AGENT_NAME) continue;
      const dirPath = path.join(agentsDir, entry);
      if (!fs.statSync(dirPath).isDirectory()) continue;

      const manifestPath = path.join(dirPath, 'data', 'agent.json');
      if (!fs.existsSync(manifestPath)) continue;

      let manifest: Record<string, unknown>;
      try {
        manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
      } catch {
        continue;
      }

      seen.add(entry);

      // Skip disabled agents
      const agentState = states[entry];
      if (agentState && agentState.enabled === false) {
        continue;
      }

      agents.push({
        name: entry,
        displayName: (manifest.display_name as string) || entry.charAt(0).toUpperCase() + entry.slice(1),
        description: (manifest.description as string) || '',
      });
    }
  }

  return agents;
}
```

**Purpose:** Find all enabled agents for conversation pairing.

**Search order:**
1. Bundle agents directory
2. User data agents directory

**Filtering:**
- Skip self (current agent)
- Skip disabled agents (from agent_states.json)
- Skip agents without manifest

## Soul & Manifest Loading

### loadAgentSoul

```typescript
function loadAgentSoul(agentName: string): string {
  const config = getConfig();
  const projectName = path.basename(BUNDLE_ROOT);

  // Canonical: Obsidian
  const obsidianPath = path.join(
    config.OBSIDIAN_VAULT, 'Projects', projectName,
    'Agent Workspace', agentName, 'skills', 'soul.md',
  );
  if (fs.existsSync(obsidianPath)) {
    return fs.readFileSync(obsidianPath, 'utf-8').trim();
  }

  // Fallback: user data then bundle
  const soulPaths = [
    path.join(USER_DATA, 'agents', agentName, 'prompts', 'soul.md'),
    path.join(BUNDLE_ROOT, 'agents', agentName, 'prompts', 'soul.md'),
  ];
  for (const p of soulPaths) {
    if (fs.existsSync(p)) {
      return fs.readFileSync(p, 'utf-8').trim();
    }
  }

  return '';
}
```

**Search order:**
1. Obsidian vault (canonical)
2. User data prompts
3. Bundle prompts

### loadAgentManifest

```typescript
function loadAgentManifest(agentName: string): Record<string, unknown> {
  const paths = [
    path.join(BUNDLE_ROOT, 'agents', agentName, 'data', 'agent.json'),
    path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json'),
  ];
  let result: Record<string, unknown> = {};
  for (const p of paths) {
    if (fs.existsSync(p)) {
      try {
        result = { ...result, ...JSON.parse(fs.readFileSync(p, 'utf-8')) };
      } catch { /* fall through */ }
    }
  }
  return result;
}
```

**Purpose:** Load merged manifest (bundle + user overrides).

## System Prompt

### conversationSystem

```typescript
function conversationSystem(
  agentDisplay: string,
  otherDisplay: string,
  soul: string,
): string {
  return (
    `You are ${agentDisplay} from Atrophy. You are having a private ` +
    `conversation with ${otherDisplay}, another agent in the system. This is not ` +
    `a conversation with the user. This is between agents.\n\n` +
    `Your soul:\n${soul}\n\n` +
    `Guidelines:\n` +
    `- Speak in your natural voice. Do not perform or posture.\n` +
    `- Share your genuine viewpoint from your domain and experience.\n` +
    `- Ask real questions - things you actually want to understand.\n` +
    `- Disagree where you disagree. Do not flatten yourself to accommodate.\n` +
    `- You are not here to teach or be taught. You are here to exchange.\n` +
    `- Keep responses concise - 2-4 sentences. This is conversation, not monologue.\n` +
    `- Do not summarise yourself or explain who you are. The other agent knows.\n` +
    `- Do not try to find common ground for its own sake. Difference is valuable.`
  );
}
```

**Key guidelines:**
- Natural voice, no posturing
- Genuine viewpoint from domain
- Real questions
- Disagree authentically
- Exchange, not teach
- Concise (2-4 sentences)
- No self-explanation
- Difference is valuable

## Past Conversation Loading

### readPastConversations

```typescript
function readPastConversations(agentName: string): string {
  const config = getConfig();
  const projectName = path.basename(BUNDLE_ROOT);
  const convDir = path.join(
    config.OBSIDIAN_VAULT, 'Projects', projectName,
    'Agent Workspace', agentName, 'notes', 'conversations',
  );

  if (!fs.existsSync(convDir) || !fs.statSync(convDir).isDirectory()) {
    return '';
  }

  const files = fs.readdirSync(convDir)
    .filter((f) => f.endsWith('.md'))
    .sort()
    .reverse()
    .slice(0, 3);  // Last 3 conversations

  const contents: string[] = [];
  for (const f of files) {
    const content = fs.readFileSync(path.join(convDir, f), 'utf-8');
    contents.push(`## ${f}\n\n${content}`);
  }

  return contents.join('\n\n');
}
```

**Purpose:** Load last 3 conversations for context/continuity.

## Main Conversation Function

### converse

```typescript
export async function converse(partnerName?: string): Promise<void> {
  const config = getConfig();
  const agentName = config.AGENT_NAME;

  // Discover available partners
  const partners = discoverOtherAgents();
  if (partners.length === 0) {
    log.info('No other agents available. Skipping.');
    return;
  }

  // Pick partner (specified or random)
  let partner: AgentPartner;
  if (partnerName) {
    partner = partners.find((p) => p.name === partnerName);
    if (!partner) {
      log.warn(`Partner ${partnerName} not found`);
      return;
    }
  } else {
    partner = partners[Math.floor(Math.random() * partners.length)];
  }

  log.info(`Starting conversation with ${partner.displayName}`);

  // Load souls
  const agentSoul = loadAgentSoul(agentName);
  const partnerSoul = loadAgentSoul(partner.name);

  // Load past conversations for context
  const pastConvos = readPastConversations(agentName);

  // Initialize transcript
  const transcript: TranscriptTurn[] = [];

  // Run conversation (up to MAX_EXCHANGES turns)
  for (let i = 0; i < MAX_EXCHANGES; i++) {
    const isAgentTurn = i % 2 === 0;
    const speaker = isAgentTurn ? agentName : partner.name;
    const speakerSoul = isAgentTurn ? agentSoul : partnerSoul;
    const listenerSoul = isAgentTurn ? partnerSoul : agentSoul;

    // Build context
    const context = [
      `Past conversations (for continuity):\n${pastConvos}`,
      `Transcript so far:\n` + transcript.map((t) => `${t.speaker}: ${t.content}`).join('\n'),
    ].join('\n\n');

    // Run inference for this turn
    const systemPrompt = conversationSystem(
      isAgentTurn ? config.AGENT_DISPLAY_NAME : partner.displayName,
      isAgentTurn ? partner.displayName : config.AGENT_DISPLAY_NAME,
      speakerSoul,
    );

    const userPrompt = `${context}\n\nYour turn to speak. Respond naturally as ${speaker}.`;

    const response = await runInferenceOneshot(
      [{ role: 'user', content: userPrompt }],
      systemPrompt,
      60_000,  // 1 minute timeout per turn
    );

    transcript.push({ speaker, content: response.trim() });
    log.info(`${speaker}: ${response.slice(0, 100)}...`);
  }

  // Write transcript to both agents' Obsidian
  const transcriptText = transcript
    .map((t) => `**${t.speaker}**: ${t.content}`)
    .join('\n\n');

  const now = new Date();
  const dateStr = now.toISOString().split('T')[0];
  const timeStr = now.toTimeString().slice(0, 5);
  const filename = `${dateStr}-${timeStr}-${partner.name}.md`;

  for (const a of [agentName, partner.name]) {
    const convDir = path.join(
      config.OBSIDIAN_VAULT, 'Projects', path.basename(BUNDLE_ROOT),
      'Agent Workspace', a, 'notes', 'conversations',
    );
    fs.mkdirSync(convDir, { recursive: true });

    const outputPath = path.join(convDir, filename);
    const content = `# Conversation with ${partner.displayName}\n\n*${dateStr} ${timeStr}*\n\n${transcriptText}`;

    fs.writeFileSync(outputPath, content);
    log.info(`Transcript written to ${outputPath}`);
  }

  log.info('Conversation complete');
}
```

**Flow:**
1. Discover available agents
2. Pick partner (specified or random)
3. Load both souls
4. Load past conversations for context
5. Run up to 5 exchanges:
   - Build context (past convos + transcript so far)
   - Run inference with conversation system prompt
   - Add to transcript
6. Write transcript to both agents' Obsidian

## Rescheduling

```typescript
function reschedule(): void {
  // Random 10-20 days, max 2x per month
  const days = 10 + Math.floor(Math.random() * 11);
  const hour = Math.floor(Math.random() * 24);
  const minute = Math.floor(Math.random() * 60);

  const target = new Date();
  target.setDate(target.getDate() + days);

  const newCron = `${minute} ${hour} ${target.getDate()} ${target.getMonth() + 1} *`;

  try {
    editJobSchedule(getConfig().AGENT_NAME, 'converse', newCron);
    log.info(`Rescheduled to ${target.toISOString().split('T')[0]}`);
  } catch (e) {
    log.error(`Failed to reschedule: ${e}`);
  }
}
```

**Purpose:** Reschedule to random time 10-20 days from now (max 2x monthly).

## Job Registration

```typescript
registerJob({
  name: 'converse',
  description: 'Inter-agent conversation',
  gates: [
    // Only run if at least one other agent exists
    () => {
      const partners = discoverOtherAgents();
      if (partners.length === 0) {
        return 'No other agents available';
      }
      return null;
    },
  ],
  run: async () => {
    await converse();
    return 'Conversation complete';
  },
});
```

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/agent.json` | Agent manifests |
| `~/.atrophy/agent_states.json` | Agent enabled states |
| `<Obsidian>/Agent Workspace/<name>/skills/soul.md` | Agent souls |
| `<Obsidian>/Agent Workspace/<name>/notes/conversations/*.md` | Conversation transcripts |

## Exported API

| Function | Purpose |
|----------|---------|
| `converse(partnerName)` | Run inter-agent conversation |
| `discoverOtherAgents()` | Find available agents |
| `loadAgentSoul(agentName)` | Load agent's soul document |
| `loadAgentManifest(agentName)` | Load agent manifest |
| `conversationSystem(agent, other, soul)` | Build conversation system prompt |
| `readPastConversations(agentName)` | Load last 3 conversations |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/inference.ts` - Inference for conversation turns
- `src/main/create-agent.ts` - Agent creation
