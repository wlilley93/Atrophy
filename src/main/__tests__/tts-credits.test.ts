import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../config', () => ({
  getConfig: () => ({}),
}));
vi.mock('../logger', () => ({
  createLogger: () => ({ warn: vi.fn(), info: vi.fn(), debug: vi.fn(), error: vi.fn() }),
}));

const { markElevenLabsExhausted, isElevenLabsExhausted, resetElevenLabsStatus, COOLDOWN_MS } =
  await import('../tts');

describe('ElevenLabs credit exhaustion', () => {
  beforeEach(() => {
    resetElevenLabsStatus();
  });

  it('starts as not exhausted', () => {
    expect(isElevenLabsExhausted()).toBe(false);
  });

  it('marks exhausted after call', () => {
    markElevenLabsExhausted();
    expect(isElevenLabsExhausted()).toBe(true);
  });

  it('auto-resets after cooldown period', () => {
    const originalNow = Date.now;
    const startTime = Date.now();

    markElevenLabsExhausted();
    expect(isElevenLabsExhausted()).toBe(true);

    // Simulate time passing beyond cooldown
    Date.now = () => startTime + COOLDOWN_MS + 1000;
    expect(isElevenLabsExhausted()).toBe(false);

    Date.now = originalNow;
  });

  it('can be manually reset', () => {
    markElevenLabsExhausted();
    resetElevenLabsStatus();
    expect(isElevenLabsExhausted()).toBe(false);
  });
});
