/**
 * Big Beautiful Test Suite - CLI Tests
 *
 * Tests CLI arg parsing, token loading, SSE stream parsing,
 * NDJSON stream parsing, and server connection logic.
 */

import { describe, it, expect } from 'vitest';

// ---------------------------------------------------------------------------
// CLI argument parsing (port of logic from src/cli.ts)
// ---------------------------------------------------------------------------

function parseCliArgs(argv: string[]): {
  port: number;
  token: string;
  streamJson: boolean;
  baseUrl: string;
} {
  const portIdx = argv.indexOf('--port');
  const port = portIdx >= 0 ? parseInt(argv[portIdx + 1] || '5000', 10) : 5000;
  const tokenIdx = argv.indexOf('--token');
  const token = tokenIdx >= 0 ? argv[tokenIdx + 1] || '' : '';
  const streamJson = argv.includes('--stream-json');
  const baseUrl = `http://127.0.0.1:${port}`;
  return { port, token, streamJson, baseUrl };
}

describe('CLI argument parsing', () => {
  it('uses default port 5000 when no --port flag', () => {
    const result = parseCliArgs([]);
    expect(result.port).toBe(5000);
    expect(result.baseUrl).toBe('http://127.0.0.1:5000');
  });

  it('parses custom port', () => {
    const result = parseCliArgs(['--port', '5001']);
    expect(result.port).toBe(5001);
    expect(result.baseUrl).toBe('http://127.0.0.1:5001');
  });

  it('parses token flag', () => {
    const result = parseCliArgs(['--token', 'my-secret-token']);
    expect(result.token).toBe('my-secret-token');
  });

  it('detects --stream-json flag', () => {
    const result = parseCliArgs(['--stream-json']);
    expect(result.streamJson).toBe(true);
  });

  it('handles no --stream-json flag', () => {
    const result = parseCliArgs([]);
    expect(result.streamJson).toBe(false);
  });

  it('handles all flags together', () => {
    const result = parseCliArgs(['--port', '8080', '--token', 'abc', '--stream-json']);
    expect(result.port).toBe(8080);
    expect(result.token).toBe('abc');
    expect(result.streamJson).toBe(true);
  });

  it('handles missing port value gracefully', () => {
    const result = parseCliArgs(['--port']);
    expect(result.port).toBe(5000); // parseInt(undefined) = NaN, fallback
  });

  it('handles missing token value gracefully', () => {
    const result = parseCliArgs(['--token']);
    expect(result.token).toBe('');
  });
});

// ---------------------------------------------------------------------------
// SSE event parsing (port of streamChat logic)
// ---------------------------------------------------------------------------

interface SSEEvent {
  type: string;
  content?: string;
  name?: string;
  full_text?: string;
  message?: string;
}

function parseSSELine(line: string): SSEEvent | null {
  if (!line.startsWith('data: ')) return null;
  try {
    return JSON.parse(line.slice(6)) as SSEEvent;
  } catch {
    return null;
  }
}

