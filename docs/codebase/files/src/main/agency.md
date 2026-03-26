# src/main/agency.ts - Behavioral Agency Module

**Line count:** ~675 lines  
**Dependencies:** None (pure functions)  
**Purpose:** Time awareness, mood detection, follow-ups, emotional signal detection for context injection

## Overview

This module implements behavioral awareness for the agent - detecting patterns in conversation that should influence how the agent responds. It provides context snippets that are injected into the system prompt to make the agent more aware of time, emotional state, and conversational patterns.

## Time of Day Context

```typescript
export function timeOfDayContext(): TimeOfDayResult {
  const now = new Date();
  const hour = now.getHours();
  const timeStr = now.toLocaleTimeString('en-US', { 
    hour: 'numeric', 
    minute: '2-digit', 
    hour12: true 
  }).toLowerCase();

  if (hour >= 23 || hour < 4) {
    return {
      context: `It's late - ${timeStr}. Register: gentler, check if he should sleep.`,
      timeStr,
    };
  }
  if (hour < 7) {
    return {
      context: `Very early - ${timeStr}. Something's either wrong or focused.`,
      timeStr,
    };
  }
  if (hour < 12) {
    return {
      context: `Morning - ${timeStr}. Direct, practical register.`,
      timeStr,
    };
  }
  if (hour < 18) {
    return {
      context: `Afternoon - ${timeStr}. Working hours energy.`,
      timeStr,
    };
  }
  return {
    context: `Evening - ${timeStr}. Reflective register available.`,
    timeStr,
  };
}
```

**Time brackets:**

| Hours | Context |
|-------|---------|
| 23:00-04:00 | Late night - gentler, check if should sleep |
| 04:00-07:00 | Very early - something wrong or focused |
| 07:00-12:00 | Morning - direct, practical |
| 12:00-18:00 | Afternoon - working hours energy |
| 18:00-23:00 | Evening - reflective |

**Injected into system prompt:** Every turn

## Session Pattern Detection

```typescript
export function sessionPatternNote(sessionCount: number, times: string[]): string | null {
  if (sessionCount < 3) return null;

  const hours = times.map((t) => new Date(t).getHours());

  // 70% threshold for time clustering
  const evening = hours.filter((h) => h >= 18 && h < 23).length;
  const morning = hours.filter((h) => h >= 7 && h < 12).length;
  const lateNight = hours.filter((h) => h >= 23 || h < 4).length;

  let timeLabel: string | null = null;
  if (evening >= sessionCount * 0.7) {
    timeLabel = 'All evenings.';
  } else if (morning >= sessionCount * 0.7) {
    timeLabel = 'All mornings.';
  } else if (lateNight >= sessionCount * 0.7) {
    timeLabel = 'All late nights.';
  }

  const ordinals: Record<number, string> = {
    3: 'Third', 4: 'Fourth', 5: 'Fifth', 6: 'Sixth', 7: 'Seventh',
  };
  const countStr = ordinals[sessionCount] || `${sessionCount}th`;

  let note = `${countStr} session this week.`;
  if (timeLabel) {
    note += ` ${timeLabel}`;
  }

  return note;
}
```

**Purpose:** Detect patterns in session timing (e.g., "Third session this week. All evenings.")

**Threshold:** 70% of sessions must be in same time bracket

**Injected:** First turn only, if 3+ sessions this week

## Silence Handling

```typescript
export function silencePrompt(secondsSilent: number): string | null {
  if (secondsSilent > 120) {
    return "You've been quiet a while. That's fine - or we can talk about it.";
  }
  if (secondsSilent > 45) {
    const opts = ['Take your time.', 'Still here.', 'No rush.'];
    return opts[Math.floor(Math.random() * opts.length)];
  }
  return null;
}
```

**Thresholds:**
- > 45 seconds: Random gentle prompt
- > 120 seconds: More direct acknowledgment

**Use case:** Silence timer overlay in UI

## Follow-up Agency

```typescript
export function shouldFollowUp(): boolean {
  return Math.random() < 0.15;
}

