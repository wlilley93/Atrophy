import { describe, it, expect } from 'vitest';
import { classifyEffort, type EffortLevel } from '../thinking';

describe('classifyEffort', () => {
  // -----------------------------------------------------------------------
  // LOW effort - greetings
  // -----------------------------------------------------------------------
  describe('greetings -> low', () => {
    const greetings = ['hey', 'Hi', 'hello', 'Morning', 'yo', 'sup', 'heya', 'good morning', 'gn', 'hiya'];

    for (const g of greetings) {
      it(`"${g}" -> low`, () => {
        expect(classifyEffort(g)).toBe('low');
      });
    }

    it('greeting with trailing punctuation', () => {
      expect(classifyEffort('hey!')).toBe('low');
      expect(classifyEffort('hello.')).toBe('low');
    });
  });

  // -----------------------------------------------------------------------
  // LOW effort - acknowledgments
  // -----------------------------------------------------------------------
  describe('acknowledgments -> low', () => {
    const acks = ['ok', 'okay', 'sure', 'got it', 'thanks', 'cool', 'lol', 'yep', 'nah', 'bet', 'true', 'alright'];

    for (const a of acks) {
      it(`"${a}" -> low`, () => {
        expect(classifyEffort(a)).toBe('low');
      });
    }

    it('acknowledgment with trailing punctuation', () => {
      expect(classifyEffort('ok!')).toBe('low');
      expect(classifyEffort('thanks.')).toBe('low');
    });
  });

  // -----------------------------------------------------------------------
  // LOW effort - simple questions
  // -----------------------------------------------------------------------
  describe('simple questions -> low', () => {
    it('what time is it', () => {
      expect(classifyEffort('what time is it')).toBe('low');
    });

    it('set a timer for 5 minutes', () => {
      expect(classifyEffort('set a timer for 5 minutes')).toBe('low');
    });

    it('remind me to call mom', () => {
      expect(classifyEffort('remind me to call mom')).toBe('low');
    });
  });

  // -----------------------------------------------------------------------
  // MEDIUM effort - moderate complexity
  // -----------------------------------------------------------------------
  describe('medium complexity -> medium', () => {
    it('casual question without deep signals', () => {
      expect(classifyEffort('what do you think about this weather we have been having lately')).toBe('medium');
    });

    it('moderate length without philosophical keywords', () => {
      expect(classifyEffort('I was thinking about picking up a new hobby, maybe woodworking or painting')).toBe('medium');
    });

    it('single complex reasoning marker is not enough for high', () => {
      expect(classifyEffort('because I think that would work better for the project')).toBe('medium');
    });
  });

  // -----------------------------------------------------------------------
  // HIGH effort - philosophical messages
  // -----------------------------------------------------------------------
  describe('philosophical messages -> high', () => {
    it('message about meaning and purpose with meta elements', () => {
      // 'meaning' + 'existence' + 'consciousness' from PHILOSOPHICAL, 'do you feel' from META = highScore >= 4
      expect(classifyEffort('What is the meaning of existence, consciousness, and do you feel any of it?')).toBe('high');
    });

    it('identity question with meta-conversation', () => {
      expect(classifyEffort('Who am I really and are you real or just a simulation of understanding?')).toBe('high');
    });

    it('deep philosophical question with multiple signals', () => {
      // 'nature of' + 'free will' from PHILOSOPHICAL, 'because' + 'i realize' from COMPLEX_REASONING
      expect(classifyEffort('I keep thinking about the nature of free will because I realize none of our choices may matter')).toBe('high');
    });
  });

  // -----------------------------------------------------------------------
  // HIGH effort - vulnerability markers
  // -----------------------------------------------------------------------
  describe('vulnerability markers -> high', () => {
    it("'i'm scared' triggers high", () => {
      expect(classifyEffort("I'm scared and I don't know what to do about it")).toBe('high');
    });

    it("'falling apart' triggers high", () => {
      expect(classifyEffort("Everything is falling apart and I can't stop it")).toBe('high');
    });

    it("'haven't told anyone' triggers high", () => {
      expect(classifyEffort("I haven't told anyone this but I need to talk about it")).toBe('high');
    });

    it("'i'm not okay' triggers high", () => {
      expect(classifyEffort("Honestly I'm not okay and I've been crying a lot lately")).toBe('high');
    });
  });

  // -----------------------------------------------------------------------
  // HIGH effort - long messages
  // -----------------------------------------------------------------------
  describe('long messages -> high', () => {
    it('message over 300 chars with reasoning markers scores high', () => {
      const longMsg = 'I have been thinking about this for a while now and I realize that ' +
        'the problem is much deeper than I initially thought. On the other hand, there are ' +
        'aspects of this situation that I keep coming back to, which means that maybe the ' +
        'answer has been staring me in the face the whole time. The thing is, it is complicated ' +
        'and I am not sure how to untangle all of these threads.';
      expect(longMsg.length).toBeGreaterThan(300);
      expect(classifyEffort(longMsg)).toBe('high');
    });
  });

  // -----------------------------------------------------------------------
  // HIGH effort - multiple question marks
  // -----------------------------------------------------------------------
  describe('multiple questions -> high', () => {
    it('3+ question marks with philosophical content triggers high', () => {
      expect(classifyEffort('What do you think about us? Are you real? Do you feel anything?')).toBe('high');
    });
  });

  // -----------------------------------------------------------------------
  // Context influence
  // -----------------------------------------------------------------------
  describe('context influence', () => {
    it('deep context can push a medium message toward high', () => {
      const deepContext = [
        'a'.repeat(400),
        'b'.repeat(400),
        'c'.repeat(400),
      ];
      // A message with one reasoning marker and deep context
      const msg = 'I realize that maybe the issue is something else entirely, because I have been looking at it wrong';
      expect(classifyEffort(msg, deepContext)).toBe('high');
    });

    it('shallow context does not inflate score', () => {
      const shallowContext = ['hi', 'hello', 'ok'];
      expect(classifyEffort('how are you doing today', shallowContext)).toBe('medium');
    });
  });

  // -----------------------------------------------------------------------
  // Edge cases
  // -----------------------------------------------------------------------
  describe('edge cases', () => {
    it('empty string -> medium (no low signals, no high signals)', () => {
      expect(classifyEffort('')).toBe('medium');
    });

    it('whitespace only -> medium', () => {
      expect(classifyEffort('   ')).toBe('medium');
    });

    it('single character -> medium (not a greeting or ack)', () => {
      expect(classifyEffort('x')).toBe('medium');
    });
  });
});
