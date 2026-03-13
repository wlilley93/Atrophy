#!/usr/bin/env node
/**
 * Atrophy CLI - text-only conversation mode.
 *
 * Connects to the running HTTP API server (--server mode) and provides
 * a stdin/stdout conversation loop. If no server is running, starts one
 * in-process.
 *
 * Usage:
 *   npx tsx src/cli.ts                    # Interactive text mode
 *   npx tsx src/cli.ts --stream-json      # NDJSON streaming (pipe to Claude)
 *   npx tsx src/cli.ts --port 5001        # Custom port
 *   npx tsx src/cli.ts --token <token>    # Explicit auth token
 */

import * as fs from 'fs';
import * as path from 'path';
import * as readline from 'readline';

const USER_DATA = path.join(process.env.HOME || '/tmp', '.atrophy');
const TOKEN_PATH = path.join(USER_DATA, 'server_token');

// Parse args
const args = process.argv.slice(2);
const portIdx = args.indexOf('--port');
const port = portIdx >= 0 ? parseInt(args[portIdx + 1] || '5000', 10) : 5000;
const tokenIdx = args.indexOf('--token');
let token = tokenIdx >= 0 ? args[tokenIdx + 1] || '' : '';
const streamJson = args.includes('--stream-json');
const baseUrl = `http://127.0.0.1:${port}`;

async function loadToken(): Promise<string> {
  if (token) return token;
  try {
    return fs.readFileSync(TOKEN_PATH, 'utf-8').trim();
  } catch {
    console.error(`  No server token found at ${TOKEN_PATH}`);
    console.error(`  Start the server first: atrophy --server`);
    process.exit(1);
  }
}

async function apiGet(endpoint: string, authToken: string): Promise<unknown> {
  const resp = await fetch(`${baseUrl}${endpoint}`, {
    headers: { Authorization: `Bearer ${authToken}` },
    signal: AbortSignal.timeout(10_000),
  });
  return resp.json();
}

async function apiPost(endpoint: string, body: unknown, authToken: string): Promise<unknown> {
  const resp = await fetch(`${baseUrl}${endpoint}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10_000),
  });
  return resp.json();
}

async function streamChat(message: string, authToken: string): Promise<string> {
  const resp = await fetch(`${baseUrl}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({ message }),
  });

  if (!resp.ok) {
    const err = await resp.json() as { error?: string };
    throw new Error(err?.error || `HTTP ${resp.status}`);
  }

  const reader = resp.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let fullText = '';
  let firstChunk = true;
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const evt = JSON.parse(line.slice(6)) as {
          type: string;
          content?: string;
          name?: string;
          full_text?: string;
          message?: string;
        };

        switch (evt.type) {
          case 'text':
            if (firstChunk) {
              process.stdout.write(`  `);
              firstChunk = false;
            }
            process.stdout.write(evt.content || '');
            break;
          case 'tool':
            if (!firstChunk) process.stdout.write('\n');
            process.stdout.write(`  [tool: ${evt.name}]\n`);
            firstChunk = true;
            break;
          case 'done':
            fullText = evt.full_text || '';
            process.stdout.write('\n');
            break;
          case 'error':
            process.stdout.write(`\n  [Error: ${evt.message}]\n`);
            break;
        }
      } catch { /* malformed SSE line */ }
    }
  }

  return fullText;
}

async function streamChatJson(message: string, authToken: string): Promise<string> {
  const resp = await fetch(`${baseUrl}/chat/stream-json`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({ message }),
  });

  if (!resp.ok) {
    const err = await resp.json() as { error?: string };
    throw new Error(err?.error || `HTTP ${resp.status}`);
  }

  const reader = resp.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let fullText = '';
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim()) continue;
      // In --stream-json mode, pass each NDJSON line through to stdout as-is
      process.stdout.write(line + '\n');
      try {
        const evt = JSON.parse(line) as { type?: string; text?: string };
        if (evt.type === 'result' && evt.text) {
          fullText = evt.text;
        }
      } catch { /* ignore parse errors */ }
    }
  }

  return fullText;
}

async function checkServer(authToken: string): Promise<{ agent: string; display_name: string } | null> {
  try {
    const resp = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(3_000) });
    if (!resp.ok) return null;
    return await resp.json() as { agent: string; display_name: string };
  } catch {
    return null;
  }
}

async function main(): Promise<void> {
  const authToken = await loadToken();

  // Check server
  const health = await checkServer(authToken);
  if (!health) {
    console.error(`  Cannot connect to server at ${baseUrl}`);
    console.error(`  Start it with: atrophy --server`);
    process.exit(1);
  }

  const agentName = health.display_name || health.agent;

  // Get session info
  let sessionInfo: { session_id?: string; cli_session_id?: string } = {};
  try {
    sessionInfo = await apiGet('/session', authToken) as typeof sessionInfo;
  } catch { /* non-critical */ }

  const cliStatus = sessionInfo.cli_session_id ? 'resuming' : 'new';

  // Header
  const title = `ATROPHY - ${agentName}`;
  console.log();
  console.log(`  +${'-'.repeat(38)}+`);
  console.log(`  |   ${title.padEnd(35)}|`);
  console.log(`  |   Text Only${' '.repeat(26)}|`);
  console.log(`  |   CLI: ${cliStatus.padEnd(29)}|`);
  console.log(`  +${'-'.repeat(38)}+`);
  console.log();

  // Readline
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: true,
  });

  const prompt = (): Promise<string | null> => {
    return new Promise((resolve) => {
      rl.question(`  You: `, (answer) => {
        const trimmed = answer.trim();
        resolve(trimmed || null);
      });
    });
  };

  // Main loop
  try {
    while (true) {
      const input = await prompt();
      if (input === null) continue;

      if (!streamJson) process.stdout.write(`  [thinking...]\r`);

      try {
        if (streamJson) {
          await streamChatJson(input, authToken);
        } else {
          await streamChat(input, authToken);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        console.log(`  [Error: ${msg}]`);
      }
      console.log();
    }
  } catch {
    // Ctrl+C / EOF
    console.log('\n  See you.\n');
  } finally {
    rl.close();
  }
}

// Handle Ctrl+C gracefully
process.on('SIGINT', () => {
  console.log('\n  See you.\n');
  process.exit(0);
});

main().catch((e) => {
  console.error(`Error: ${e}`);
  process.exit(1);
});
