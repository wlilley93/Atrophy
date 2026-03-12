/**
 * Telegram message router - routes incoming messages to the right agent(s).
 * Port of channels/router.py.
 *
 * Two-tier routing:
 *   1. Explicit: user names an agent via /prefix, @mention, wake word -> route directly
 *   2. Routing agent: lightweight LLM call classifies the message -> route to best fit
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig, USER_DATA, BUNDLE_ROOT } from './config';
import { discoverAgents, getAgentState } from './agent-manager';
import { runInferenceOneshot } from './inference';
import { createLogger } from './logger';

const log = createLogger('router');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentInfo {
  name: string;
  display_name: string;
  description: string;
  wake_words: string[];
  emoji: string;
}

export interface RoutingDecision {
  agents: string[];
  tier: 'explicit' | 'agent' | 'single' | 'none';
  text: string;
}

// ---------------------------------------------------------------------------
// Agent registry
// ---------------------------------------------------------------------------

function loadAgentRegistry(): AgentInfo[] {
  const registry: AgentInfo[] = [];

  for (const agent of discoverAgents()) {
    const name = agent.name;
    const state = getAgentState(name);
    if (!state.enabled || state.muted) continue;

    // Load full manifest for routing metadata
    let manifest: Record<string, unknown> = {};
    for (const base of [
      path.join(USER_DATA, 'agents', name),
      path.join(BUNDLE_ROOT, 'agents', name),
    ]) {
      const mpath = path.join(base, 'data', 'agent.json');
      if (fs.existsSync(mpath)) {
        try {
          manifest = JSON.parse(fs.readFileSync(mpath, 'utf-8'));
        } catch { /* skip */ }
        break;
      }
    }

    registry.push({
      name,
      display_name: (manifest.display_name as string) || name.charAt(0).toUpperCase() + name.slice(1),
      description: (manifest.description as string) || '',
      wake_words: ((manifest.wake_words as string[]) || []).map((w) => w.toLowerCase()),
      emoji: (manifest.telegram_emoji as string) || '',
    });
  }

  return registry;
}

// ---------------------------------------------------------------------------
// Tier 1: Explicit routing (free, no LLM call)
// ---------------------------------------------------------------------------

function checkExplicit(text: string, agents: AgentInfo[]): string[] | null {
  const lower = text.toLowerCase().trim();

  // /command prefix
  if (lower.startsWith('/')) {
    const cmd = lower.split(/\s/)[0].slice(1);
    for (const a of agents) {
      if (cmd === a.name || cmd === a.display_name.toLowerCase()) {
        return [a.name];
      }
    }
  }

  // @mention
  const mentions = lower.match(/@(\w+)/g);
  if (mentions) {
    const matched: string[] = [];
    for (const raw of mentions) {
      const mention = raw.slice(1);
      for (const a of agents) {
        if (mention === a.name || mention === a.display_name.toLowerCase()) {
          matched.push(a.name);
        }
      }
    }
    if (matched.length) return [...new Set(matched)];
  }

  // Wake words or "name:" prefix
  for (const a of agents) {
    if (lower.startsWith(`${a.name}:`) || lower.startsWith(`${a.display_name.toLowerCase()}:`)) {
      return [a.name];
    }
    for (const ww of a.wake_words) {
      if (lower.startsWith(ww)) return [a.name];
    }
  }

  // Multiple agents named explicitly
  const named: string[] = [];
  for (const a of agents) {
    const nameLower = a.display_name.toLowerCase();
    if (lower.includes(nameLower) || lower.includes(a.name)) {
      named.push(a.name);
    }
  }
  if (named.length >= 2) return [...new Set(named)];

  return null;
}

// ---------------------------------------------------------------------------
// Tier 2: Routing agent (lightweight LLM call)
// ---------------------------------------------------------------------------

