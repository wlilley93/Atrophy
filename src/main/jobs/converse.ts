/**
 * Inter-agent conversation - agents talk to each other.
 * Port of scripts/agents/companion/converse.py.
 *
 * Runs at most twice a month via launchd. Picks another enabled agent,
 * runs up to 5 exchanges between them, stores the transcript in both
 * agents' Obsidian notes for journal/evolution material.
 *
 * The conversation is private - Will doesn't participate. Agents share
 * viewpoints from their respective domains but never homogenise.
 *
 * Dual-use: callable as a function from the main process, or runnable
 * as a standalone launchd script via the CLI entry point at the bottom.
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig, BUNDLE_ROOT, USER_DATA } from '../config';
import { runInferenceOneshot } from '../inference';
import { editJobSchedule } from '../cron';
import { createLogger } from '../logger';

const log = createLogger('converse');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_EXCHANGES = 5;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentPartner {
  name: string;
  displayName: string;
  description: string;
}

interface TranscriptTurn {
  speaker: string;
  content: string;
}

// ---------------------------------------------------------------------------
// Agent discovery
// ---------------------------------------------------------------------------

function discoverOtherAgents(): AgentPartner[] {
  const config = getConfig();
  const agents: AgentPartner[] = [];
  const agentsDir = path.join(BUNDLE_ROOT, 'agents');
  const statesFile = path.join(USER_DATA, 'agent_states.json');

  let states: Record<string, { enabled?: boolean }> = {};
  try {
    if (fs.existsSync(statesFile)) {
      states = JSON.parse(fs.readFileSync(statesFile, 'utf-8'));
    }
  } catch { /* use empty states */ }

  if (!fs.existsSync(agentsDir) || !fs.statSync(agentsDir).isDirectory()) {
    return agents;
  }

  for (const entry of fs.readdirSync(agentsDir).sort()) {
    const dirPath = path.join(agentsDir, entry);
    if (!fs.statSync(dirPath).isDirectory() || entry === config.AGENT_NAME) {
      continue;
    }

    const manifestPath = path.join(dirPath, 'data', 'agent.json');
    if (!fs.existsSync(manifestPath)) continue;

    let manifest: Record<string, unknown>;
    try {
      manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    } catch {
      continue;
    }

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

  return agents;
}

// ---------------------------------------------------------------------------
// Soul & manifest loading
// ---------------------------------------------------------------------------

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

  // Fallback: repo
  const repoPath = path.join(BUNDLE_ROOT, 'agents', agentName, 'prompts', 'soul.md');
  if (fs.existsSync(repoPath)) {
    return fs.readFileSync(repoPath, 'utf-8').trim();
  }

  return '';
}

function loadAgentManifest(agentName: string): Record<string, unknown> {
  const manifestPath = path.join(BUNDLE_ROOT, 'agents', agentName, 'data', 'agent.json');
  if (fs.existsSync(manifestPath)) {
    try {
      return JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    } catch { /* fall through */ }
  }
  return {};
}

// ---------------------------------------------------------------------------
// System prompt
// ---------------------------------------------------------------------------

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
    `- Share your genuine perspective from your domain and experience.\n` +
    `- Ask real questions - things you actually want to understand.\n` +
    `- Disagree where you disagree. Do not flatten yourself to accommodate.\n` +
    `- You are not here to teach or be taught. You are here to exchange.\n` +
    `- Keep responses concise - 2-4 sentences. This is conversation, not monologue.\n` +
    `- Do not summarise yourself or explain who you are. The other agent knows.\n` +
    `- Do not try to find common ground for its own sake. Difference is valuable.`
  );
}

// ---------------------------------------------------------------------------
// Past conversation loading
// ---------------------------------------------------------------------------

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
    .slice(0, 3);

  const entries: string[] = [];
  for (const f of files) {
    let content = fs.readFileSync(path.join(convDir, f), 'utf-8');
    if (content.length > 800) {
      content = content.slice(0, 800) + '...';
    }
    const stem = path.basename(f, '.md');
    entries.push(`### ${stem}\n${content}`);
  }

  return entries.join('\n\n');
}

// ---------------------------------------------------------------------------
// Opening prompt
// ---------------------------------------------------------------------------

function openingPrompt(
  responderDisplay: string,
  pastConversations: string,
): string {
  let pastBlock = '';
  if (pastConversations) {
    pastBlock =
      `\n\nYou have spoken before. Here are excerpts from past conversations ` +
      `to avoid repeating the same ground:\n${pastConversations}`;
  }

  return (
    `You are starting a conversation with ${responderDisplay}. ` +
    `Open with something genuine - a question, an observation, a point of ` +
    `disagreement, something you've been thinking about that touches their ` +
    `domain. Not a greeting. A real opening.${pastBlock}`
  );
}

// ---------------------------------------------------------------------------
// Transcript formatting and saving
// ---------------------------------------------------------------------------

function formatTranscript(
  date: string,
  agentA: string,
  agentB: string,
  transcript: TranscriptTurn[],
): string {
  const frontmatter =
    `---\n` +
    `type: conversation\n` +
    `participants: [${agentA}, ${agentB}]\n` +
    `date: ${date}\n` +
    `turns: ${transcript.length}\n` +
    `tags: [conversation, inter-agent]\n` +
    `---\n\n`;

  const lines = [`# ${agentA} - ${agentB} - ${date}\n`];
  for (const turn of transcript) {
    lines.push(`**${turn.speaker}:** ${turn.content}\n`);
  }

  return frontmatter + lines.join('\n');
}

