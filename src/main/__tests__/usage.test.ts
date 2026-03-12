import { describe, it, expect } from 'vitest';
import { formatTokens, formatDuration } from '../usage';

// -------------------------------------------------------------------------
// formatTokens
// -------------------------------------------------------------------------

describe('formatTokens', () => {
  it('formats millions', () => {
    expect(formatTokens(1_500_000)).toBe('1.5M');
    expect(formatTokens(2_000_000)).toBe('2.0M');
    expect(formatTokens(1_000_000)).toBe('1.0M');
  });

  it('formats thousands', () => {
    expect(formatTokens(1_500)).toBe('1.5k');
    expect(formatTokens(50_000)).toBe('50.0k');
    expect(formatTokens(1_000)).toBe('1.0k');
    expect(formatTokens(999_999)).toBe('1000.0k');
  });

  it('formats small numbers as-is', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(999)).toBe('999');
    expect(formatTokens(1)).toBe('1');
    expect(formatTokens(500)).toBe('500');
  });
});

// -------------------------------------------------------------------------
// formatDuration
// -------------------------------------------------------------------------

describe('formatDuration', () => {
  it('formats hours', () => {
    expect(formatDuration(3_600_000)).toBe('1.0h');
    expect(formatDuration(7_200_000)).toBe('2.0h');
    expect(formatDuration(5_400_000)).toBe('1.5h');
  });

  it('formats minutes', () => {
    expect(formatDuration(60_000)).toBe('1m');
    expect(formatDuration(120_000)).toBe('2m');
    expect(formatDuration(300_000)).toBe('5m');
  });

  it('formats seconds', () => {
    expect(formatDuration(1_000)).toBe('1s');
    expect(formatDuration(5_000)).toBe('5s');
    expect(formatDuration(30_000)).toBe('30s');
  });

  it('formats milliseconds', () => {
    expect(formatDuration(0)).toBe('0ms');
    expect(formatDuration(500)).toBe('500ms');
    expect(formatDuration(999)).toBe('999ms');
  });

  it('uses highest appropriate unit', () => {
    // Just above the hour threshold
    expect(formatDuration(3_600_001)).toBe('1.0h');
    // Just above the minute threshold
    expect(formatDuration(60_001)).toBe('1m');
    // Just above the second threshold
    expect(formatDuration(1_001)).toBe('1s');
  });
});
