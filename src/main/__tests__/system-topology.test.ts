import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Tests for the topology data assembly logic.
 * We test the pure data transformation, not the IPC plumbing.
 */

// Mock the modules we depend on
vi.mock('../agent-manager', () => ({
  discoverAgents: vi.fn(() => [
    { name: 'xan', display_name: 'Xan', description: '', role: '' },
    { name: 'companion', display_name: 'Companion', description: '', role: '' },
  ]),
}));

vi.mock('../mcp-registry', async () => {
  const actual = await vi.importActual('../mcp-registry') as Record<string, unknown>;
  return {
    ...actual,
    readAgentManifest: vi.fn((name: string) => {
      if (name === 'xan') {
        return {
          mcp: { include: ['memory', 'shell'], exclude: [], custom: {} },
          channels: { telegram: { enabled: true }, desktop: { enabled: true } },
          jobs: { morning_brief: { schedule: '0 7 * * *' } },
          router: { system_access: true },
        };
      }
      return {
        mcp: { include: ['memory'], exclude: [], custom: {} },
        channels: { desktop: { enabled: true } },
        jobs: {},
        router: { system_access: false },
      };
    }),
    getAgentMcpSection: vi.fn((name: string) => {
      if (name === 'xan') {
        return { include: ['memory', 'shell'], exclude: [], custom: {} };
      }
      return { include: ['memory'], exclude: [], custom: {} };
    }),
    EXTERNAL_SERVER_META: {
      elevenlabs: {
        description: 'ElevenLabs TTS',
        capabilities: ['tts'],
        commandCandidates: ['uvx'],
        args: ['elevenlabs-mcp'],
        requiresEnvKey: 'ELEVENLABS_API_KEY',
      },
    },
    mcpRegistry: {
      getRegistry: vi.fn(() => [
        { name: 'memory', description: 'Memory server', capabilities: ['memory'], bundled: true },
        { name: 'shell', description: 'Shell server', capabilities: ['shell'], bundled: true },
      ]),
      getForAgent: vi.fn((name: string) => {
        if (name === 'xan') {
          return [
            { name: 'memory', description: 'Memory', capabilities: ['memory'], bundled: true },
            { name: 'shell', description: 'Shell', capabilities: ['shell'], bundled: true },
          ];
        }
        return [
          { name: 'memory', description: 'Memory', capabilities: ['memory'], bundled: true },
        ];
      }),
      getServer: vi.fn((name: string) => {
        if (name === 'memory' || name === 'shell') return { name };
        return undefined;
      }),
      activateForAgent: vi.fn(),
      deactivateForAgent: vi.fn(),
      buildConfigForAgent: vi.fn(),
      needsRestart: vi.fn(() => true),
    },
  };
});

// Import after mocks
import { buildTopology, handleToggleConnection } from '../system-topology';
import { mcpRegistry } from '../mcp-registry';

describe('buildTopology', () => {
  it('returns agents with MCP, channels, and jobs', () => {
    const result = buildTopology();
    expect(result.agents).toHaveLength(2);
    expect(result.agents[0].name).toBe('xan');
    expect(result.agents[0].mcp.active).toEqual(['memory', 'shell']);
    expect(result.agents[0].channels).toHaveProperty('telegram');
    expect(result.agents[0].jobs).toHaveProperty('morning_brief');
  });

  it('includes available registered servers', () => {
    const result = buildTopology();
    expect(result.servers.some(s => s.name === 'memory')).toBe(true);
    expect(result.servers.some(s => s.name === 'shell')).toBe(true);
  });

  it('includes unavailable external servers from EXTERNAL_SERVER_META', () => {
    // Set the env key so missingKey is false and missingCommand is true
    const origKey = process.env.ELEVENLABS_API_KEY;
    process.env.ELEVENLABS_API_KEY = 'test-key';
    try {
      const result = buildTopology();
      const el = result.servers.find(s => s.name === 'elevenlabs');
      expect(el).toBeDefined();
      expect(el!.available).toBe(false);
      expect(el!.missingCommand).toBe(true);
    } finally {
      if (origKey === undefined) delete process.env.ELEVENLABS_API_KEY;
      else process.env.ELEVENLABS_API_KEY = origKey;
    }
  });

  it('includes router info for cross-agent access checks', () => {
    const result = buildTopology();
    expect(result.agents[0].router).toHaveProperty('system_access', true);
    expect(result.agents[1].router).toHaveProperty('system_access', false);
  });
});

describe('handleToggleConnection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns error for invalid agent', () => {
    const result = handleToggleConnection('../bad', 'memory', true);
    expect(result.success).toBe(false);
    expect(result.error).toContain('Invalid');
  });

  it('returns error for unknown server on activate', () => {
    const result = handleToggleConnection('xan', 'nonexistent', true);
    expect(result.success).toBe(false);
    expect(result.error).toContain('Unknown');
  });

  it('calls activateForAgent and buildConfigForAgent on enable', () => {
    const result = handleToggleConnection('xan', 'shell', true);
    expect(result.success).toBe(true);
    expect(mcpRegistry.activateForAgent).toHaveBeenCalledWith('xan', 'shell');
    expect(mcpRegistry.buildConfigForAgent).toHaveBeenCalledWith('xan');
  });

  it('calls deactivateForAgent on disable', () => {
    const result = handleToggleConnection('xan', 'shell', false);
    expect(result.success).toBe(true);
    expect(mcpRegistry.deactivateForAgent).toHaveBeenCalledWith('xan', 'shell');
  });

  it('returns needsRestart flag', () => {
    const result = handleToggleConnection('xan', 'shell', true);
    expect(result.needsRestart).toBe(true);
  });
});
