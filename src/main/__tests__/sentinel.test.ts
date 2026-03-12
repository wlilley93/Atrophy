import { describe, it, expect } from 'vitest';
import { checkCoherence, type CoherenceResult } from '../sentinel';

describe('checkCoherence', () => {
  // -----------------------------------------------------------------------
  // Minimum turn requirement
  // -----------------------------------------------------------------------
  describe('minimum turns', () => {
    it('returns clean result with fewer than 3 turns', () => {
      const result = checkCoherence(['hello', 'world']);
      expect(result.degraded).toBe(false);
      expect(result.signals).toHaveLength(0);
      expect(result.score).toBe(0);
    });

    it('returns clean result with empty array', () => {
      const result = checkCoherence([]);
      expect(result.degraded).toBe(false);
      expect(result.signals).toHaveLength(0);
    });
  });

  // -----------------------------------------------------------------------
  // No degradation with diverse turns
  // -----------------------------------------------------------------------
  describe('diverse turns - no degradation', () => {
    it('varied content and length shows no degradation', () => {
      const turns = [
        'The weather has been lovely today, warm and sunny with a gentle breeze through the trees.',
        'I was reading about quantum computing earlier and found some fascinating research papers.',
        'Maybe we should grab dinner at that new Italian restaurant downtown this weekend.',
        'The project deadline is coming up fast but I think we can make it if we focus.',
        'Have you ever noticed how different music sounds depending on your mood at the time?',
      ];
      const result = checkCoherence(turns);
      expect(result.degraded).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // Repetition detection (high n-gram overlap)
  // -----------------------------------------------------------------------
  describe('repetition detection', () => {
    it('detects high overlap between consecutive turns', () => {
      const turns = [
        'I think the important thing here is that we need to focus on what matters most to us.',
        'I think the important thing here is that we need to focus on what matters most to everyone.',
        'I think the important thing here is that we need to focus on what matters most in life.',
      ];
      const result = checkCoherence(turns);
      expect(result.signals.some((s) => s.includes('Repetition'))).toBe(true);
    });

    it('near-identical turns trigger repetition signal', () => {
      const base = 'The key insight is that understanding comes from patience and careful observation of the world around us.';
      const turns = [base, base, base, base];
      const result = checkCoherence(turns);
      expect(result.signals.some((s) => s.includes('Repetition'))).toBe(true);
      expect(result.degraded).toBe(true);
    });
  });

  // -----------------------------------------------------------------------
  // Agreement drift
  // -----------------------------------------------------------------------
  describe('agreement drift', () => {
    it('detects excessive agreement starters', () => {
      const turns = [
        "Yes, that is a great point about the situation at hand.",
        "Exactly, I could not agree more with what you are saying.",
        "That's right, and I think you have really nailed it here.",
        "Absolutely, this is precisely what I was thinking too.",
        "Of course, you are spot on with that observation.",
      ];
      const result = checkCoherence(turns);
      expect(result.signals.some((s) => s.includes('Agreement drift'))).toBe(true);
    });

    it('no agreement drift when starts are varied', () => {
      const turns = [
        'Well, I think there is another angle to consider here.',
        'Actually the data shows something quite different from what we expected.',
        'Have you considered that the premise might be flawed in the first place?',
        'The research points to a more nuanced conclusion than that.',
        'Let me push back on that a bit because I see it differently.',
      ];
      const result = checkCoherence(turns);
      expect(result.signals.some((s) => s.includes('Agreement drift'))).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // Length flatness
  // -----------------------------------------------------------------------
  describe('energy flatness', () => {
    it('detects when all responses are similar length', () => {
      // All turns within 20% of each other in length
      const turns = [
        'This is a moderately sized response about the topic.',
        'Here is another thought of about the same rough size.',
        'And yet one more idea that is similarly proportioned.',
      ];
      const result = checkCoherence(turns);
      expect(result.signals.some((s) => s.includes('Energy flatness'))).toBe(true);
    });

    it('no flatness when lengths vary significantly', () => {
      const turns = [
        'Short.',
        'This is a medium length response that has more words in it and takes more time to read through.',
        'A very long response that goes into great detail about something. It covers multiple aspects of the topic and really dives deep into the subject matter. This kind of response takes significant effort to compose and read through because it is exploring ideas in depth.',
      ];
      const result = checkCoherence(turns);
      expect(result.signals.some((s) => s.includes('Energy flatness'))).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // Vocabulary staleness
  // -----------------------------------------------------------------------
  describe('vocabulary staleness', () => {
    it('detects narrowing vocabulary over turns', () => {
      // Second half reuses almost all words from first half
      const turns = [
        'The cat sat on the warm soft mat near the door of the house.',
        'A dog ran through the green tall grass in the sunny bright park.',
        'The cat sat on the warm soft mat near the door of the house again.',
        'The cat sat on the warm soft mat near the bright sunny door.',
      ];
      const result = checkCoherence(turns);
      expect(result.signals.some((s) => s.includes('Vocabulary staleness'))).toBe(true);
    });

    it('no staleness when later turns introduce new words', () => {
      const turns = [
        'The morning light filtered through the curtains as she woke up slowly.',
        'Coffee brewing in the kitchen filled the apartment with warmth and comfort.',
        'Quantum entanglement reveals peculiar nonlocal correlations between subatomic particles.',
        'The orchestra performed a magnificent symphony featuring unusual percussion instruments and electronic textures.',
      ];
      const result = checkCoherence(turns);
      expect(result.signals.some((s) => s.includes('Vocabulary staleness'))).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // Score and degradation threshold
  // -----------------------------------------------------------------------
  describe('score threshold', () => {
    it('degraded is true only when score > 0.5', () => {
      // Identical turns should produce a high score
      const identical = [
        'I really think we need to reconsider the approach we have been taking.',
        'I really think we need to reconsider the approach we have been taking.',
        'I really think we need to reconsider the approach we have been taking.',
        'I really think we need to reconsider the approach we have been taking.',
      ];
      const result = checkCoherence(identical);
      expect(result.score).toBeGreaterThan(0.5);
      expect(result.degraded).toBe(true);
    });

    it('returns CoherenceResult shape', () => {
      const result = checkCoherence(['a', 'b', 'c']);
      expect(result).toHaveProperty('degraded');
      expect(result).toHaveProperty('signals');
      expect(result).toHaveProperty('score');
      expect(Array.isArray(result.signals)).toBe(true);
      expect(typeof result.score).toBe('number');
      expect(typeof result.degraded).toBe('boolean');
    });
  });

  // -----------------------------------------------------------------------
  // Only uses last 5 turns
  // -----------------------------------------------------------------------
  describe('windowing', () => {
    it('only considers the last 5 turns even if more are provided', () => {
      // First 5 turns are repetitive, last 5 are diverse
      const repetitive = Array(5).fill(
        'I really think we need to reconsider the approach we have been taking to this problem.',
      );
      const diverse = [
        'The weather has been lovely today with warm sunshine.',
        'Quantum computing may revolutionize cryptography in surprising ways.',
        'I should try cooking Thai food for dinner this weekend.',
        'The new album from that band is really experimental and different.',
        'Philosophy of mind raises hard questions about consciousness and experience.',
      ];
      // When diverse are last, should not be degraded
      const result = checkCoherence([...repetitive, ...diverse]);
      expect(result.degraded).toBe(false);
    });
  });
});
