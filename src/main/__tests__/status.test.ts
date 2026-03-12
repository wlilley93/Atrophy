import { describe, it, expect } from 'vitest';
import { detectAwayIntent } from '../status';

// -------------------------------------------------------------------------
// detectAwayIntent
// -------------------------------------------------------------------------

describe('detectAwayIntent', () => {
  describe('detects away patterns', () => {
    const patterns = [
      ['going to bed', 'going to bed'],
      ['I am heading out now', 'heading out'],
      ['gotta go, see you later', 'gotta go'],
      ['goodnight everyone', 'goodnight'],
      ["i'm out", "i'm out"],
      ['brb getting coffee', 'brb'],
      ['talk later about this', 'talk later'],
      ['calling it a night', 'calling it'],
      ['stepping away for a bit', 'stepping away'],
      ['shutting down the computer', 'shutting down'],
    ];

    for (const [input, expected] of patterns) {
      it(`"${input}" detects "${expected}"`, () => {
        const result = detectAwayIntent(input);
        expect(result).not.toBeNull();
        expect(result!.toLowerCase()).toBe(expected.toLowerCase());
      });
    }
  });

  describe('returns null for non-away messages', () => {
    const messages = [
      'How are you doing today?',
      'Tell me about the weather',
      'I am working on a project',
      'What should we have for lunch?',
      'The code is looking good',
    ];

    for (const msg of messages) {
      it(`"${msg}" -> null`, () => {
        expect(detectAwayIntent(msg)).toBeNull();
      });
    }
  });

  it('is case insensitive', () => {
    expect(detectAwayIntent('GOING TO BED')).not.toBeNull();
    expect(detectAwayIntent('Goodnight')).not.toBeNull();
    expect(detectAwayIntent('BRB')).not.toBeNull();
  });
});
