/**
 * Context assembly for inference.
 * Port of core/context.py.
 *
 * With the resume-based flow, the system prompt is only sent once
 * when the CLI session is created. The companion uses MCP memory
 * tools for active recall instead of passive injection.
 *
 * assemble_context is preserved for the SDK fallback path and
 * for summary generation.
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from './config';
import { loadPrompt, loadSkillFiles } from './prompts';
import * as memory from './memory';

// ---------------------------------------------------------------------------
// Agent roster (inline - avoids circular dep with agent-manager)
// ---------------------------------------------------------------------------

interface RosterEntry {
  name: string;
  display_name: string;
  description: string;
}

function getAgentRoster(exclude?: string): RosterEntry[] {
  const config = getConfig();
  const agentsDirs: string[] = [];

  const userAgents = path.join(config.DATA_DIR, '..', '..');
  const bundleAgents = path.join(config.AGENT_DIR, '..');

  if (fs.existsSync(userAgents)) agentsDirs.push(userAgents);
  if (fs.existsSync(bundleAgents) && path.resolve(bundleAgents) !== path.resolve(userAgents)) {
    agentsDirs.push(bundleAgents);
  }

  const seen = new Set<string>();
  const agents: RosterEntry[] = [];

  for (const agentsDir of agentsDirs) {
    let entries: string[];
    try {
      entries = fs.readdirSync(agentsDir).sort();
    } catch {
      continue;
    }

    for (const name of entries) {
      if (seen.has(name)) continue;
      const manifestPath = path.join(agentsDir, name, 'data', 'agent.json');
      if (!fs.existsSync(manifestPath)) continue;
      seen.add(name);

      if (name === exclude) continue;

      try {
        const data = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
        if (!data) continue;

        // Check enabled state
        const statesFile = getConfig().AGENT_STATES_FILE;
        if (fs.existsSync(statesFile)) {
          try {
            const states = JSON.parse(fs.readFileSync(statesFile, 'utf-8'));
            const state = states[name];
            if (state && state.enabled === false) continue;
          } catch { /* include by default */ }
        }

        agents.push({
          name,
          display_name: data.display_name || name.charAt(0).toUpperCase() + name.slice(1),
          description: data.description || '',
        });
      } catch {
        continue;
      }
    }
  }

  return agents;
}

// ---------------------------------------------------------------------------
// Load system prompt
// ---------------------------------------------------------------------------

export function loadSystemPrompt(): string {
  const config = getConfig();

  // Try loading system.md from the tiered search dirs
  let base = loadPrompt('system', '');

  // Fallback to bundle system_prompt.md
  if (!base) {
    const bundlePath = path.join(config.AGENT_DIR, 'prompts', 'system_prompt.md');
    try {
      if (fs.existsSync(bundlePath)) {
        base = fs.readFileSync(bundlePath, 'utf-8').trim();
      }
    } catch { /* use fallback */ }
  }

  if (!base) {
    base = 'You are a companion. Be genuine, direct, and honest.';
  }

  // Append skill files
  const skills = loadSkillFiles();
  for (const skill of skills) {
    base += `\n\n---\n\n${skill}`;
  }

  // Append agent roster for deferral awareness
  const roster = getAgentRoster(config.AGENT_NAME);
  if (roster.length > 0) {
    const lines = roster.map((a) => {
      const desc = a.description ? ` - ${a.description}` : '';
      return `- **${a.display_name}** (\`${a.name}\`)${desc}`;
    });
    base +=
      '\n\n---\n\n## Other Agents\n\n' +
      'You can hand off to these agents using `defer_to_agent` if the user\'s ' +
      'question is better suited to them:\n\n' +
      lines.join('\n') +
      "\n\nOnly defer when there's a clear reason - another agent's specialty " +
      "matches the question, or the user asks for them by name. Don't defer " +
      'just because another agent exists.';
  }

  return base;
}

// ---------------------------------------------------------------------------
// Assemble context (for SDK fallback / oneshot calls)
// ---------------------------------------------------------------------------

export function assembleContext(
  turnHistory: { role: string; content: string }[],
): { system: string; messages: { role: string; content: string }[] } {
  const systemPrompt = loadSystemPrompt();
  const memoryContext = memory.getContextInjection(getConfig().CONTEXT_SUMMARIES);

  const fullSystem = memoryContext
    ? `${systemPrompt}\n\n---\n\n## Memory\n\n${memoryContext}`
    : systemPrompt;

  const messages = turnHistory.map((turn) => ({
    role: turn.role === 'will' ? 'user' : 'assistant',
    content: turn.content,
  }));

  return { system: fullSystem, messages };
}