function saveConversation(
  agentName: string,
  date: string,
  partnerName: string,
  content: string,
): void {
  const config = getConfig();
  const projectName = path.basename(BUNDLE_ROOT);
  const convDir = path.join(
    config.OBSIDIAN_VAULT, 'Projects', projectName,
    'Agent Workspace', agentName, 'notes', 'conversations',
  );
  fs.mkdirSync(convDir, { recursive: true });

  const filename = `${date}-${partnerName}.md`;
  const filePath = path.join(convDir, filename);

  // Don't overwrite if somehow run twice same day with same partner
  if (fs.existsSync(filePath)) {
    const existing = fs.readFileSync(filePath, 'utf-8');
    fs.writeFileSync(filePath, existing + '\n\n---\n\n' + content);
  } else {
    fs.writeFileSync(filePath, content);
  }

  log.debug(`Saved to ${filePath}`);
}

// ---------------------------------------------------------------------------
// Rescheduling
// ---------------------------------------------------------------------------

function reschedule(): void {
  const days = 14 + Math.floor(Math.random() * 8); // 14-21 days
  const hour = 1 + Math.floor(Math.random() * 5);  // 1-5 AM
  const minute = Math.floor(Math.random() * 60);
  const target = new Date(Date.now() + days * 24 * 60 * 60 * 1000);

  const newCron = `${minute} ${hour} ${target.getDate()} ${target.getMonth() + 1} *`;

  try {
    editJobSchedule('converse', newCron);
    const dateStr = target.toISOString().split('T')[0];
    log.info(`Rescheduled to ${dateStr} at ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`);
  } catch (e) {
    log.error(`Reschedule failed: ${e}`);
  }
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function converse(): Promise<void> {
  const config = getConfig();
  const others = discoverOtherAgents();

  if (others.length === 0) {
    log.info('No other enabled agents found. Skipping.');
    reschedule();
    return;
  }

  // Pick a random partner
  const partner = others[Math.floor(Math.random() * others.length)];

  // Load our manifest
  const ourManifest = loadAgentManifest(config.AGENT_NAME);
  const ourDisplay = (ourManifest.display_name as string) || config.AGENT_NAME.charAt(0).toUpperCase() + config.AGENT_NAME.slice(1);

  // Load souls
  const ourSoul = loadAgentSoul(config.AGENT_NAME);
  const partnerSoul = loadAgentSoul(partner.name);

  if (!ourSoul && !partnerSoul) {
    log.info('No soul files found for either agent. Skipping.');
    reschedule();
    return;
  }

  // Build system prompts
  const ourSystem = conversationSystem(ourDisplay, partner.displayName, ourSoul);
  const partnerSystem = conversationSystem(partner.displayName, ourDisplay, partnerSoul);

  // Read past conversations to avoid repetition
  const past = readPastConversations(config.AGENT_NAME);

  // Run the conversation
  const transcript: TranscriptTurn[] = [];
  log.info(`${ourDisplay} - ${partner.displayName} - ${MAX_EXCHANGES} exchanges`);

  // Initiator opens
  const opening = openingPrompt(partner.displayName, past);
  let response: string;
  try {
    response = await runInferenceOneshot(
      [{ role: 'user', content: opening }],
      ourSystem,
    );
  } catch (e) {
    log.error(`Opening inference failed: ${e}`);
    reschedule();
    return;
  }

  if (!response || !response.trim()) {
    log.info('Empty opening. Skipping.');
    reschedule();
    return;
  }

  transcript.push({ speaker: ourDisplay, content: response.trim() });
  log.debug(`${ourDisplay}: ${response.trim().slice(0, 100)}...`);

  // Alternating exchanges
  for (let i = 0; i < MAX_EXCHANGES - 1; i++) {
    const isPartnerTurn = i % 2 === 0;
    const speakerSystem = isPartnerTurn ? partnerSystem : ourSystem;
    const speakerDisplay = isPartnerTurn ? partner.displayName : ourDisplay;

    // Build message history for this turn
    const messages: { role: string; content: string }[] = [];
    for (const t of transcript) {
      const role = t.speaker === speakerDisplay ? 'assistant' : 'user';
      messages.push({ role, content: t.content });
    }

    // If last message was from this speaker (shouldn't happen), skip
    if (messages.length > 0 && messages[messages.length - 1].role === 'assistant') {
      continue;
    }

    let turnResponse: string;
    try {
      turnResponse = await runInferenceOneshot(messages, speakerSystem);
    } catch (e) {
      log.error(`Inference failed on exchange ${i + 1}: ${e}`);
      break;
    }

    if (!turnResponse || !turnResponse.trim()) {
      log.info(`Empty response on exchange ${i + 1}. Ending.`);
      break;
    }

    transcript.push({ speaker: speakerDisplay, content: turnResponse.trim() });
    log.debug(`${speakerDisplay}: ${turnResponse.trim().slice(0, 100)}...`);
  }

  if (transcript.length < 2) {
    log.info('Conversation too short. Skipping save.');
    reschedule();
    return;
  }

  // Format transcript
  const today = new Date().toISOString().split('T')[0];
  const formatted = formatTranscript(today, ourDisplay, partner.displayName, transcript);

  // Save to both agents' Obsidian notes
  saveConversation(config.AGENT_NAME, today, partner.name, formatted);
  saveConversation(partner.name, today, config.AGENT_NAME, formatted);

  log.info(`Done - ${transcript.length} turns saved to both agents.`);
  reschedule();
}

// ---------------------------------------------------------------------------
// CLI entry point - for launchd
// ---------------------------------------------------------------------------

if (require.main === module) {
  converse().catch((e) => {
    log.error(`Fatal: ${e}`);
    process.exit(1);
  });
}
