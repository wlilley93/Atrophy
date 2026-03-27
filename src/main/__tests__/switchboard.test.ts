/**
 * Tests for channels/switchboard.ts
 *
 * Tests register/unregister (directory cleanup), envelope routing,
 * broadcast semantics, and createEnvelope. We mock the config module
 * and logger to avoid filesystem and Electron dependencies.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('../config', () => ({
  USER_DATA: '/tmp/atrophy-switchboard-test',
}));

vi.mock('../logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }),
}));

vi.mock('uuid', () => ({
  v4: () => 'test-uuid-1234',
}));

// ---------------------------------------------------------------------------
// Import after mocks are set up
// ---------------------------------------------------------------------------

// We need a fresh instance for each test, so we use dynamic import
// and reset modules between tests.
import type { Envelope, MessageHandler, ServiceEntry } from '../channels/switchboard';

let switchboard: typeof import('../channels/switchboard')['switchboard'];

beforeEach(async () => {
  vi.resetModules();
  const mod = await import('../channels/switchboard');
  switchboard = mod.switchboard;
});

// ---------------------------------------------------------------------------
// register / unregister
// ---------------------------------------------------------------------------

describe('register', () => {
  it('registers a handler for an address', () => {
    const handler = vi.fn();
    switchboard.register('agent:xan', handler);
    expect(switchboard.hasHandler('agent:xan')).toBe(true);
  });

  it('adds an entry to the service directory', () => {
    const handler = vi.fn();
    switchboard.register('agent:xan', handler, { description: 'Xan agent' });
    const entry = switchboard.getService('agent:xan');
    expect(entry).toBeDefined();
    expect(entry!.address).toBe('agent:xan');
    expect(entry!.description).toBe('Xan agent');
    expect(entry!.type).toBe('agent');
  });

  it('infers agent type from address prefix', () => {
    switchboard.register('agent:companion', vi.fn());
    expect(switchboard.getService('agent:companion')!.type).toBe('agent');
  });

  it('infers channel type from telegram prefix', () => {
    switchboard.register('telegram:xan', vi.fn());
    expect(switchboard.getService('telegram:xan')!.type).toBe('channel');
  });

  it('infers channel type from desktop prefix', () => {
    switchboard.register('desktop:xan', vi.fn());
    expect(switchboard.getService('desktop:xan')!.type).toBe('channel');
  });

  it('infers webhook type from webhook prefix', () => {
    switchboard.register('webhook:alerts', vi.fn());
    expect(switchboard.getService('webhook:alerts')!.type).toBe('webhook');
  });

  it('infers mcp type from mcp prefix', () => {
    switchboard.register('mcp:memory', vi.fn());
    expect(switchboard.getService('mcp:memory')!.type).toBe('mcp');
  });

  it('infers federation type from federation prefix', () => {
    switchboard.register('federation:remote', vi.fn());
    expect(switchboard.getService('federation:remote')!.type).toBe('federation');
  });

  it('defaults to system type for unknown prefixes', () => {
    switchboard.register('unknown:thing', vi.fn());
    expect(switchboard.getService('unknown:thing')!.type).toBe('system');
  });

  it('allows explicit type override', () => {
    switchboard.register('agent:xan', vi.fn(), { type: 'system' });
    expect(switchboard.getService('agent:xan')!.type).toBe('system');
  });

  it('overwrites existing handler and logs warning', () => {
    const handler1 = vi.fn();
    const handler2 = vi.fn();
    switchboard.register('agent:xan', handler1);
    switchboard.register('agent:xan', handler2);
    expect(switchboard.hasHandler('agent:xan')).toBe(true);
  });
});

describe('unregister', () => {
  it('removes the handler', () => {
    switchboard.register('agent:xan', vi.fn());
    expect(switchboard.hasHandler('agent:xan')).toBe(true);
    switchboard.unregister('agent:xan');
    expect(switchboard.hasHandler('agent:xan')).toBe(false);
  });

  it('removes the directory entry', () => {
    switchboard.register('agent:xan', vi.fn());
    switchboard.unregister('agent:xan');
    expect(switchboard.getService('agent:xan')).toBeUndefined();
  });

  it('is a no-op for unregistered addresses', () => {
    // Should not throw
    switchboard.unregister('agent:nonexistent');
    expect(switchboard.hasHandler('agent:nonexistent')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// route - exact match
// ---------------------------------------------------------------------------

describe('route - exact match', () => {
  it('routes to the registered handler', async () => {
    const handler = vi.fn();
    switchboard.register('agent:xan', handler);
    const envelope = switchboard.createEnvelope('telegram:xan', 'agent:xan', 'hello');
    await switchboard.route(envelope);
    expect(handler).toHaveBeenCalledWith(envelope);
  });

  it('does not call other handlers', async () => {
    const xanHandler = vi.fn();
    const companionHandler = vi.fn();
    switchboard.register('agent:xan', xanHandler);
    switchboard.register('agent:companion', companionHandler);
    const envelope = switchboard.createEnvelope('telegram:xan', 'agent:xan', 'hello');
    await switchboard.route(envelope);
    expect(xanHandler).toHaveBeenCalled();
    expect(companionHandler).not.toHaveBeenCalled();
  });

  it('records the message in the log', async () => {
    switchboard.register('agent:xan', vi.fn());
    const envelope = switchboard.createEnvelope('telegram:xan', 'agent:xan', 'hello');
    await switchboard.route(envelope);
    const recent = switchboard.getRecentMessages(10);
    expect(recent.some(e => e.text === 'hello')).toBe(true);
  });

  it('handles missing handler gracefully (no throw)', async () => {
    const envelope = switchboard.createEnvelope('telegram:xan', 'agent:missing', 'hello');
    // Should not throw
    await switchboard.route(envelope);
  });
});

// ---------------------------------------------------------------------------
// route - broadcast
// ---------------------------------------------------------------------------

describe('route - broadcast', () => {
  it('delivers to all matching handlers', async () => {
    const xanHandler = vi.fn();
    const companionHandler = vi.fn();
    switchboard.register('agent:xan', xanHandler);
    switchboard.register('agent:companion', companionHandler);
    const envelope = switchboard.createEnvelope('system', 'agent:*', 'broadcast msg');
    await switchboard.route(envelope);
    expect(xanHandler).toHaveBeenCalledWith(envelope);
    expect(companionHandler).toHaveBeenCalledWith(envelope);
  });

  it('excludes the sender from broadcast', async () => {
    const xanHandler = vi.fn();
    const companionHandler = vi.fn();
    switchboard.register('agent:xan', xanHandler);
    switchboard.register('agent:companion', companionHandler);
    const envelope = switchboard.createEnvelope('agent:xan', 'agent:*', 'broadcast msg');
    await switchboard.route(envelope);
    expect(xanHandler).not.toHaveBeenCalled();
    expect(companionHandler).toHaveBeenCalled();
  });

  it('does not deliver to non-matching prefixes', async () => {
    const agentHandler = vi.fn();
    const telegramHandler = vi.fn();
    switchboard.register('agent:xan', agentHandler);
    switchboard.register('telegram:xan', telegramHandler);
    const envelope = switchboard.createEnvelope('system', 'agent:*', 'broadcast');
    await switchboard.route(envelope);
    expect(agentHandler).toHaveBeenCalled();
    expect(telegramHandler).not.toHaveBeenCalled();
  });

  it('handles no matching handlers gracefully', async () => {
    switchboard.register('telegram:xan', vi.fn());
    const envelope = switchboard.createEnvelope('system', 'agent:*', 'broadcast');
    // Should not throw
    await switchboard.route(envelope);
  });
});

// ---------------------------------------------------------------------------
// route - error handling
// ---------------------------------------------------------------------------

describe('route - error handling', () => {
  it('catches and logs handler errors on exact match', async () => {
    const handler = vi.fn().mockRejectedValue(new Error('handler failed'));
    switchboard.register('agent:xan', handler);
    const envelope = switchboard.createEnvelope('telegram:xan', 'agent:xan', 'hello');
    // Should not throw
    await switchboard.route(envelope);
    expect(handler).toHaveBeenCalled();
  });

  it('continues broadcast delivery when one handler throws', async () => {
    const failHandler = vi.fn().mockRejectedValue(new Error('fail'));
    const successHandler = vi.fn();
    switchboard.register('agent:fail', failHandler);
    switchboard.register('agent:success', successHandler);
    const envelope = switchboard.createEnvelope('system', 'agent:*', 'broadcast');
    await switchboard.route(envelope);
    expect(failHandler).toHaveBeenCalled();
    expect(successHandler).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// createEnvelope
// ---------------------------------------------------------------------------

describe('createEnvelope', () => {
  it('creates an envelope with required fields', () => {
    const env = switchboard.createEnvelope('telegram:xan', 'agent:xan', 'hello');
    expect(env.id).toBe('test-uuid-1234');
    expect(env.from).toBe('telegram:xan');
    expect(env.to).toBe('agent:xan');
    expect(env.text).toBe('hello');
    expect(env.type).toBe('user');
    expect(env.priority).toBe('normal');
    expect(env.replyTo).toBe('telegram:xan');
    expect(typeof env.timestamp).toBe('number');
  });

  it('allows overriding type and priority', () => {
    const env = switchboard.createEnvelope('system', 'agent:xan', 'alert', {
      type: 'system',
      priority: 'high',
    });
    expect(env.type).toBe('system');
    expect(env.priority).toBe('high');
  });

  it('allows setting replyTo explicitly', () => {
    const env = switchboard.createEnvelope('cron:xan', 'agent:xan', 'job done', {
      replyTo: 'telegram:xan',
    });
    expect(env.replyTo).toBe('telegram:xan');
  });

  it('allows setting metadata', () => {
    const env = switchboard.createEnvelope('system', 'agent:xan', 'msg', {
      metadata: { job: 'morning_brief', exitCode: 0 },
    });
    expect(env.metadata).toEqual({ job: 'morning_brief', exitCode: 0 });
  });
});

// ---------------------------------------------------------------------------
// record
// ---------------------------------------------------------------------------

describe('record', () => {
  it('adds envelope to log without routing', async () => {
    const handler = vi.fn();
    switchboard.register('agent:xan', handler);
    const env = switchboard.createEnvelope('desktop:xan', 'agent:xan', 'recorded');
    switchboard.record(env);
    expect(handler).not.toHaveBeenCalled();
    const recent = switchboard.getRecentMessages(10);
    expect(recent.some(e => e.text === 'recorded')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// getRecentMessages
// ---------------------------------------------------------------------------

describe('getRecentMessages', () => {
  it('returns empty array initially', () => {
    expect(switchboard.getRecentMessages()).toHaveLength(0);
  });

  it('respects count parameter', () => {
    for (let i = 0; i < 10; i++) {
      switchboard.record(switchboard.createEnvelope('a', 'b', `msg${i}`));
    }
    expect(switchboard.getRecentMessages(3)).toHaveLength(3);
  });

  it('defaults to returning up to 50 messages', () => {
    for (let i = 0; i < 60; i++) {
      switchboard.record(switchboard.createEnvelope('a', 'b', `msg${i}`));
    }
    expect(switchboard.getRecentMessages()).toHaveLength(50);
  });
});

// ---------------------------------------------------------------------------
// getRegisteredAddresses / hasHandler
// ---------------------------------------------------------------------------

describe('getRegisteredAddresses', () => {
  it('returns all registered addresses', () => {
    switchboard.register('agent:xan', vi.fn());
    switchboard.register('telegram:xan', vi.fn());
    switchboard.register('mcp:memory', vi.fn());
    const addresses = switchboard.getRegisteredAddresses();
    expect(addresses).toContain('agent:xan');
    expect(addresses).toContain('telegram:xan');
    expect(addresses).toContain('mcp:memory');
  });

  it('returns empty array when nothing is registered', () => {
    expect(switchboard.getRegisteredAddresses()).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// getDirectory / getDirectoryByType / getService
// ---------------------------------------------------------------------------

describe('service directory', () => {
  it('getDirectory returns all entries', () => {
    switchboard.register('agent:xan', vi.fn());
    switchboard.register('telegram:xan', vi.fn());
    const dir = switchboard.getDirectory();
    expect(dir).toHaveLength(2);
  });

  it('getDirectoryByType filters correctly', () => {
    switchboard.register('agent:xan', vi.fn());
    switchboard.register('agent:companion', vi.fn());
    switchboard.register('telegram:xan', vi.fn());
    const agents = switchboard.getDirectoryByType('agent');
    expect(agents).toHaveLength(2);
    expect(agents.every(e => e.type === 'agent')).toBe(true);
  });

  it('getService returns undefined for missing address', () => {
    expect(switchboard.getService('agent:nonexistent')).toBeUndefined();
  });

  it('directory entries have registeredAt timestamp', () => {
    switchboard.register('agent:xan', vi.fn());
    const entry = switchboard.getService('agent:xan');
    expect(entry!.registeredAt).toBeGreaterThan(0);
  });

  it('directory stores capabilities when provided', () => {
    switchboard.register('mcp:memory', vi.fn(), {
      capabilities: ['store', 'search', 'retrieve'],
    });
    const entry = switchboard.getService('mcp:memory');
    expect(entry!.capabilities).toEqual(['store', 'search', 'retrieve']);
  });
});

// ---------------------------------------------------------------------------
// Message log trimming
// ---------------------------------------------------------------------------

describe('message log trimming', () => {
  it('trims log to MAX_LOG_SIZE (200)', async () => {
    switchboard.register('agent:xan', vi.fn());
    // Route 250 messages - log should cap at 200
    for (let i = 0; i < 250; i++) {
      const env = switchboard.createEnvelope('system', 'agent:xan', `msg-${i}`);
      await switchboard.route(env);
    }
    // Default getRecentMessages limit is 50, but internally log is 200
    const recent = switchboard.getRecentMessages(300);
    expect(recent.length).toBeLessThanOrEqual(200);
    // Last message should be the most recent
    expect(recent[recent.length - 1].text).toBe('msg-249');
  });
});
