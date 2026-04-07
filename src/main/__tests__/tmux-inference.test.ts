/**
 * Tests for tmux-inference.ts
 *
 * Tests JSONL parsing, event mapping, byte-offset file reading, and TmuxPool
 * construction. Uses real filesystem (tmpdir) for readNewEntries tests.
 * Mocks child_process.execFileSync for TmuxPool tests.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

// Mock electron before importing anything that might transitively import config.ts
vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (name: string) => `/tmp/atrophy-test/${name}`,
    getName: () => 'atrophy-test',
    getVersion: () => '0.0.0-test',
  },
  ipcMain: { handle: vi.fn(), on: vi.fn() },
  BrowserWindow: class {},
}));

import {
  parseJsonlEntry,
  splitSentences,
  mapToEvents,
  readNewEntries,
  TmuxPool,
} from '../tmux-inference';

// ---------------------------------------------------------------------------
// parseJsonlEntry
// ---------------------------------------------------------------------------

describe('parseJsonlEntry', () => {
  it('parses valid JSON object', () => {
    const result = parseJsonlEntry('{"type":"assistant","message":{}}');
    expect(result).toEqual({ type: 'assistant', message: {} });
  });

  it('returns null for empty string', () => {
    expect(parseJsonlEntry('')).toBeNull();
  });

  it('returns null for whitespace-only string', () => {
    expect(parseJsonlEntry('   \t  ')).toBeNull();
  });

  it('returns null for invalid JSON', () => {
    expect(parseJsonlEntry('{broken json')).toBeNull();
  });

  it('returns null for JSON array', () => {
    expect(parseJsonlEntry('[1, 2, 3]')).toBeNull();
  });

  it('returns null for JSON primitive', () => {
    expect(parseJsonlEntry('"hello"')).toBeNull();
    expect(parseJsonlEntry('42')).toBeNull();
    expect(parseJsonlEntry('true')).toBeNull();
  });

  it('handles JSON with whitespace padding', () => {
    const result = parseJsonlEntry('  {"type":"user"}  ');
    expect(result).toEqual({ type: 'user' });
  });
});

// ---------------------------------------------------------------------------
// splitSentences
// ---------------------------------------------------------------------------

describe('splitSentences', () => {
  it('splits on sentence boundaries', () => {
    const result = splitSentences('Hello world. How are you? I am fine!');
    expect(result).toEqual(['Hello world.', 'How are you?', 'I am fine!']);
  });

  it('returns single sentence without boundary', () => {
    const result = splitSentences('Hello world');
    expect(result).toEqual(['Hello world']);
  });

  it('handles empty string', () => {
    const result = splitSentences('');
    expect(result).toEqual([]);
  });

  it('handles trailing punctuation', () => {
    const result = splitSentences('Done.');
    expect(result).toEqual(['Done.']);
  });

  it('applies clause splitting for long segments', () => {
    // Build a string > 120 chars with a comma
    const longSegment = 'A'.repeat(80) + ', ' + 'B'.repeat(50);
    const result = splitSentences(longSegment);
    // Should split at the comma since segment > 120 chars
    expect(result.length).toBe(2);
    expect(result[0]).toContain('A'.repeat(80) + ',');
    expect(result[1]).toContain('B'.repeat(50));
  });

  it('does not clause-split short segments', () => {
    const result = splitSentences('Hello, world');
    expect(result).toEqual(['Hello, world']);
  });
});

// ---------------------------------------------------------------------------
// mapToEvents
// ---------------------------------------------------------------------------

describe('mapToEvents', () => {
  it('ignores non-assistant entries', () => {
    const entry = { type: 'user', message: { content: [{ type: 'text', text: 'hello' }] } };
    expect(mapToEvents(entry, '')).toEqual([]);
  });

  it('ignores entries without message', () => {
    const entry = { type: 'assistant' };
    expect(mapToEvents(entry, '')).toEqual([]);
  });

  it('ignores entries without content array', () => {
    const entry = { type: 'assistant', message: { content: 'not an array' } };
    expect(mapToEvents(entry, '')).toEqual([]);
  });

  it('emits TextDelta for text content', () => {
    const entry = {
      type: 'assistant',
      message: {
        content: [{ type: 'text', text: 'Hello world' }],
      },
    };
    const events = mapToEvents(entry, '');
    expect(events).toEqual([{ type: 'TextDelta', text: 'Hello world' }]);
  });

  it('computes text delta from previousText', () => {
    const entry = {
      type: 'assistant',
      message: {
        content: [{ type: 'text', text: 'Hello world, how are you?' }],
      },
    };
    const events = mapToEvents(entry, 'Hello world');
    expect(events[0]).toEqual({ type: 'TextDelta', text: ', how are you?' });
  });

  it('emits no TextDelta when text unchanged', () => {
    const entry = {
      type: 'assistant',
      message: {
        content: [{ type: 'text', text: 'Hello' }],
      },
    };
    const events = mapToEvents(entry, 'Hello');
    expect(events.filter(e => e.type === 'TextDelta')).toEqual([]);
  });

  it('emits ToolUse for tool_use blocks', () => {
    const entry = {
      type: 'assistant',
      message: {
        content: [
          { type: 'tool_use', name: 'Bash', id: 'tool_123', input: { command: 'ls' } },
        ],
      },
    };
    const events = mapToEvents(entry, '');
    expect(events).toEqual([{
      type: 'ToolUse',
      name: 'Bash',
      toolId: 'tool_123',
      inputJson: '{"command":"ls"}',
    }]);
  });

  it('skips thinking blocks', () => {
    const entry = {
      type: 'assistant',
      message: {
        content: [
          { type: 'thinking', thinking: 'Let me think...' },
          { type: 'text', text: 'The answer is 42.' },
        ],
      },
    };
    const events = mapToEvents(entry, '');
    expect(events).toEqual([{ type: 'TextDelta', text: 'The answer is 42.' }]);
  });

  it('emits SentenceReady and StreamDone on end_turn', () => {
    const entry = {
      type: 'assistant',
      message: {
        content: [{ type: 'text', text: 'Hello. World.' }],
        stop_reason: 'end_turn',
      },
    };
    const events = mapToEvents(entry, '');
    const types = events.map(e => e.type);
    expect(types).toContain('TextDelta');
    expect(types).toContain('SentenceReady');
    expect(types).toContain('StreamDone');

    const sentences = events.filter(e => e.type === 'SentenceReady');
    expect(sentences).toEqual([
      { type: 'SentenceReady', sentence: 'Hello.', index: 0 },
      { type: 'SentenceReady', sentence: 'World.', index: 1 },
    ]);

    const done = events.find(e => e.type === 'StreamDone');
    expect(done).toEqual({
      type: 'StreamDone',
      fullText: 'Hello. World.',
      sessionId: '',
    });
  });

  it('handles mixed text and tool_use content', () => {
    const entry = {
      type: 'assistant',
      message: {
        content: [
          { type: 'text', text: 'Let me check.' },
          { type: 'tool_use', name: 'Read', id: 'tool_456', input: { path: '/tmp' } },
        ],
      },
    };
    const events = mapToEvents(entry, '');
    expect(events[0]).toEqual({ type: 'TextDelta', text: 'Let me check.' });
    expect(events[1]).toEqual({
      type: 'ToolUse',
      name: 'Read',
      toolId: 'tool_456',
      inputJson: '{"path":"/tmp"}',
    });
  });
});

// ---------------------------------------------------------------------------
// readNewEntries - uses real filesystem
// ---------------------------------------------------------------------------

describe('readNewEntries', () => {
  let tmpDir: string;
  let testFile: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'tmux-test-'));
    testFile = path.join(tmpDir, 'test.jsonl');
  });

  afterEach(() => {
    try { fs.rmSync(tmpDir, { recursive: true }); } catch { /* ok */ }
  });

  it('reads entries from the beginning', () => {
    fs.writeFileSync(testFile, '{"type":"user"}\n{"type":"assistant","message":{}}\n');
    const result = readNewEntries(testFile, 0);
    expect(result.entries).toHaveLength(2);
    expect(result.entries[0]).toEqual({ type: 'user' });
    expect(result.entries[1]).toEqual({ type: 'assistant', message: {} });
    expect(result.newOffset).toBeGreaterThan(0);
  });

  it('reads from a byte offset', () => {
    const line1 = '{"type":"user"}\n';
    const line2 = '{"type":"assistant","message":{}}\n';
    fs.writeFileSync(testFile, line1 + line2);

    const offset = Buffer.byteLength(line1, 'utf-8');
    const result = readNewEntries(testFile, offset);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]).toEqual({ type: 'assistant', message: {} });
  });

  it('handles truncated file (offset > file size)', () => {
    fs.writeFileSync(testFile, '{"type":"user"}\n');
    const result = readNewEntries(testFile, 99999);
    // Should reset to 0 and read everything
    expect(result.entries).toHaveLength(1);
    expect(result.newOffset).toBeLessThan(99999);
  });

  it('skips partial lines at end of file', () => {
    // Write a complete line followed by incomplete JSON
    fs.writeFileSync(testFile, '{"type":"user"}\n{"type":"ass');
    const result = readNewEntries(testFile, 0);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]).toEqual({ type: 'user' });
    // Offset should only advance past the first complete line
    expect(result.newOffset).toBe(Buffer.byteLength('{"type":"user"}\n', 'utf-8'));
  });

  it('returns empty for non-existent file', () => {
    const result = readNewEntries('/tmp/nonexistent-file.jsonl', 0);
    expect(result.entries).toEqual([]);
    expect(result.newOffset).toBe(0);
  });

  it('returns empty when nothing new to read', () => {
    const content = '{"type":"user"}\n';
    fs.writeFileSync(testFile, content);
    const offset = Buffer.byteLength(content, 'utf-8');
    const result = readNewEntries(testFile, offset);
    expect(result.entries).toEqual([]);
    expect(result.newOffset).toBe(offset);
  });

  it('tracks offset correctly across multiple reads', () => {
    // First write
    const line1 = '{"type":"user"}\n';
    fs.writeFileSync(testFile, line1);

    const r1 = readNewEntries(testFile, 0);
    expect(r1.entries).toHaveLength(1);

    // Append more data
    const line2 = '{"type":"assistant","message":{}}\n';
    fs.appendFileSync(testFile, line2);

    const r2 = readNewEntries(testFile, r1.newOffset);
    expect(r2.entries).toHaveLength(1);
    expect(r2.entries[0]).toEqual({ type: 'assistant', message: {} });
    expect(r2.newOffset).toBeGreaterThan(r1.newOffset);
  });
});