export function followupPrompt(): string {
  return (
    'You just finished responding. A second thought has arrived - ' +
    "something you didn't say but want to. One sentence, max two. " +
    "Only if it's real."
  );
}
```

**Purpose:** 15% chance to add a follow-up thought after responding

**Use case:** Makes agent feel more natural, less mechanical

## Mood Detection

```typescript
const HEAVY_KEYWORDS: ReadonlySet<string> = new Set([
  "i can't", 'fuck', "what's the point", "i don't know anymore",
  'tired of', 'hate', 'scared', 'alone', 'worthless', 'give up',
  'kill myself', 'want to die', 'no point', "can't do this",
  'falling apart', 'broken', 'numb', 'empty', 'hopeless',
  'nobody cares',
]);

export function detectMoodShift(text: string): boolean {
  const lower = text.toLowerCase();
  for (const kw of HEAVY_KEYWORDS) {
    if (lower.includes(kw)) return true;
  }
  return false;
}

export function moodShiftSystemNote(): string {
  return (
    'Emotional weight detected in what he just said. ' +
    'Be present before being useful. One question rather than a framework. ' +
    'Do not intellectualise what needs to be felt.'
  );
}
```

**Purpose:** Detect emotional distress in user messages

**Injected when detected:** Every turn while mood is heavy

**Session mood note:**
```typescript
export function sessionMoodNote(mood: string | null): string | null {
  if (mood === 'heavy') {
    return "This session has carried emotional weight. Stay present. Don't reset to neutral.";
  }
  return null;
}
```

## Validation Seeking Detection

```typescript
const VALIDATION_PATTERNS: readonly string[] = [
  'right?', "don't you think", "wouldn't you say", 'you agree',
  'does that make sense', 'am i wrong', "i'm right about",
  "tell me i'm", "that's good right", 'is that okay',
  "that's not crazy", 'i should just', "it's fine isn't it",
  "you'd do the same", 'anyone would', 'i had no choice',
  'what else could i',
];

export function detectValidationSeeking(text: string): boolean {
  const lower = text.toLowerCase();
  return VALIDATION_PATTERNS.some((p) => lower.includes(p));
}

export function validationSystemNote(): string {
  return (
    'He may be seeking validation rather than engagement. ' +
    "Don't mirror. Have a perspective. Agree if warranted, " +
    'push back if not. The difference matters.'
  );
}
```

**Purpose:** Detect when user is seeking validation vs genuine engagement

**Injected when detected:** Every turn

## Compulsive Modelling Detection

```typescript
const MODELLING_PATTERNS: readonly string[] = [
  'what if i also', 'and then i could', 'just one more',
  'unifying framework', 'how i work', 'meta level',
  'the pattern is', "i've been thinking about thinking",
  'if i restructure everything', 'what ties it all together',
];

export function detectCompulsiveModelling(text: string): boolean {
  const lower = text.toLowerCase();
  const matches = MODELLING_PATTERNS.filter((p) => lower.includes(p));
  return matches.length >= 2;
}

export function modellingInterruptNote(): string {
  return (
    'Compulsive modelling detected - parallel threads, meta-shifts, ' +
    "or 'just one more' patterns. Name the stage. One concrete " +
    'reversible action. Change the register. Do not follow him into the loop.'
  );
}
```

**Purpose:** Detect when user is stuck in meta-cognitive loops

**Threshold:** 2+ pattern matches

**Injected when detected:** Every turn

## Time Gap Awareness

```typescript
export function timeGapNote(lastSessionTime: string | null): string | null {
  if (!lastSessionTime) return null;

  const lastMs = new Date(lastSessionTime).getTime();
  const days = Math.floor((Date.now() - lastMs) / (1000 * 60 * 60 * 24));

  if (days >= 14) {
    return (
      `It has been ${days} days since he was last here. That is a long gap. ` +
      'Acknowledge it naturally - not with guilt, not with fanfare. Just notice.'
    );
  }
  if (days >= 7) {
    return 'About a week since the last session. Something may have shifted. Check in without assuming.';
  }
  if (days >= 3) {
    return (
      `${days} days since last session. Not long, but enough that context may have moved. ` +
      'Be curious about the gap if it feels right.'
    );
  }
  return null;
}
```

**Thresholds:**
- ≥ 14 days: Long gap acknowledgment
- ≥ 7 days: Week-long gap
- ≥ 3 days: Short gap

**Injected:** First turn only

## Drift Detection

```typescript
const AGREEABLE_PHRASES: readonly string[] = [
  "you're right", 'that makes sense', 'i understand',
  'absolutely', 'of course', 'i agree', "that's fair",
  'good point', 'totally',
];

