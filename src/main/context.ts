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
import { getConfig, BUNDLE_ROOT, USER_DATA } from './config';
import { loadPrompt } from './prompts';
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

  const userAgents = path.join(USER_DATA, 'agents');
  const bundleAgents = path.join(BUNDLE_ROOT, 'agents');

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

        // Skip tier 2+ agents (headless workers not addressable by other principals)
        const orgSection = data.org as Record<string, unknown> | undefined;
        if (orgSection?.tier && (orgSection.tier as number) > 1) continue;

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

  // Fallback to bundle system_prompt.md (check both AGENT_DIR and BUNDLE_ROOT)
  if (!base) {
    const candidates = [
      path.join(config.AGENT_DIR, 'prompts', 'system_prompt.md'),
      path.join(BUNDLE_ROOT, 'agents', config.AGENT_NAME, 'prompts', 'system_prompt.md'),
    ];
    for (const bundlePath of candidates) {
      try {
        if (fs.existsSync(bundlePath)) {
          base = fs.readFileSync(bundlePath, 'utf-8').trim();
          break;
        }
      } catch { /* use fallback */ }
    }
  }

  if (!base) {
    base = 'You are a companion. Be genuine, direct, and honest.';
  }

  // Lazy-load instruction for skill files (no longer appended in full)
  base += '\n\n---\n\n## Skills\n\nYou have skill files with specialized behavioral guidance. ' +
    'Use read_note to access them when a situation calls for it. ' +
    'They cover: tools usage, introspection protocols, gifts, and morning briefings.';

  // System reference - agents know about the switchboard and their wiring
  base += '\n\n---\n\n## System Reference\n\n' +
    'You are running inside Atrophy, a companion agent system. ' +
    'All messages flow through a central switchboard as Envelopes with from/to addresses. ' +
    'Your channels, MCP servers, and scheduled jobs are defined in your agent manifest at ' +
    '~/.atrophy/agents/' + config.AGENT_NAME + '/data/agent.json.\n\n' +
    'Available switchboard tools: send_message, broadcast, query_status. ' +
    'Available MCP tools: mcp_list_servers, mcp_activate_server, mcp_deactivate_server, mcp_scaffold_server.\n\n' +
    'For the full system reference, read the file at: ' +
    path.join(BUNDLE_ROOT, 'docs', 'agent-reference.md');

  // Org owner guidelines - injected for agents that can provision
  const manifestPath = path.join(USER_DATA, 'agents', config.AGENT_NAME, 'data', 'agent.json');
  try {
    if (fs.existsSync(manifestPath)) {
      const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
      const org = manifest.org as Record<string, unknown> | undefined;
      if (org?.can_provision) {
        base += '\n\n---\n\n## Script Creation Guidelines\n\n' +
          'When creating Python scripts for your organisation:\n\n' +
          '1. **Start from the template:** Copy `scripts/agents/shared/template.py`\n' +
          '2. **Credentials:** Use `from shared.credentials import load_telegram_credentials` - NEVER read agent.json directly for tokens\n' +
          '3. **Telegram:** Use `from shared.telegram_utils import send_telegram` - NEVER write your own HTTP sender\n' +
          '4. **Claude calls:** Use `from shared.claude_cli import call_claude` - NEVER write your own subprocess wrapper\n' +
          '5. **Paths:** Use `Path(__file__).resolve().parent` chains - NEVER hardcode absolute paths\n' +
          '6. **Jobs:** After creating a script, register it in your agent manifest under `jobs` - unregistered scripts never run\n' +
          '7. **Imports:** Include ALL stdlib imports your script uses (sqlite3, shutil, subprocess, etc.)\n\n' +
          'Available shared utilities in `scripts/agents/shared/`:\n' +
          '- `credentials.py` - load_telegram_credentials(agent_name)\n' +
          '- `telegram_utils.py` - send_telegram(token, chat_id, text), send_voice_note()\n' +
          '- `claude_cli.py` - call_claude(system, prompt, model)\n' +
          '- `template.py` - correct boilerplate for new scripts';
      }
    }
  } catch { /* non-critical */ }

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

  // Append inline artifact emission instructions
  base +=
    '\n\n---\n\n## Inline Artifacts\n\n' +
    'When you create standalone content (HTML pages, interactive widgets, SVG graphics, ' +
    'code snippets, or visualisations), emit it inline using this format:\n\n' +
    '```\n' +
    '<artifact id="unique-id" type="html|svg|code" title="Human-readable title" language="html">\n' +
    'CONTENT HERE\n' +
    '</artifact>\n' +
    '```\n\n' +
    'Rules:\n' +
    '- `id` must be unique within the conversation (use descriptive slugs like `solar-system-viz`)\n' +
    '- `type` is one of: `html` (full pages, interactive widgets), `svg` (vector graphics), `code` (source code)\n' +
    '- `language` is the content language (html, svg, python, typescript, etc.)\n' +
    '- For `html` type, include complete self-contained HTML with inline CSS/JS\n' +
    '- The artifact will appear as a clickable card in the transcript that opens in a full-screen viewer\n' +
    '- Use artifacts for anything visual, interactive, or that benefits from being rendered rather than shown as text\n' +
    '- You can emit multiple artifacts in a single response\n' +
    '- If iterating on the same artifact, reuse the same `id` to replace the previous version';

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
