/**
 * Telegram polling daemon - single process, sequential agent dispatch.
 * Port of channels/telegram_daemon.py.
 *
 * Polls the shared Telegram bot for incoming messages. Routes each message
 * via the router (explicit match -> routing agent), then dispatches to target
 * agent(s) one at a time. Sequential dispatch eliminates race conditions.
 *
 * Can run as:
 *   - Single poll (for launchd interval jobs)
 *   - Continuous loop (KeepAlive daemon)
 *   - Managed from within the Electron main process
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig, USER_DATA, BUNDLE_ROOT } from './config';
import { sendMessage, _post, setLastUpdateId } from './telegram';
import { routeMessage, RoutingDecision } from './router';
import { discoverAgents, getAgentState, setAgentState } from './agent-manager';
import { streamInference, InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import * as memory from './memory';

// ---------------------------------------------------------------------------
// State persistence
// ---------------------------------------------------------------------------

const STATE_FILE = path.join(USER_DATA, '.telegram_daemon_state.json');

function loadLastUpdateId(): number {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
      return state.last_update_id || 0;
    }
  } catch { /* default */ }
  return 0;
}

function saveLastUpdateId(updateId: number): void {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify({ last_update_id: updateId }) + '\n');
}

// ---------------------------------------------------------------------------
// Agent dispatch
// ---------------------------------------------------------------------------

async function dispatchToAgent(agentName: string, text: string): Promise<string | null> {
  try {
    // Temporarily switch config for this agent
    const config = getConfig();
    const originalAgent = config.AGENT_NAME;
    config.reloadForAgent(agentName);
    memory.initDb();

    const system = loadSystemPrompt();
    const cliSessionId = memory.getLastCliSessionId();

    const prompt = `[Telegram message from Will]\n\n${text}`;
    let fullText = '';
    const toolsUsed: string[] = [];

    await new Promise<void>((resolve) => {
      const emitter = streamInference(prompt, system, cliSessionId);

      emitter.on('event', (evt: InferenceEvent) => {
        switch (evt.type) {
          case 'ToolUse':
            toolsUsed.push(evt.name);
            console.log(`  [${agentName}] tool -> ${evt.name}`);
            break;
          case 'StreamDone':
            fullText = evt.fullText;
            resolve();
            break;
          case 'StreamError':
            console.log(`  [${agentName}] inference error: ${evt.message}`);
            resolve();
            break;
        }
      });
    });

    if (toolsUsed.length) {
      console.log(`  [${agentName}] used tools: ${toolsUsed.join(', ')}`);
    }

    // Restore original agent
    config.reloadForAgent(originalAgent);
    memory.initDb();

    return fullText.trim() || null;
  } catch (e) {
    console.log(`  [${agentName}] dispatch failed: ${e}`);
    return null;
  }
}

function sendAgentResponse(agentName: string, text: string): void {
  // Load agent manifest for emoji prefix
  for (const base of [
    path.join(USER_DATA, 'agents', agentName),
    path.join(BUNDLE_ROOT, 'agents', agentName),
  ]) {
    const mpath = path.join(base, 'data', 'agent.json');
    if (fs.existsSync(mpath)) {
      try {
        const manifest = JSON.parse(fs.readFileSync(mpath, 'utf-8'));
        const emoji = manifest.telegram_emoji || '';
        const display = manifest.display_name || agentName.charAt(0).toUpperCase() + agentName.slice(1);
        if (emoji) {
          text = `${emoji} *${display}*\n\n${text}`;
        }
        break;
      } catch { /* use plain text */ }
    }
  }

  sendMessage(text, '', false);
}

// ---------------------------------------------------------------------------
// Utility commands
// ---------------------------------------------------------------------------

function handleStatusCommand(): void {
  const lines = ['*Active agents:*\n'];

  for (const agent of discoverAgents()) {
    const name = agent.name;
    const state = getAgentState(name);

    // Load emoji from manifest
    let emoji = '';
    for (const base of [
      path.join(USER_DATA, 'agents', name),
      path.join(BUNDLE_ROOT, 'agents', name),
    ]) {
      const mpath = path.join(base, 'data', 'agent.json');
      if (fs.existsSync(mpath)) {
        try {
          const manifest = JSON.parse(fs.readFileSync(mpath, 'utf-8'));
          emoji = manifest.telegram_emoji || '';
        } catch { /* skip */ }
        break;
      }
    }

    let status = 'active';
    if (!state.enabled) status = 'disabled';
    else if (state.muted) status = 'muted';

    const prefix = emoji ? `${emoji} ` : '';
    lines.push(`${prefix}*${agent.display_name}* (\`/${name}\`) - ${status}`);
  }

  sendMessage(lines.join('\n'), '', false);
}

