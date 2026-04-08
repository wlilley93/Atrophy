import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

// ---------------------------------------------------------------------------
// Temp directory for isolated test filesystem
// ---------------------------------------------------------------------------

const TEST_DIR = path.join('/tmp', 'atrophy-org-test-' + process.pid);
const TEST_USER_DATA = path.join(TEST_DIR, 'user');
const TEST_BUNDLE_ROOT = path.join(TEST_DIR, 'bundle');
const ORGS_DIR = path.join(TEST_USER_DATA, 'orgs');
const AGENTS_DIR = path.join(TEST_USER_DATA, 'agents');

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('../config', () => ({
  USER_DATA: TEST_USER_DATA,
  BUNDLE_ROOT: TEST_BUNDLE_ROOT,
  isValidAgentName: (name: string) => /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(name) && !name.includes('..'),
  saveAgentConfig: vi.fn((agentName: string, updates: Record<string, unknown>) => {
    const agentJsonPath = path.join(TEST_USER_DATA, 'agents', agentName, 'data', 'agent.json');
    let existing: Record<string, unknown> = {};
    try {
      existing = JSON.parse(fs.readFileSync(agentJsonPath, 'utf-8'));
    } catch { /* empty */ }
    for (const [key, value] of Object.entries(updates)) {
      existing[key] = value;
    }
    fs.mkdirSync(path.dirname(agentJsonPath), { recursive: true });
    fs.writeFileSync(agentJsonPath, JSON.stringify(existing, null, 2));
  }),
  getConfig: () => ({}),
}));

vi.mock('../logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }),
}));

// Mock better-sqlite3 since the native module may not match the test Node version
const mockDbExec = vi.fn();
const mockDbClose = vi.fn();
vi.mock('better-sqlite3', () => {
  function MockDatabase() {
    return {
      exec: mockDbExec,
      close: mockDbClose,
      prepare: vi.fn(() => ({ all: vi.fn(() => []), get: vi.fn(() => null) })),
    };
  }
  return { default: MockDatabase };
});

vi.mock('../mcp-registry', () => ({
  readAgentManifest: vi.fn((name: string) => {
    for (const base of [
      path.join(TEST_USER_DATA, 'agents', name),
      path.join(TEST_BUNDLE_ROOT, 'agents', name),
    ]) {
      const mpath = path.join(base, 'data', 'agent.json');
      if (fs.existsSync(mpath)) {
        try {
          return JSON.parse(fs.readFileSync(mpath, 'utf-8'));
        } catch { /* skip */ }
      }
    }
    return {};
  }),
}));

