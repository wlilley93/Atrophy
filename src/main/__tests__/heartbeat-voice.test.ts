import { describe, it, expect, vi } from 'vitest';

vi.mock('../config', () => ({
  getConfig: () => ({}),
  BUNDLE_ROOT: '/tmp',
}));
vi.mock('../memory', () => ({
  getDb: () => ({ prepare: () => ({ get: () => null }) }),
  getActiveThreads: () => [],
  getRecentSummaries: () => [],
  getRecentObservations: () => [],
  getLastInteractionTime: () => null,
  getLastCliSessionId: () => null,
  logHeartbeat: vi.fn(),
}));
vi.mock('../inference', () => ({
  streamInference: vi.fn(),
}));
vi.mock('../context', () => ({
  loadSystemPrompt: () => '',
}));
vi.mock('../status', () => ({
  isAway: () => false,
  isMacIdle: () => false,
}));
vi.mock('../notify', () => ({
  sendNotification: vi.fn(),
}));
vi.mock('../queue', () => ({
  queueMessage: vi.fn(),
}));
vi.mock('../telegram', () => ({
  sendMessage: vi.fn(),
  sendVoiceNote: vi.fn(),
  sendButtons: vi.fn(),
  sendPhoto: vi.fn(),
  pollCallback: vi.fn(),
}));
vi.mock('../tts', () => ({
  synthesise: vi.fn(),
  isElevenLabsExhausted: () => false,
}));
vi.mock('../audio-convert', () => ({
  convertToOgg: vi.fn(),
  cleanupFiles: vi.fn(),
}));
vi.mock('./generate-avatar', () => ({
  getFalKey: () => 'test-key',
  getReferenceImages: () => [],
  uploadToFal: vi.fn(),
  falGenerate: vi.fn(),
  downloadImage: vi.fn(),
  loadAgentManifest: () => ({}),
}));
vi.mock('./index', () => ({
  registerJob: vi.fn(),
  activeHoursGate: vi.fn(),
}));
vi.mock('../logger', () => ({
  createLogger: () => ({ warn: vi.fn(), info: vi.fn(), debug: vi.fn(), error: vi.fn() }),
}));

// Import the pure parsing function - no mocks needed
const { parseHeartbeatResponse } = await import('../jobs/heartbeat');

describe('parseHeartbeatResponse', () => {
  it('parses REACH_OUT prefix', () => {
    const result = parseHeartbeatResponse('[REACH_OUT] Hey, thought of you');
    expect(result).toEqual({ type: 'REACH_OUT', message: 'Hey, thought of you' });
  });

  it('parses VOICE_NOTE prefix', () => {
    const result = parseHeartbeatResponse('[VOICE_NOTE] I was just thinking about our conversation');
    expect(result).toEqual({ type: 'VOICE_NOTE', message: 'I was just thinking about our conversation' });
  });

  it('parses SELFIE prefix', () => {
    const result = parseHeartbeatResponse('[SELFIE] Thinking of you while reading in the sun');
    expect(result).toEqual({ type: 'SELFIE', message: 'Thinking of you while reading in the sun' });
  });

  it('parses HEARTBEAT_OK prefix', () => {
    const result = parseHeartbeatResponse('[HEARTBEAT_OK] Too soon to reach out');
    expect(result).toEqual({ type: 'HEARTBEAT_OK', message: 'Too soon to reach out' });
  });

  it('parses SUPPRESS prefix', () => {
    const result = parseHeartbeatResponse('[SUPPRESS] User is away');
    expect(result).toEqual({ type: 'SUPPRESS', message: 'User is away' });
  });

  it('parses ASK prefix with options', () => {
    const result = parseHeartbeatResponse('[ASK] Should I check in about the project? | Yes | No | Later');
    expect(result).toEqual({
      type: 'ASK',
      message: 'Should I check in about the project?',
      options: ['Yes', 'No', 'Later'],
    });
  });

  it('returns UNKNOWN for unrecognized format', () => {
    const result = parseHeartbeatResponse('Just some random text');
    expect(result).toEqual({ type: 'UNKNOWN', message: 'Just some random text' });
  });

  it('handles whitespace around prefix', () => {
    const result = parseHeartbeatResponse('  [REACH_OUT]   Hello there  ');
    expect(result).toEqual({ type: 'REACH_OUT', message: 'Hello there' });
  });
});