async function routeViaAgent(text: string, agents: AgentInfo[]): Promise<string[]> {
  const agentList = agents
    .map((a) => `- **${a.display_name}** (\`${a.name}\`): ${a.description || 'no description'}`)
    .join('\n');

  const validSlugs = agents.map((a) => a.name);

  const system =
    'You are a message routing agent. Your ONLY job is to decide which AI agent(s) ' +
    'should handle an incoming Telegram message.\n\n' +
    'Rules:\n' +
    '- Route to ONE agent unless the message genuinely needs multiple perspectives.\n' +
    '- For casual/general messages, pick the agent whose personality is the best fit.\n' +
    '- Reply with ONLY a JSON array of agent slugs. No explanation.\n' +
    `- Valid slugs: ${JSON.stringify(validSlugs)}`;

  const prompt =
    `Available agents:\n${agentList}\n\n` +
    `Incoming message:\n"${text}"\n\n` +
    `Which agent(s) should respond? Reply with a JSON array.`;

  try {
    const result = await runInferenceOneshot(
      [{ role: 'user', content: prompt }],
      system,
      'claude-haiku-4-5-20251001',
      'low',
    );

    const match = result.match(/\[.*?\]/s);
    if (match) {
      const names = JSON.parse(match[0]) as string[];
      const valid = names.filter((n) => validSlugs.includes(n));
      if (valid.length) {
        log.info(`Routing agent chose: ${valid.join(', ')}`);
        return valid;
      }
    }
  } catch (e) {
    log.error(`Routing agent failed: ${e}`);
  }

  return agents.length ? [agents[0].name] : [];
}

// ---------------------------------------------------------------------------
// Main router
// ---------------------------------------------------------------------------

export async function routeMessage(text: string): Promise<RoutingDecision> {
  const agents = loadAgentRegistry();

  if (!agents.length) {
    return { agents: [], tier: 'none', text };
  }

  if (agents.length === 1) {
    return { agents: [agents[0].name], tier: 'single', text };
  }

  // Tier 1: Explicit
  const explicit = checkExplicit(text, agents);
  if (explicit) {
    let clean = text;
    const lower = text.toLowerCase().trim();
    if (lower.startsWith('/')) {
      clean = text.includes(' ') ? text.split(/\s/, 2)[1] || text : text;
    } else if (text.includes(':') && text.indexOf(':') < 30) {
      clean = text.split(':', 2)[1]?.trim() || text;
    }
    return { agents: explicit, tier: 'explicit', text: clean };
  }

  // Tier 2: Routing agent
  const winners = await routeViaAgent(text, agents);
  return { agents: winners, tier: 'agent', text };
}

// ---------------------------------------------------------------------------
// Routing queue (file-based IPC for daemons)
// ---------------------------------------------------------------------------

const ROUTE_FILE = path.join(USER_DATA, '.telegram_routes.json');

interface RouteEntry {
  message_id: number;
  text: string;
  agents: string[];
  tier: string;
  timestamp: number;
}

export function enqueueRoute(messageId: number, text: string, decision: RoutingDecision): void {
  let routes: RouteEntry[] = [];
  try {
    if (fs.existsSync(ROUTE_FILE)) {
      routes = JSON.parse(fs.readFileSync(ROUTE_FILE, 'utf-8'));
    }
  } catch { /* start fresh */ }

  routes.push({
    message_id: messageId,
    text: decision.text,
    agents: decision.agents,
    tier: decision.tier,
    timestamp: Date.now() / 1000,
  });

  // Keep last 50
  routes = routes.slice(-50);
  fs.writeFileSync(ROUTE_FILE, JSON.stringify(routes, null, 2) + '\n');
}

export function dequeueRoute(agentName: string): RouteEntry | null {
  if (!fs.existsSync(ROUTE_FILE)) return null;

  let routes: RouteEntry[];
  try {
    routes = JSON.parse(fs.readFileSync(ROUTE_FILE, 'utf-8'));
  } catch {
    return null;
  }

  for (let i = 0; i < routes.length; i++) {
    if (routes[i].agents.includes(agentName)) {
      const route = routes[i];
      route.agents = route.agents.filter((a) => a !== agentName);
      if (!route.agents.length) {
        routes.splice(i, 1);
      }
      fs.writeFileSync(ROUTE_FILE, JSON.stringify(routes, null, 2) + '\n');
      return route;
    }
  }

  return null;
}