vi.mock('../agent-manager', () => ({
  discoverAgents: vi.fn(() => {
    const agents: Array<{ name: string; display_name: string; description: string; role: string }> = [];
    if (fs.existsSync(AGENTS_DIR)) {
      for (const name of fs.readdirSync(AGENTS_DIR)) {
        const dataDir = path.join(AGENTS_DIR, name, 'data');
        if (fs.existsSync(dataDir)) {
          agents.push({ name, display_name: name, description: '', role: '' });
        }
      }
    }
    return agents;
  }),
  getAgentDir: (name: string) => path.join(AGENTS_DIR, name),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createTestAgent(name: string, manifest: Record<string, unknown> = {}): void {
  const agentDir = path.join(AGENTS_DIR, name, 'data');
  fs.mkdirSync(agentDir, { recursive: true });
  const defaults = { name, display_name: name, description: '', role: '' };
  fs.writeFileSync(
    path.join(agentDir, 'agent.json'),
    JSON.stringify({ ...defaults, ...manifest }, null, 2),
  );
}

function readAgentJson(name: string): Record<string, unknown> {
  const p = path.join(AGENTS_DIR, name, 'data', 'agent.json');
  return JSON.parse(fs.readFileSync(p, 'utf-8'));
}

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Create fresh test directories
  fs.mkdirSync(ORGS_DIR, { recursive: true });
  fs.mkdirSync(AGENTS_DIR, { recursive: true });

  // Create org-schema.sql in bundle
  const schemaDir = path.join(TEST_BUNDLE_ROOT, 'db');
  fs.mkdirSync(schemaDir, { recursive: true });
  fs.writeFileSync(
    path.join(schemaDir, 'org-schema.sql'),
    `CREATE TABLE IF NOT EXISTS sessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT UNIQUE NOT NULL,
      agent_name TEXT NOT NULL,
      started_at TEXT NOT NULL DEFAULT (datetime('now')),
      ended_at TEXT,
      summary TEXT
    );
    CREATE TABLE IF NOT EXISTS observations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      agent_name TEXT NOT NULL,
      content TEXT NOT NULL,
      category TEXT DEFAULT 'general',
      confidence REAL DEFAULT 1.0,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now')),
      source TEXT
    );`,
  );
});

afterEach(async () => {
  // Clear manifest cache between tests
  const { clearCache } = await import('../org-manager');
  clearCache();

  // Clean up test directories
  fs.rmSync(TEST_DIR, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('createOrg', () => {
  it('creates org directory, org.json, and memory.db', async () => {
    const { createOrg } = await import('../org-manager');

    const result = createOrg('Defence Bureau', 'government', 'National security');

    expect(result.name).toBe('Defence Bureau');
    expect(result.slug).toBe('defence-bureau');
    expect(result.type).toBe('government');
    expect(result.purpose).toBe('National security');
    expect(result.created).toBeDefined();
    expect(result.principal).toBeNull();

    // Check filesystem
    const orgDir = path.join(ORGS_DIR, 'defence-bureau');
    expect(fs.existsSync(path.join(orgDir, 'org.json'))).toBe(true);

    // Check org.json content
    const orgJson = JSON.parse(fs.readFileSync(path.join(orgDir, 'org.json'), 'utf-8'));
    expect(orgJson.name).toBe('Defence Bureau');
    expect(orgJson.type).toBe('government');

    // Verify Database was called (mocked - no real file created)
    expect(mockDbExec).toHaveBeenCalled();
    expect(mockDbClose).toHaveBeenCalled();
  });

  it('rejects duplicate org slug', async () => {
    const { createOrg } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    expect(() => createOrg('Defence Bureau', 'company', 'Different purpose')).toThrow(
      /already exists/,
    );
  });

  it('rejects invalid org type', async () => {
    const { createOrg } = await import('../org-manager');

    expect(() => createOrg('Bad Org', 'invalid' as 'government', 'Purpose')).toThrow(
      /Invalid org type/,
    );
  });

  it('rejects empty name', async () => {
    const { createOrg } = await import('../org-manager');

    expect(() => createOrg('', 'company', 'Purpose')).toThrow(/name cannot be empty/);
  });

  it('generates slug from name', async () => {
    const { createOrg } = await import('../org-manager');

    const result = createOrg('Music & Arts Co.', 'creative', 'Music production');
    expect(result.slug).toBe('music-arts-co');
  });
});

describe('listOrgs', () => {
  it('returns empty array when no orgs exist', async () => {
    const { listOrgs } = await import('../org-manager');

    expect(listOrgs()).toEqual([]);
  });

  it('returns all created orgs', async () => {
    const { createOrg, listOrgs } = await import('../org-manager');

    createOrg('Alpha Corp', 'company', 'Alpha business');
    createOrg('Beta Lab', 'creative', 'Beta creative');

    const orgs = listOrgs();
    expect(orgs).toHaveLength(2);
    const slugs = orgs.map(o => o.slug).sort();
    expect(slugs).toEqual(['alpha-corp', 'beta-lab']);
  });
});

describe('getOrgDetail', () => {
  it('returns manifest and roster', async () => {
    const { createOrg, addAgentToOrg, getOrgDetail, clearCache } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    createTestAgent('general', { org: { slug: 'defence-bureau', tier: 1, role: 'Commander' } });
    clearCache();

    const detail = getOrgDetail('defence-bureau');
    expect(detail.manifest.name).toBe('Defence Bureau');
    expect(detail.roster).toHaveLength(1);
    expect(detail.roster[0].name).toBe('general');
    expect(detail.roster[0].tier).toBe(1);
  });

  it('throws for non-existent org', async () => {
    const { getOrgDetail } = await import('../org-manager');

    expect(() => getOrgDetail('nonexistent')).toThrow(/not found/);
  });
});

describe('getOrgRoster', () => {
  it('returns agents matching org slug', async () => {
    const { createOrg, getOrgRoster, clearCache } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    createTestAgent('agent_a', { org: { slug: 'defence-bureau', tier: 1, role: 'Lead' } });
    createTestAgent('agent_b', { org: { slug: 'defence-bureau', tier: 2, role: 'Staff' } });
    createTestAgent('agent_c', { org: { slug: 'other-org', tier: 1, role: 'Lead' } });
    clearCache();

    const roster = getOrgRoster('defence-bureau');
    expect(roster).toHaveLength(2);
    expect(roster.map(a => a.name).sort()).toEqual(['agent_a', 'agent_b']);
  });

  it('returns empty array for org with no agents', async () => {
    const { createOrg, getOrgRoster } = await import('../org-manager');

    createOrg('Empty Org', 'utility', 'Nothing here');

    const roster = getOrgRoster('empty-org');
    expect(roster).toEqual([]);
  });
});

describe('addAgentToOrg', () => {
  it('updates agent manifest with org section', async () => {
    const { createOrg, addAgentToOrg } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    createTestAgent('soldier', {});

    addAgentToOrg('defence-bureau', 'soldier', 'Infantry', 2, null);

    const manifest = readAgentJson('soldier');
    const org = manifest.org as Record<string, unknown>;
    expect(org.slug).toBe('defence-bureau');
    expect(org.tier).toBe(2);
    expect(org.role).toBe('Infantry');
    expect(org.reports_to).toBeNull();
  });

  it('updates parent direct_reports when reportsTo is set', async () => {
    const { createOrg, addAgentToOrg, clearCache } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    createTestAgent('general', {
      org: { slug: 'defence-bureau', tier: 1, role: 'Commander', direct_reports: [] },
    });
    createTestAgent('soldier', {});
    clearCache();

    addAgentToOrg('defence-bureau', 'soldier', 'Infantry', 2, 'general');

    const parentManifest = readAgentJson('general');
    const parentOrg = parentManifest.org as Record<string, unknown>;
    expect(parentOrg.direct_reports).toContain('soldier');
  });

  it('sets org principal when tier is 1 and no principal exists', async () => {
    const { createOrg, addAgentToOrg } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    createTestAgent('general', {});

    addAgentToOrg('defence-bureau', 'general', 'Commander', 1, null);

    const orgJson = JSON.parse(
      fs.readFileSync(path.join(ORGS_DIR, 'defence-bureau', 'org.json'), 'utf-8'),
    );
    expect(orgJson.principal).toBe('general');
  });

  it('throws for non-existent org', async () => {
    const { addAgentToOrg } = await import('../org-manager');

    createTestAgent('soldier', {});
    expect(() => addAgentToOrg('nonexistent', 'soldier', 'Role', 2, null)).toThrow(
      /not found/,
    );
  });

  it('throws for invalid agent name', async () => {
    const { createOrg, addAgentToOrg } = await import('../org-manager');

    createOrg('Test Org', 'utility', 'Testing');
    expect(() => addAgentToOrg('test-org', '../bad', 'Role', 2, null)).toThrow(
      /Invalid agent name/,
    );
  });
});

describe('removeAgentFromOrg', () => {
  it('removes org section from agent manifest', async () => {
    const { createOrg, addAgentToOrg, removeAgentFromOrg, clearCache } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    createTestAgent('soldier', {});
    addAgentToOrg('defence-bureau', 'soldier', 'Infantry', 2, null);
    clearCache();

    removeAgentFromOrg('soldier');

    const manifest = readAgentJson('soldier');
    expect(manifest.org).toBeUndefined();
  });

  it('removes agent from parent direct_reports', async () => {
    const { createOrg, addAgentToOrg, removeAgentFromOrg, clearCache } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    createTestAgent('general', {
      org: { slug: 'defence-bureau', tier: 1, role: 'Commander', direct_reports: [] },
    });
    createTestAgent('soldier', {});
    clearCache();

    addAgentToOrg('defence-bureau', 'soldier', 'Infantry', 2, 'general');
    clearCache();

    removeAgentFromOrg('soldier');

    const parentManifest = readAgentJson('general');
    const parentOrg = parentManifest.org as Record<string, unknown>;
    expect(parentOrg.direct_reports).not.toContain('soldier');
  });

  it('clears org principal if removed agent was principal', async () => {
    const { createOrg, addAgentToOrg, removeAgentFromOrg, clearCache } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    createTestAgent('general', {});
    addAgentToOrg('defence-bureau', 'general', 'Commander', 1, null);
    clearCache();

    removeAgentFromOrg('general');

    const orgJson = JSON.parse(
      fs.readFileSync(path.join(ORGS_DIR, 'defence-bureau', 'org.json'), 'utf-8'),
    );
    expect(orgJson.principal).toBeNull();
  });
});

describe('dissolveOrg', () => {
  it('unassigns all agents and removes org directory', async () => {
    const { createOrg, addAgentToOrg, dissolveOrg, clearCache } = await import('../org-manager');

    createOrg('Defence Bureau', 'government', 'National security');
    createTestAgent('agent_a', {});
    createTestAgent('agent_b', {});
    addAgentToOrg('defence-bureau', 'agent_a', 'Lead', 1, null);
    addAgentToOrg('defence-bureau', 'agent_b', 'Staff', 2, 'agent_a');
    clearCache();

    dissolveOrg('defence-bureau');

    // Org directory removed
    expect(fs.existsSync(path.join(ORGS_DIR, 'defence-bureau'))).toBe(false);

    // Agents unassigned
    const manifestA = readAgentJson('agent_a');
    const manifestB = readAgentJson('agent_b');
    expect(manifestA.org).toBeUndefined();
    expect(manifestB.org).toBeUndefined();
  });

  it('throws for non-existent org', async () => {
    const { dissolveOrg } = await import('../org-manager');

    expect(() => dissolveOrg('nonexistent')).toThrow(/not found/);
  });
});

describe('clearCache', () => {
  it('invalidates manifest cache so fresh data is read', async () => {
    const { createOrg, getOrgRoster, clearCache } = await import('../org-manager');

    createOrg('Test Org', 'utility', 'Testing');
    createTestAgent('agent_x', { org: { slug: 'test-org', tier: 2, role: 'Worker' } });
    clearCache();

    expect(getOrgRoster('test-org')).toHaveLength(1);

    // Add another agent and clear cache
    createTestAgent('agent_y', { org: { slug: 'test-org', tier: 2, role: 'Worker 2' } });
    clearCache();

    expect(getOrgRoster('test-org')).toHaveLength(2);
  });
});
