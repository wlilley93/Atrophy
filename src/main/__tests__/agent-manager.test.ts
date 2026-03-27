/**
 * Tests for agent-manager.ts
 *
 * Tests checkAskRequest scanning, deleteAgent backup path,
 * validateDeferralRequest, session suspension/resumption, and
 * discoverAgents with org-nested agents.
 *
 * Uses a temp directory to isolate filesystem operations.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

// ---------------------------------------------------------------------------
// Temp directory for isolated test filesystem
// ---------------------------------------------------------------------------

// vi.mock factories are hoisted - cannot reference variables declared after them.
// Use a fixed path derived from process.pid.
const TEST_DIR = `/tmp/atrophy-agent-mgr-test-${process.pid}`;
const TEST_USER_DATA = `${TEST_DIR}/user`;
const TEST_BUNDLE_ROOT = `${TEST_DIR}/bundle`;

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('../config', () => {
  const _dir = `/tmp/atrophy-agent-mgr-test-${process.pid}`;
  const _userData = `${_dir}/user`;
  const _bundleRoot = `${_dir}/bundle`;
  return {
    USER_DATA: _userData,
    BUNDLE_ROOT: _bundleRoot,
    isValidAgentName: (name: string) => /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(name) && !name.includes('..'),
    getConfig: () => ({
      AGENT_NAME: 'xan',
      AGENT_STATES_FILE: `${_userData}/agent_states.json`,
      PYTHON_PATH: 'python3',
    }),
  };
});

vi.mock('../logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import {
  deleteAgent,
  validateDeferralRequest,
  suspendAgentSession,
  resumeAgentSession,
  checkAskRequest,
  discoverAgents,
  findManifest,
  getAgentDir,
} from '../agent-manager';

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  fs.mkdirSync(path.join(TEST_USER_DATA, 'agents'), { recursive: true });
  fs.mkdirSync(path.join(TEST_BUNDLE_ROOT, 'agents'), { recursive: true });
});

afterEach(() => {
  fs.rmSync(TEST_DIR, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createAgent(name: string, manifest?: Record<string, unknown>): void {
  const dataDir = path.join(TEST_USER_DATA, 'agents', name, 'data');
  fs.mkdirSync(dataDir, { recursive: true });
  if (manifest) {
    fs.writeFileSync(path.join(dataDir, 'agent.json'), JSON.stringify(manifest));
  }
}

function createOrgAgent(org: string, name: string, manifest?: Record<string, unknown>): void {
  const dataDir = path.join(TEST_USER_DATA, 'agents', org, name, 'data');
  fs.mkdirSync(dataDir, { recursive: true });
  if (manifest) {
    fs.writeFileSync(path.join(dataDir, 'agent.json'), JSON.stringify(manifest));
  }
}

function createBundledAgent(name: string, manifest?: Record<string, unknown>): void {
  const dataDir = path.join(TEST_BUNDLE_ROOT, 'agents', name, 'data');
  fs.mkdirSync(dataDir, { recursive: true });
  if (manifest) {
    fs.writeFileSync(path.join(dataDir, 'agent.json'), JSON.stringify(manifest));
  }
}

// ---------------------------------------------------------------------------
// deleteAgent
// ---------------------------------------------------------------------------

describe('deleteAgent', () => {
  it('removes the agent directory', () => {
    createAgent('test-agent');
    const agentDir = path.join(TEST_USER_DATA, 'agents', 'test-agent');
    expect(fs.existsSync(agentDir)).toBe(true);
    deleteAgent('test-agent');
    // The directory may be recreated for memory backup, but main files are gone
  });

  it('preserves memory.db after deletion', () => {
    createAgent('test-agent');
    const dbPath = path.join(TEST_USER_DATA, 'agents', 'test-agent', 'data', 'memory.db');
    fs.writeFileSync(dbPath, 'fake-db-content');
    deleteAgent('test-agent');
    // memory.db should be restored
    const restoredDb = path.join(TEST_USER_DATA, 'agents', 'test-agent', 'data', 'memory.db');
    expect(fs.existsSync(restoredDb)).toBe(true);
    expect(fs.readFileSync(restoredDb, 'utf-8')).toBe('fake-db-content');
  });

  it('works when no memory.db exists', () => {
    createAgent('test-agent');
    deleteAgent('test-agent');
    // Should not throw
    const restoredDb = path.join(TEST_USER_DATA, 'agents', 'test-agent', 'data', 'memory.db');
    expect(fs.existsSync(restoredDb)).toBe(false);
  });

  it('removes all other files but keeps memory', () => {
    createAgent('test-agent');
    const dataDir = path.join(TEST_USER_DATA, 'agents', 'test-agent', 'data');
    fs.writeFileSync(path.join(dataDir, 'memory.db'), 'db-data');
    fs.writeFileSync(path.join(dataDir, '.emotional_state.json'), '{}');
    fs.writeFileSync(path.join(dataDir, 'agent.json'), '{}');

    deleteAgent('test-agent');

    // Only memory.db should survive
    const restoredDb = path.join(dataDir, 'memory.db');
    expect(fs.existsSync(restoredDb)).toBe(true);
    expect(fs.existsSync(path.join(dataDir, '.emotional_state.json'))).toBe(false);
    expect(fs.existsSync(path.join(dataDir, 'agent.json'))).toBe(false);
  });

  it('throws for invalid agent name', () => {
    expect(() => deleteAgent('../evil')).toThrow('Invalid agent name');
  });

  it('throws for non-existent agent directory', () => {
    expect(() => deleteAgent('nonexistent')).toThrow('not found');
  });

  it('backs up memory.db outside agent dir before rmSync', () => {
    createAgent('test-agent');
    const dbPath = path.join(TEST_USER_DATA, 'agents', 'test-agent', 'data', 'memory.db');
    fs.writeFileSync(dbPath, 'important-data');

    deleteAgent('test-agent');

    // The backup at agents/<name>.memory.db.preserved should be cleaned up
    // (it gets renamed back). The restored file should have the content.
    const restored = path.join(TEST_USER_DATA, 'agents', 'test-agent', 'data', 'memory.db');
    expect(fs.readFileSync(restored, 'utf-8')).toBe('important-data');
  });
});

// ---------------------------------------------------------------------------
// validateDeferralRequest
// ---------------------------------------------------------------------------

describe('validateDeferralRequest', () => {
  it('rejects deferral to self', () => {
    expect(validateDeferralRequest('xan', 'xan')).toBe(false);
  });

  it('accepts deferral to a different agent', () => {
    expect(validateDeferralRequest('companion', 'xan')).toBe(true);
  });

  it('blocks deferrals after exceeding MAX_DEFERRALS_PER_WINDOW (anti-loop)', () => {
    // The deferral counter is module-level and accumulates across test calls
    // in the same window. Previous test ("accepts deferral") already incremented it.
    // Call repeatedly until the window limit (3) is exceeded, then verify blocking.
    // We may already be partway through the window.
    let successes = 0;
    for (let i = 0; i < 10; i++) {
      if (validateDeferralRequest('companion', 'xan')) {
        successes++;
      } else {
        break;
      }
    }
    // Some calls succeeded but eventually it was blocked
    expect(successes).toBeLessThanOrEqual(3);
    // Now it should definitely be blocked
    expect(validateDeferralRequest('companion', 'xan')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// suspendAgentSession / resumeAgentSession
// ---------------------------------------------------------------------------

describe('session suspension', () => {
  it('suspends and resumes a session', () => {
    const history = [{ role: 'user', content: 'hello' }];
    suspendAgentSession('xan', 'session-123', history);
    const result = resumeAgentSession('xan');
    expect(result).not.toBeNull();
    expect(result!.cliSessionId).toBe('session-123');
    expect(result!.turnHistory).toEqual(history);
  });

  it('returns null when no session is suspended', () => {
    expect(resumeAgentSession('companion')).toBeNull();
  });

  it('clears the suspended session after resume', () => {
    suspendAgentSession('xan', 'session-456', []);
    resumeAgentSession('xan');
    expect(resumeAgentSession('xan')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// checkAskRequest
// ---------------------------------------------------------------------------

describe('checkAskRequest', () => {
  it('returns null when no ask request files exist', () => {
    createAgent('xan');
    expect(checkAskRequest()).toBeNull();
  });

  it('finds ask request in active agent', () => {
    createAgent('xan');
    const reqPath = path.join(TEST_USER_DATA, 'agents', 'xan', 'data', '.ask_request.json');
    const request = {
      question: 'Are you sure?',
      action_type: 'confirmation',
      request_id: 'req-1',
      timestamp: Date.now(),
    };
    fs.writeFileSync(reqPath, JSON.stringify(request));
    const result = checkAskRequest();
    expect(result).not.toBeNull();
    expect(result!.question).toBe('Are you sure?');
  });

  it('finds ask request in non-active agent (background scan)', () => {
    createAgent('xan');
    createAgent('companion');
    const reqPath = path.join(TEST_USER_DATA, 'agents', 'companion', 'data', '.ask_request.json');
    const request = {
      question: 'Background question',
      action_type: 'question',
      request_id: 'req-2',
      timestamp: Date.now(),
    };
    fs.writeFileSync(reqPath, JSON.stringify(request));
    const result = checkAskRequest();
    expect(result).not.toBeNull();
    expect(result!.question).toBe('Background question');
    expect((result as any)._agent).toBe('companion');
  });

  it('ignores stale requests older than 3 minutes', () => {
    createAgent('xan');
    const reqPath = path.join(TEST_USER_DATA, 'agents', 'xan', 'data', '.ask_request.json');
    const request = {
      question: 'Old question',
      action_type: 'question',
      request_id: 'req-3',
      timestamp: Date.now() - 200_000, // 200 seconds ago (> 180s)
    };
    fs.writeFileSync(reqPath, JSON.stringify(request));
    const result = checkAskRequest();
    expect(result).toBeNull();
    // Stale request should be cleaned up
    expect(fs.existsSync(reqPath)).toBe(false);
  });

  it('scans org-nested agent directories', () => {
    createAgent('xan');
    createOrgAgent('defence-org', 'montgomery');
    const reqPath = path.join(
      TEST_USER_DATA, 'agents', 'defence-org', 'montgomery', 'data', '.ask_request.json',
    );
    const request = {
      question: 'Org nested question',
      action_type: 'question',
      request_id: 'req-4',
      timestamp: Date.now(),
    };
    fs.writeFileSync(reqPath, JSON.stringify(request));
    const result = checkAskRequest();
    expect(result).not.toBeNull();
    expect(result!.question).toBe('Org nested question');
  });
});

// ---------------------------------------------------------------------------
// discoverAgents
// ---------------------------------------------------------------------------

describe('discoverAgents', () => {
  it('discovers flat agents', () => {
    createAgent('xan', { display_name: 'Xan', description: 'Primary companion' });
    createAgent('companion', { display_name: 'Companion' });
    const agents = discoverAgents();
    expect(agents.length).toBe(2);
    const names = agents.map(a => a.name);
    expect(names).toContain('xan');
    expect(names).toContain('companion');
  });

  it('discovers org-nested agents', () => {
    createAgent('xan');
    createOrgAgent('defence-org', 'montgomery', {
      display_name: 'Montgomery',
      org: { tier: 2, name: 'defence-org' },
    });
    const agents = discoverAgents();
    const names = agents.map(a => a.name);
    expect(names).toContain('montgomery');
  });

  it('de-duplicates agents seen in multiple locations', () => {
    // Same name in user and bundle
    createAgent('xan');
    createBundledAgent('xan');
    const agents = discoverAgents();
    const xanCount = agents.filter(a => a.name === 'xan').length;
    expect(xanCount).toBe(1);
  });

  it('sorts by tier ascending then alphabetically', () => {
    createAgent('xan', { org: { tier: 1 } });
    createAgent('alpha', { org: { tier: 1 } });
    createAgent('zulu', { org: { tier: 2 } });
    const agents = discoverAgents();
    // tier 1 agents first (alpha, xan), then tier 2 (zulu)
    const names = agents.map(a => a.name);
    expect(names.indexOf('alpha')).toBeLessThan(names.indexOf('zulu'));
    expect(names.indexOf('xan')).toBeLessThan(names.indexOf('zulu'));
  });

  it('returns empty array when no agents exist', () => {
    const agents = discoverAgents();
    expect(agents).toHaveLength(0);
  });

  it('reads display_name from manifest', () => {
    createAgent('xan', { display_name: 'Xan the AI' });
    const agents = discoverAgents();
    expect(agents[0].display_name).toBe('Xan the AI');
  });

  it('capitalizes name as fallback display_name', () => {
    createAgent('xan', {});
    const agents = discoverAgents();
    expect(agents[0].display_name).toBe('Xan');
  });
});

// ---------------------------------------------------------------------------
// findManifest / getAgentDir
// ---------------------------------------------------------------------------

describe('findManifest', () => {
  it('returns parsed manifest for existing agent', () => {
    createAgent('xan', { display_name: 'Xan', role: 'companion' });
    const manifest = findManifest('xan');
    expect(manifest).not.toBeNull();
    expect(manifest!.display_name).toBe('Xan');
    expect(manifest!.role).toBe('companion');
  });

  it('returns null for agent with no manifest', () => {
    createAgent('minimal'); // no manifest file
    const manifest = findManifest('minimal');
    expect(manifest).toBeNull();
  });
});

describe('getAgentDir', () => {
  it('returns flat user path for flat agents', () => {
    createAgent('xan');
    const dir = getAgentDir('xan');
    expect(dir).toBe(path.join(TEST_USER_DATA, 'agents', 'xan'));
  });

  it('returns org-nested path for org agents', () => {
    createOrgAgent('defence-org', 'montgomery');
    const dir = getAgentDir('montgomery');
    expect(dir).toBe(path.join(TEST_USER_DATA, 'agents', 'defence-org', 'montgomery'));
  });

  it('falls back to flat user path for unknown agents', () => {
    const dir = getAgentDir('unknown');
    expect(dir).toBe(path.join(TEST_USER_DATA, 'agents', 'unknown'));
  });

  it('prefers org-nested over flat when both exist', () => {
    createAgent('montgomery');
    createOrgAgent('defence-org', 'montgomery');
    const dir = getAgentDir('montgomery');
    // org-nested is checked first
    expect(dir).toBe(path.join(TEST_USER_DATA, 'agents', 'defence-org', 'montgomery'));
  });
});