function handleMuteCommand(text: string): void {
  const parts = text.trim().split(/\s+/);
  const agents = discoverAgents();

  let targetName: string;
  if (parts.length < 2) {
    if (!agents.length) {
      sendMessage('No agents available.', '', false);
      return;
    }
    targetName = agents[0].name;
  } else {
    targetName = parts[1].toLowerCase().replace(/^\//, '');
  }

  const found = agents.find(
    (a) => a.name === targetName || a.display_name.toLowerCase() === targetName,
  );
  if (!found) {
    sendMessage(`Unknown agent: \`${targetName}\``, '', false);
    return;
  }

  const state = getAgentState(found.name);
  const newMuted = !state.muted;
  setAgentState(found.name, { muted: newMuted });

  const verb = newMuted ? 'muted' : 'unmuted';
  sendMessage(`*${found.display_name}* ${verb}.`, '', false);
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

let _lastUpdateId = 0;

async function pollOnce(): Promise<void> {
  const config = getConfig();
  if (!config.TELEGRAM_BOT_TOKEN) {
    console.log('[telegram-daemon] TELEGRAM_BOT_TOKEN not configured');
    return;
  }

  const result = await _post('getUpdates', {
    offset: _lastUpdateId + 1,
    timeout: 30,
    allowed_updates: ['message'],
  }) as { update_id: number; message?: {
    text?: string;
    from?: { id: number };
    chat?: { id: number };
  } }[] | null;

  if (!result) return;

  for (const update of result) {
    _lastUpdateId = Math.max(_lastUpdateId, update.update_id);

    const msg = update.message;
    if (!msg?.text) continue;

    const senderId = String(msg.from?.id || '');
    const chatId = String(msg.chat?.id || '');
    if (config.TELEGRAM_CHAT_ID && senderId !== config.TELEGRAM_CHAT_ID && chatId !== config.TELEGRAM_CHAT_ID) {
      continue;
    }

    const text = msg.text.trim();
    if (!text) continue;

    console.log(`[telegram-daemon] Received: ${text.slice(0, 80)}`);

    // Utility commands
    if (text.toLowerCase() === '/status') {
      handleStatusCommand();
      continue;
    }
    if (text.toLowerCase().startsWith('/mute')) {
      handleMuteCommand(text);
      continue;
    }

    // Route the message
    const decision = await routeMessage(text);
    console.log(`[telegram-daemon] Routed: agents=${decision.agents.join(',')} tier=${decision.tier}`);

    if (!decision.agents.length) {
      console.log('[telegram-daemon] No agents available to handle message');
      continue;
    }

    // Dispatch to each agent sequentially
    for (const agentName of decision.agents) {
      console.log(`[telegram-daemon] Dispatching to ${agentName}...`);
      const response = await dispatchToAgent(agentName, decision.text);
      if (response) {
        sendAgentResponse(agentName, response);
        console.log(`  [${agentName}] responded (${response.length} chars)`);
      } else {
        console.log(`  [${agentName}] no response`);
      }
    }
  }

  saveLastUpdateId(_lastUpdateId);
}

// ---------------------------------------------------------------------------
// Daemon control
// ---------------------------------------------------------------------------

let _pollTimer: ReturnType<typeof setInterval> | null = null;
let _running = false;

export function startDaemon(intervalMs = 10_000): void {
  if (_running) return;
  _running = true;
  _lastUpdateId = loadLastUpdateId();
  setLastUpdateId(_lastUpdateId);

  console.log(`[telegram-daemon] Starting (last_update_id=${_lastUpdateId}, interval=${intervalMs}ms)`);

  // Initial poll
  pollOnce().catch((e) => console.log(`[telegram-daemon] Poll error: ${e}`));

  // Recurring polls
  _pollTimer = setInterval(() => {
    pollOnce().catch((e) => console.log(`[telegram-daemon] Poll error: ${e}`));
  }, intervalMs);
}

export function stopDaemon(): void {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
  _running = false;
  console.log('[telegram-daemon] Stopped');
}

export function isDaemonRunning(): boolean {
  return _running;
}