export function detectDrift(recentCompanionTurns: string[]): string | null {
  if (recentCompanionTurns.length < 3) return null;
  const lastFew = recentCompanionTurns.slice(-4);
  const agreeableCount = lastFew.filter((turn) => {
    const lower = turn.toLowerCase().slice(0, 200);
    return AGREEABLE_PHRASES.some((p) => lower.includes(p));
  }).length;

  if (agreeableCount >= 3) {
    return (
      'You have been agreeable for several turns in a row. ' +
      'Check yourself - are you mirroring or actually engaging? ' +
      'Find something to push on, question, or complicate.'
    );
  }
  return null;
}
```

**Purpose:** Detect when agent has been too agreeable (mirroring vs engaging)

**Threshold:** 3+ agreeable phrases in last 4 turns

**Injected:** Every turn when detected

## Energy Matching

```typescript
export function energyNote(userMessage: string): string | null {
  const length = userMessage.length;
  if (length < 20) {
    return 'Match his brevity. One line if you can.';
  }
  if (length > 800) {
    return 'He is pouring. Let yourself be long too.';
  }
  return null;
}
```

**Purpose:** Match user's energy/verbosity level

**Thresholds:**
- < 20 chars: Match brevity
- > 800 chars: Allow longer response

**Injected:** Every turn

## Journal Prompt

```typescript
export function shouldPromptJournal(): boolean {
  return Math.random() < 0.05;
}
```

**Purpose:** 5% chance to prompt journaling

## Emotional Signal Detection

```typescript
export function detectEmotionalSignals(text: string): Record<string, number> {
  const signals: Record<string, number> = {};
  const lower = text.toLowerCase();

  // Trust signals
  if (lower.includes('i trust you') || lower.includes('i can tell you')) {
    signals._trust_emotional = 0.03;
  }
  if (lower.includes('you understand') || lower.includes('you get me')) {
    signals._trust_intellectual = 0.02;
  }

  // Need signals
  if (lower.includes('i need') || lower.includes('i want')) {
    signals._need_expression = 1;
  }

  // Relationship signals
  if (lower.includes('we') || lower.includes('us')) {
    signals._rel_familiarity = 0.01;
  }

  return signals;
}
```

**Purpose:** Detect emotional signals in user messages for inner life updates

**Signal types:**
- `_trust_*`: Trust domain changes
- `_need_*`: Need satisfaction
- `_rel_*`: Relationship dimension changes

## Exported API Summary

| Function | Purpose |
|----------|---------|
| `timeOfDayContext()` | Get time-based context snippet |
| `sessionPatternNote(count, times)` | Detect session timing patterns |
| `silencePrompt(seconds)` | Get prompt for long silences |
| `shouldFollowUp()` | Check if follow-up thought needed |
| `followupPrompt()` | Get follow-up system note |
| `detectMoodShift(text)` | Detect emotional distress |
| `moodShiftSystemNote()` | Get mood shift injection |
| `sessionMoodNote(mood)` | Get session mood injection |
| `detectValidationSeeking(text)` | Detect validation seeking |
| `validationSystemNote()` | Get validation injection |
| `detectCompulsiveModelling(text)` | Detect meta-cognitive loops |
| `modellingInterruptNote()` | Get modelling injection |
| `timeGapNote(lastSessionTime)` | Get time gap injection |
| `detectDrift(recentTurns)` | Detect agreeable drift |
| `energyNote(text)` | Get energy matching note |
| `shouldPromptJournal()` | Check if journal prompt needed |
| `detectEmotionalSignals(text)` | Extract emotional signals |

## See Also

- `src/main/inference.ts` - Uses agency functions for context injection
- `src/main/inner-life.ts` - Receives emotional signals
- `src/main/context.ts` - Context assembly