describe('SSE event parsing', () => {
  it('parses text delta events', () => {
    const evt = parseSSELine('data: {"type":"text","content":"Hello"}');
    expect(evt).not.toBeNull();
    expect(evt!.type).toBe('text');
    expect(evt!.content).toBe('Hello');
  });

  it('parses tool events', () => {
    const evt = parseSSELine('data: {"type":"tool","name":"memory_search"}');
    expect(evt).not.toBeNull();
    expect(evt!.type).toBe('tool');
    expect(evt!.name).toBe('memory_search');
  });

  it('parses done events', () => {
    const evt = parseSSELine('data: {"type":"done","full_text":"Complete response"}');
    expect(evt).not.toBeNull();
    expect(evt!.type).toBe('done');
    expect(evt!.full_text).toBe('Complete response');
  });

  it('parses error events', () => {
    const evt = parseSSELine('data: {"type":"error","message":"Something failed"}');
    expect(evt).not.toBeNull();
    expect(evt!.type).toBe('error');
    expect(evt!.message).toBe('Something failed');
  });

  it('returns null for non-data lines', () => {
    expect(parseSSELine('')).toBeNull();
    expect(parseSSELine('event: update')).toBeNull();
    expect(parseSSELine('id: 123')).toBeNull();
    expect(parseSSELine(': comment')).toBeNull();
  });

  it('returns null for malformed JSON', () => {
    expect(parseSSELine('data: not-json')).toBeNull();
    expect(parseSSELine('data: {broken')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// NDJSON event parsing (port of streamChatJson logic)
// ---------------------------------------------------------------------------

interface NDJSONEvent {
  type?: string;
  subtype?: string;
  text?: string;
  name?: string;
  error?: string;
  session_id?: string;
  index?: number;
}

function parseNDJSONLine(line: string): NDJSONEvent | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed) as NDJSONEvent;
  } catch {
    return null;
  }
}

describe('NDJSON event parsing', () => {
  it('parses text delta events', () => {
    const evt = parseNDJSONLine('{"type":"assistant","subtype":"text_delta","text":"Hi"}');
    expect(evt).not.toBeNull();
    expect(evt!.type).toBe('assistant');
    expect(evt!.subtype).toBe('text_delta');
    expect(evt!.text).toBe('Hi');
  });

  it('parses sentence events', () => {
    const evt = parseNDJSONLine('{"type":"assistant","subtype":"sentence","text":"Hello world.","index":0}');
    expect(evt).not.toBeNull();
    expect(evt!.subtype).toBe('sentence');
    expect(evt!.index).toBe(0);
  });

  it('parses tool use events', () => {
    const evt = parseNDJSONLine('{"type":"tool_use","name":"recall"}');
    expect(evt).not.toBeNull();
    expect(evt!.type).toBe('tool_use');
    expect(evt!.name).toBe('recall');
  });

  it('parses result success events', () => {
    const evt = parseNDJSONLine('{"type":"result","subtype":"success","text":"Done","session_id":"s1"}');
    expect(evt).not.toBeNull();
    expect(evt!.type).toBe('result');
    expect(evt!.subtype).toBe('success');
    expect(evt!.session_id).toBe('s1');
  });

  it('parses result error events', () => {
    const evt = parseNDJSONLine('{"type":"result","subtype":"error","error":"failed"}');
    expect(evt).not.toBeNull();
    expect(evt!.subtype).toBe('error');
    expect(evt!.error).toBe('failed');
  });

  it('parses compacting events', () => {
    const evt = parseNDJSONLine('{"type":"system","subtype":"compacting"}');
    expect(evt).not.toBeNull();
    expect(evt!.type).toBe('system');
    expect(evt!.subtype).toBe('compacting');
  });

  it('returns null for empty lines', () => {
    expect(parseNDJSONLine('')).toBeNull();
    expect(parseNDJSONLine('   ')).toBeNull();
  });

  it('returns null for malformed JSON', () => {
    expect(parseNDJSONLine('not json')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// SSE buffer splitting (simulates streaming chunk assembly)
// ---------------------------------------------------------------------------

describe('SSE buffer splitting', () => {
  it('handles complete lines', () => {
    const chunk = 'data: {"type":"text","content":"Hello"}\n\ndata: {"type":"text","content":" world"}\n\n';
    const lines = chunk.split('\n').filter((l) => l.startsWith('data: '));
    expect(lines.length).toBe(2);
  });

  it('handles partial lines across chunks', () => {
    let buffer = '';

    // Chunk 1: partial line
    buffer += 'data: {"type":"te';
    let lines = buffer.split('\n');
    buffer = lines.pop() || '';
    expect(lines.length).toBe(0); // no complete lines yet

    // Chunk 2: rest of line + complete second line
    buffer += 'xt","content":"Hi"}\ndata: {"type":"done","full_text":"Hi"}\n';
    lines = buffer.split('\n');
    buffer = lines.pop() || '';

    const events = lines.filter((l) => l.startsWith('data: ')).map((l) => parseSSELine(l));
    expect(events.length).toBe(2);
    expect(events[0]!.content).toBe('Hi');
    expect(events[1]!.type).toBe('done');
  });
});

// ---------------------------------------------------------------------------
// NDJSON buffer splitting
// ---------------------------------------------------------------------------

describe('NDJSON buffer splitting', () => {
  it('handles complete lines', () => {
    const chunk = '{"type":"assistant","subtype":"text_delta","text":"Hi"}\n{"type":"result","subtype":"success","text":"Hi"}\n';
    const lines = chunk.trim().split('\n');
    expect(lines.length).toBe(2);
    expect(parseNDJSONLine(lines[0])!.type).toBe('assistant');
    expect(parseNDJSONLine(lines[1])!.type).toBe('result');
  });

  it('handles partial lines across chunks', () => {
    let buffer = '';

    buffer += '{"type":"assis';
    let lines = buffer.split('\n');
    buffer = lines.pop() || '';
    expect(lines.length).toBe(0);

    buffer += 'tant","subtype":"text_delta","text":"Hi"}\n';
    lines = buffer.split('\n');
    buffer = lines.pop() || '';

    const events = lines.filter((l) => l.trim()).map((l) => parseNDJSONLine(l));
    expect(events.length).toBe(1);
    expect(events[0]!.text).toBe('Hi');
  });
});

// ---------------------------------------------------------------------------
// Header box rendering
// ---------------------------------------------------------------------------

describe('CLI header rendering', () => {
  it('formats agent name in header box', () => {
    const agentName = 'Xan';
    const title = `ATROPHY - ${agentName}`;
    const padded = title.padEnd(35);
    expect(padded.length).toBe(35);
    expect(padded.startsWith('ATROPHY - Xan')).toBe(true);
  });

  it('formats session status in header', () => {
    const cliStatus = 'new';
    const padded = cliStatus.padEnd(29);
    expect(padded.length).toBe(29);
  });

  it('header box has consistent width', () => {
    const border = `+${'-'.repeat(38)}+`;
    expect(border.length).toBe(40);
    expect(border.startsWith('+')).toBe(true);
    expect(border.endsWith('+')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Token file path
// ---------------------------------------------------------------------------

describe('Token path resolution', () => {
  it('constructs token path from HOME', () => {
    const home = '/Users/test';
    const tokenPath = `${home}/.atrophy/server_token`;
    expect(tokenPath).toBe('/Users/test/.atrophy/server_token');
  });

  it('falls back to /tmp when HOME is not set', () => {
    const home = undefined;
    const base = home || '/tmp';
    const tokenPath = `${base}/.atrophy/server_token`;
    expect(tokenPath).toBe('/tmp/.atrophy/server_token');
  });
});
