# src/main/thinking.ts - Adaptive Thinking Classifier

**Line count:** ~130 lines  
**Dependencies:** None (pure functions)  
**Purpose:** Classify message complexity to set Claude CLI inference effort level

## Overview

This module implements a simple heuristic classifier that determines how much "thinking" effort Claude should apply to a message. It runs in <1ms with no ML or API calls. The classifier helps optimize cost and latency by using lower effort for simple messages and higher effort for complex ones.

## Effort Levels

```typescript
export type EffortLevel = 'low' | 'medium' | 'high';
```

**Mapping to Claude models:**
- `low` → haiku (fast, cheap)
- `medium` → sonnet (balanced)
- `high` → opus (slow, expensive, most capable)

## HIGH Effort Signals

### Philosophical Keywords

```typescript
const PHILOSOPHICAL_KEYWORDS = [
  'meaning', 'purpose', 'why do i', 'what does it mean',
  'identity', 'existence', 'consciousness', 'feel like',
  'struggling with', 'what matters', 'who am i',
  "what's the point", 'nature of', 'free will',
];
```

**Purpose:** Detect existential/philosophical questions

### Vulnerability Markers

```typescript
const VULNERABILITY_MARKERS = [
  "i'm scared", "i don't know who", "i've been thinking",
  "can't stop", 'hurts', 'afraid', 'ashamed', 'lost',
  "i'm not okay", "i don't know anymore", 'falling apart',
  'i need to tell you', "haven't told anyone",
  'the truth is', "i've been crying",
];
```

**Purpose:** Detect emotional vulnerability - these ALWAYS get high effort

### Meta-Conversation

```typescript
const META_CONVERSATION = [
  'what do you think about us', 'are you real',
  'do you actually', 'what are you', 'are we',
  'do you feel', 'do you remember',
];
```

**Purpose:** Detect questions about the agent itself

### Complex Reasoning

```typescript
const COMPLEX_REASONING = [
  'because', 'therefore', 'on the other hand', 'but what if',
  'the problem is', 'i realize', "i've realized",
  'which means', 'the thing is', "what i'm trying to say",
  "it's complicated", 'i keep coming back to',
];
```

**Purpose:** Detect complex reasoning patterns

## LOW Effort Signals

### Greetings

```typescript
const GREETINGS = new Set([
  'hey', 'hi', 'hello', 'morning', 'yo', 'sup', 'heya',
  'good morning', 'good evening', 'good night', 'gn',
  'evening', 'night', 'hiya',
]);
```

### Acknowledgments

```typescript
const ACKNOWLEDGMENTS = new Set([
  'ok', 'okay', 'sure', 'got it', 'thanks', 'thank you',
  'cool', 'nice', 'lol', 'lmao', 'haha', 'yep', 'yea',
  'yeah', 'yes', 'no', 'nah', 'nope', 'k', 'kk', 'bet',
  'word', 'true', 'fair', 'right', 'ah', 'oh', 'hmm',
  'mm', 'mhm', 'alright',
]);
```

### Simple Question Prefixes

```typescript
const SIMPLE_QUESTION_PREFIXES = [
  'what time', "how's the weather", 'what should i eat',
  'play music', 'set a timer', 'remind me', 'turn on',
  'turn off', "what's the date", 'what day is it',
];
```

## Helper Functions

```typescript
function countQuestions(text: string): number {
  return (text.match(QUESTION_RE) || []).length;
}

function hasAny(text: string, phrases: string[]): boolean {
  return phrases.some((p) => text.includes(p));
}

function contextIsDeep(recentContext?: string[]): boolean {
  if (!recentContext || recentContext.length === 0) return false;
  const last3 = recentContext.slice(-3);
  const longTurns = last3.filter((t) => t.length > 300).length;
  return longTurns >= 2;
}
```

**contextIsDeep:** Returns true if 2+ of last 3 turns were >300 chars

## Main Classifier

```typescript
export function classifyEffort(
  userMessage: string,
  recentContext?: string[],
): EffortLevel {
  const text = userMessage.trim();
  const lower = text.toLowerCase();
  const length = text.length;

  // -- Check LOW signals first (short-circuit for fast responses) --

  if (length < 30) {
    // Don't fast-path low if vulnerability markers are present
    // ("hey I'm scared", "hi I'm not okay" need high effort, not low)
    if (!hasAny(lower, VULNERABILITY_MARKERS)) {
      const words = new Set(lower.replace(/[!.,?]+$/, '').split(/\s+/));
      for (const w of words) {
        if (GREETINGS.has(w)) return 'low';
      }
      const stripped = lower.replace(/[!.,?]+$/, '').trim();
      if (ACKNOWLEDGMENTS.has(stripped)) return 'low';
    }
  }

  if (length < 60 && hasAny(lower, SIMPLE_QUESTION_PREFIXES)) {
    return 'low';
  }

  // -- Check HIGH signals --

  let highScore = 0;

  if (length > 300) highScore += 2;
  if (countQuestions(text) > 2) highScore += 2;
  if (hasAny(lower, PHILOSOPHICAL_KEYWORDS)) highScore += 2;
  if (hasAny(lower, VULNERABILITY_MARKERS)) highScore += 3;
  if (hasAny(lower, META_CONVERSATION)) highScore += 2;

  const reasoningHits = COMPLEX_REASONING.filter((p) => lower.includes(p)).length;
  if (reasoningHits >= 2) highScore += 2;
  else if (reasoningHits === 1) highScore += 1;

  if (contextIsDeep(recentContext)) highScore += 1;

  if (highScore >= 3) return 'high';

  return 'medium';
}
```

**Scoring:**

| Signal | Score |
|--------|-------|
| Length > 300 chars | +2 |
| > 2 questions | +2 |
| Philosophical keywords | +2 |
| Vulnerability markers | +3 |
| Meta-conversation | +2 |
| Complex reasoning (2+ hits) | +2 |
| Complex reasoning (1 hit) | +1 |
| Deep context | +1 |

**Thresholds:**
- `highScore >= 3` → `'high'`
- Otherwise → `'medium'`

**Low effort short-circuit:**
- Length < 30 chars AND (greeting OR acknowledgment) → `'low'`
- Length < 60 chars AND simple question → `'low'`
- **Exception:** Vulnerability markers override low effort

## Usage in Inference

```typescript
// In inference.ts
const effort = config.ADAPTIVE_EFFORT 
  ? classifyEffort(userMessage) 
  : (config.CLAUDE_EFFORT as EffortLevel);

const model = effort === 'high' || effort === 'max' 
  ? 'claude-opus-4-6' 
  : config.CLAUDE_MODEL || DEFAULT_MODEL;
```

## Exported API

| Function | Purpose |
|----------|---------|
| `classifyEffort(userMessage, recentContext)` | Classify effort level |
| `EffortLevel` | Type: 'low' | 'medium' | 'high' |

## See Also

- `src/main/inference.ts` - Uses classifyEffort for model selection
- `src/main/config.ts` - ADAPTIVE_EFFORT configuration
