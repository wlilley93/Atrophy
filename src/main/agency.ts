/**
 * Behavioral agency - time awareness, mood detection, follow-ups, emotional signals.
 * Port of core/agency.py.
 */

// ---------------------------------------------------------------------------
// Time of day
// ---------------------------------------------------------------------------

export interface TimeOfDayResult {
  context: string;
  timeStr: string;
}

export function timeOfDayContext(): TimeOfDayResult {
  const now = new Date();
  const hour = now.getHours();
  const timeStr = now
    .toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
    .toLowerCase();

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

// ---------------------------------------------------------------------------
// Session patterns
// ---------------------------------------------------------------------------

export function sessionPatternNote(sessionCount: number, times: string[]): string | null {
  if (sessionCount < 3) return null;

  const hours = times.map((t) => new Date(t).getHours());
  const isEvening = hours.every((h) => h >= 18);
  const isMorning = hours.every((h) => h >= 6 && h < 12);
  const isLate = hours.every((h) => h >= 23 || h < 4);

  if (isEvening) return `${sessionCount} sessions this week. All evenings.`;
  if (isMorning) return `${sessionCount} sessions this week. All mornings.`;
  if (isLate) return `${sessionCount} sessions this week. All late night.`;
  return null;
}

// ---------------------------------------------------------------------------
// Silence handling
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Follow-up agency
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Mood detection
// ---------------------------------------------------------------------------

const HEAVY_KEYWORDS: ReadonlySet<string> = new Set([
  "i can't",
  'fuck',
  "what's the point",
  "i don't know anymore",
  'tired of',
  'hate',
  'scared',
  'alone',
  'worthless',
  'give up',
  'kill myself',
  'want to die',
  'no point',
  "can't do this",
  'falling apart',
  'broken',
  'numb',
  'empty',
  'hopeless',
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

export function sessionMoodNote(mood: string | null): string | null {
  if (mood === 'heavy') {
    return "This session has carried emotional weight. Stay present. Don't reset to neutral.";
  }
  return null;
}

// ---------------------------------------------------------------------------
// Validation seeking
// ---------------------------------------------------------------------------

const VALIDATION_PATTERNS: readonly string[] = [
  'right?',
  "don't you think",
  "wouldn't you say",
  'you agree',
  'does that make sense',
  'am i wrong',
  "i'm right about",
  "tell me i'm",
  "that's good right",
  'is that okay',
  "that's not crazy",
  'i should just',
  "it's fine isn't it",
  "you'd do the same",
  'anyone would',
  'i had no choice',
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

// ---------------------------------------------------------------------------
// Compulsive modelling
// ---------------------------------------------------------------------------

const MODELLING_PATTERNS: readonly string[] = [
  'what if i also',
  'and then i could',
  'just one more',
  'unifying framework',
  'how i work',
  'meta level',
  'the pattern is',
  "i've been thinking about thinking",
  'if i restructure everything',
  'what ties it all together',
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

// ---------------------------------------------------------------------------
// Time gap awareness
// ---------------------------------------------------------------------------

export function timeGapNote(lastSessionTime: string | null): string | null {
  if (!lastSessionTime) return null;

  let lastMs: number;
  try {
    lastMs = new Date(lastSessionTime).getTime();
    if (isNaN(lastMs)) return null;
  } catch {
    return null;
  }

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

// ---------------------------------------------------------------------------
// Drift detection
// ---------------------------------------------------------------------------

const AGREEABLE_PHRASES: readonly string[] = [
  "you're right",
  'that makes sense',
  'i understand',
  'absolutely',
  'of course',
  'i agree',
  "that's fair",
  'good point',
  'totally',
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

// ---------------------------------------------------------------------------
// Energy matching
// ---------------------------------------------------------------------------

export function energyNote(userMessage: string): string | null {
  const length = userMessage.trim().length;
  if (length < 20) {
    return 'Short message. Match the energy - keep your response tight. A sentence or two.';
  }
  if (length > 800) {
    return 'Long message - he is working something out. Give it depth. Meet the energy, don\'t summarise it.';
  }
  return null;
}

// ---------------------------------------------------------------------------
// Journal prompting
// ---------------------------------------------------------------------------

export function shouldPromptJournal(): boolean {
  return Math.random() < 0.1;
}

// ---------------------------------------------------------------------------
// Emotional signal detection
// ---------------------------------------------------------------------------

interface SignalDelta {
  [key: string]: number;
}

const VULNERABILITY_PHRASES: readonly string[] = [
  'i feel', "i'm scared", "i'm afraid", "i don't know if",
  'it hurts', 'i miss', 'i need', "i've been struggling",
  "i can't stop thinking", "i haven't told anyone",
  'this is hard to say', 'honestly', 'the truth is',
  "i'm not okay", "i've been crying", "i'm lonely",
];

const DISMISSIVE_PHRASES: readonly string[] = [
  'fine', 'whatever', 'idk', "doesn't matter", 'i guess',
  'sure', 'okay', 'nvm', 'nevermind', 'forget it',
  'not really', 'who cares',
];

const HELP_SEEKING: readonly string[] = [
  'can you help', 'i need help', 'how do i', 'what should i',
  'could you', 'any advice', 'what do you think i should',
];

const CREATIVE_PHRASES: readonly string[] = [
  'i wrote', 'i made', "i've been working on", 'check this out',
  "here's something", 'i want to show you', 'been building',
  'started writing', 'new project', 'draft',
];

const DEFLECTION_PHRASES: readonly string[] = [
  'anyway', 'moving on', "let's talk about something else",
  "that's enough about", "doesn't matter anyway",
  'forget i said', "it's nothing",
];

const PLAYFUL_MARKERS: readonly string[] = [
  'haha', 'lol', 'lmao', '\u{1F602}', '\u{1F604}',
];

export function detectEmotionalSignals(text: string): SignalDelta {
  const lower = text.toLowerCase().trim();
  const length = text.trim().length;
  const deltas: SignalDelta = {};

  function add(key: string, value: number): void {
    deltas[key] = (deltas[key] || 0) + value;
  }

  // Long, thoughtful message
  if (length > 400) {
    add('curiosity', 0.1);
    add('connection', 0.05);
  }

  // Short dismissive reply
  if (length < 30 && DISMISSIVE_PHRASES.some((p) => lower.includes(p))) {
    add('connection', -0.1);
    add('frustration', 0.1);
  }

  // Vulnerability / openness
  if (VULNERABILITY_PHRASES.some((p) => lower.includes(p))) {
    add('connection', 0.15);
    add('warmth', 0.1);
  }

  // Asking for help (trust signal)
  if (HELP_SEEKING.some((p) => lower.includes(p))) {
    add('confidence', 0.05);
    deltas._trust_practical = 0.02;
  }

  // Sharing creative work
  if (CREATIVE_PHRASES.some((p) => lower.includes(p))) {
    add('curiosity', 0.1);
    deltas._trust_creative = 0.02;
  }

  // Deflecting / changing subject
  if (DEFLECTION_PHRASES.some((p) => lower.includes(p))) {
    add('frustration', 0.05);
  }

  // Playfulness signals
  if (PLAYFUL_MARKERS.some((x) => lower.includes(x))) {
    add('playfulness', 0.1);
  }

  // Mood shift (leveraging existing detection)
  if (detectMoodShift(text)) {
    add('warmth', 0.1);
    add('playfulness', -0.1);
  }

  return deltas;
}