// ---------------------------------------------------------------------------
// TmuxPool - mocked child_process
// ---------------------------------------------------------------------------

// Note: We use execFileSync (safe, no shell injection) not exec().
// The mock is for testing only - production code uses execFileSync throughout.
vi.mock('child_process', () => ({
  execFileSync: vi.fn(() => ''),
}));

import { execFileSync } from 'child_process';
const mockExecFileSync = vi.mocked(execFileSync);

describe('TmuxPool', () => {
  beforeEach(() => {
    mockExecFileSync.mockReset();
    mockExecFileSync.mockReturnValue('');
  });

  it('constructs with default session name', () => {
    const pool = new TmuxPool();
    expect(pool.agentNames()).toEqual([]);
  });

  it('constructs with custom session name', () => {
    const pool = new TmuxPool('custom');
    expect(pool.agentNames()).toEqual([]);
  });

  describe('isAvailable', () => {
    it('returns true when tmux is found', () => {
      mockExecFileSync.mockReturnValue('/opt/homebrew/bin/tmux');
      expect(TmuxPool.isAvailable()).toBe(true);
      expect(mockExecFileSync).toHaveBeenCalledWith('which', ['tmux'], expect.any(Object));
    });

    it('returns false when tmux is not found', () => {
      mockExecFileSync.mockImplementation(() => {
        throw new Error('not found');
      });
      expect(TmuxPool.isAvailable()).toBe(false);
    });
  });

  describe('ensureSession', () => {
    it('does not create session if it already exists', () => {
      mockExecFileSync.mockReturnValue('');
      const pool = new TmuxPool('test');
      pool.ensureSession();
      // has-session should be called, but new-session should NOT
      expect(mockExecFileSync).toHaveBeenCalledWith(
        'tmux', ['has-session', '-t', 'test'], expect.any(Object),
      );
      expect(mockExecFileSync).not.toHaveBeenCalledWith(
        'tmux', expect.arrayContaining(['new-session']), expect.any(Object),
      );
    });

    it('creates session when has-session fails', () => {
      mockExecFileSync.mockImplementation((_cmd: unknown, args: unknown) => {
        if (Array.isArray(args) && args[0] === 'has-session') {
          throw new Error('session not found');
        }
        return '';
      });
      const pool = new TmuxPool('test');
      pool.ensureSession();
      expect(mockExecFileSync).toHaveBeenCalledWith(
        'tmux', expect.arrayContaining(['new-session', '-d', '-s', 'test']), expect.any(Object),
      );
    });
  });

  describe('createWindow', () => {
    it('creates window and initializes agent state', () => {
      const pool = new TmuxPool('test');
      pool.createWindow('xan', {
        sessionId: 'sess-123',
        claudeBin: '/usr/local/bin/claude',
        mcpConfigPath: '/tmp/mcp.json',
      });

      expect(pool.agentNames()).toEqual(['xan']);
      const state = pool.get('xan');
      expect(state).toBeDefined();
      expect(state!.agentName).toBe('xan');
      expect(state!.sessionId).toBe('sess-123');
      expect(state!.busy).toBe(false);
      expect(state!.queue).toEqual([]);

      // Should have called new-window and send-keys
      expect(mockExecFileSync).toHaveBeenCalledWith(
        'tmux', ['new-window', '-t', 'test', '-n', 'xan'], expect.any(Object),
      );
      expect(mockExecFileSync).toHaveBeenCalledWith(
        'tmux', expect.arrayContaining(['send-keys', '-t', 'test:xan']), expect.any(Object),
      );
    });
  });

  describe('send', () => {
    it('returns error emitter for unknown agent', () => {
      const pool = new TmuxPool('test');
      const emitter = pool.send('unknown', 'hello', 'test');

      return new Promise<void>((resolve) => {
        emitter.on('error', (err) => {
          expect(err.message).toContain('not found');
          resolve();
        });
      });
    });

    it('queues messages when agent is busy', () => {
      const pool = new TmuxPool('test');
      pool.createWindow('xan', {
        sessionId: 'sess-123',
        claudeBin: 'claude',
        mcpConfigPath: '/tmp/mcp.json',
      });

      // First send - makes agent busy
      pool.send('xan', 'first', 'test');
      const state = pool.get('xan')!;
      expect(state.busy).toBe(true);

      // Second send - should queue
      pool.send('xan', 'second', 'test');
      expect(state.queue).toHaveLength(1);
      expect(state.queue[0].text).toBe('second');
    });
  });

  describe('cancel', () => {
    it('cancels current inference and clears queue', () => {
      const pool = new TmuxPool('test');
      pool.createWindow('xan', {
        sessionId: 'sess-123',
        claudeBin: 'claude',
        mcpConfigPath: '/tmp/mcp.json',
      });

      const emitter1 = pool.send('xan', 'first', 'test');
      const emitter2 = pool.send('xan', 'second', 'test');

      const errors: Error[] = [];
      emitter1.on('error', (e) => errors.push(e));
      emitter2.on('error', (e) => errors.push(e));

      pool.cancel('xan');

      const state = pool.get('xan')!;
      expect(state.busy).toBe(false);
      expect(state.queue).toEqual([]);
      expect(errors).toHaveLength(2);

      // Should have sent C-c
      expect(mockExecFileSync).toHaveBeenCalledWith(
        'tmux', ['send-keys', '-t', 'test:xan', 'C-c', ''], expect.any(Object),
      );
    });

    it('is a no-op for unknown agent', () => {
      const pool = new TmuxPool('test');
      expect(() => pool.cancel('unknown')).not.toThrow();
    });
  });

  describe('killWindow', () => {
    it('removes agent from pool', () => {
      const pool = new TmuxPool('test');
      pool.createWindow('xan', {
        sessionId: 'sess-123',
        claudeBin: 'claude',
        mcpConfigPath: '/tmp/mcp.json',
      });
      expect(pool.agentNames()).toEqual(['xan']);

      pool.killWindow('xan');
      expect(pool.agentNames()).toEqual([]);
      expect(pool.get('xan')).toBeUndefined();

      expect(mockExecFileSync).toHaveBeenCalledWith(
        'tmux', ['kill-window', '-t', 'test:xan'], expect.any(Object),
      );
    });
  });

  describe('stopAll', () => {
    it('kills all windows and session', () => {
      const pool = new TmuxPool('test');
      pool.createWindow('xan', {
        sessionId: 'sess-1',
        claudeBin: 'claude',
        mcpConfigPath: '/tmp/mcp.json',
      });
      pool.createWindow('mirror', {
        sessionId: 'sess-2',
        claudeBin: 'claude',
        mcpConfigPath: '/tmp/mcp.json',
      });

      pool.stopAll();
      expect(pool.agentNames()).toEqual([]);
      expect(mockExecFileSync).toHaveBeenCalledWith(
        'tmux', ['kill-session', '-t', 'test'], expect.any(Object),
      );
    });
  });
});
