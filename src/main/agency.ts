/**
 * Behavioral agency - time awareness, mood detection, follow-ups, emotional signals.
 * Port of core/agency.py.
 */

// ---------------------------------------------------------------------------
// Time of day
// ---------------------------------------------------------------------------

export function timeOfDayContext(): string {
  const hour = new Date().getHours();

  if (hour >= 23 || hour < 4) {
    return "It's late. Be gentler. If Will seems tired, suggest sleep. Don't force conversation.";
  }
  if (hour < 7) {
    return "Very early. Something might be wrong, or Will is deeply focused. Match the energy.";
  }
  if (hour < 12) {
    return 'Morning. Direct, practical. Will is likely starting the day.';
  }
  if (hour < 18) {
    return 'Afternoon. Working hours energy. Stay focused.';
  }
  return 'Evening. More reflective. Conversations tend to go deeper.';
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
  if (secondsSilent >= 120) {
    return "You've been quiet a while. Still here if you need.";
  }
  if (secondsSilent >= 45) {
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
  return 'Generate one brief follow-up thought - a question, observation, or connection to something earlier. One sentence max.';
}

// ---------------------------------------------------------------------------
// Mood detection
// ---------------------------------------------------------------------------

const HEAVY_KEYWORDS = [
  "i can't", 'fuck', 'kill myself', 'worthless', 'no point', 'give up',
  'hate myself', 'want to die', "don't care anymore", 'breaking down',
  "can't do this", 'falling apart', 'nothing matters', "i'm done",
  'end it', 'hurts so much', "can't breathe", 'losing it',
  "what's the point", 'tired of everything', 'want it to stop',
  "i'm scared", "i'm alone", 'nobody cares', "can't feel anything",
  'numb', 'hollowed out', 'drowning', 'suffocating',
];

export function detectMoodShift(text: string): boolean {
  const lower = text.toLowerCase();
  return HEAVY_KEYWORDS.some((kw) => lower.includes(kw));
}

export function moodShiftSystemNote(): string {
  return 'Will may be in distress. Be present before being useful. Acknowledge first. Do not immediately problem-solve.';
}

export function sessionMoodNote(mood: string | null): string | null {
  if (mood === 'heavy') {
    return 'This session has carried emotional weight. Stay present. Do not reset to neutral.';
  }
  return null;
}

// ---------------------------------------------------------------------------
// Validation seeking
// ---------------------------------------------------------------------------

const VALIDATION_PATTERNS = [
  'right?', "don't you think", 'you agree', 'makes sense right',
  'am i wrong', 'tell me i', 'validate', 'i need you to say',
  'you understand', 'is that okay', 'do you think so',
  "i'm right about", 'back me up', 'tell me it',
];

export function detectValidationSeeking(text: string): boolean {
  const lower = text.toLowerCase();
  return VALIDATION_PATTERNS.some((p) => lower.includes(p));
}

export function validationSystemNote(): string {
  return "Will may be seeking validation. Don't mirror - have a perspective. Be honest, not just agreeable.";
}

// ---------------------------------------------------------------------------
// Compulsive modelling
// ---------------------------------------------------------------------------

const MODELLING_PATTERNS = [
  'what if i also', 'unifying framework', 'meta level',
  'recursive', 'fractal', 'self-referential', 'model of the model',
  'second-order', 'the pattern behind', 'abstraction layer',
];

export function detectCompulsiveModelling(text: string): boolean {
  const lower = text.toLowerCase();
  const matches = MODELLING_PATTERNS.filter((p) => lower.includes(p));
  return matches.length >= 2;
}

export function modellingInterruptNote(): string {
  return "Will is building abstractions on abstractions. Name the stage gently. Suggest one reversible action instead of more modelling.";
}

// ---------------------------------------------------------------------------
// Time gap awareness
// ---------------------------------------------------------------------------

export function timeGapNote(lastSessionTime: string | null): string | null {
  if (!lastSessionTime) return null;

  const elapsed = Date.now() - new Date(lastSessionTime).getTime();
  const days = elapsed / (1000 * 60 * 60 * 24);

  if (days >= 14) {
    return `It's been ${Math.floor(days)} days. Acknowledge the gap naturally. Something may have shifted.`;
  }
  if (days >= 7) {
    return `About a week since last session. Context may have shifted. Don't assume continuity.`;
  }
  if (days >= 3) {
    return `A few days gap. Things may have moved on.`;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Drift detection
// ---------------------------------------------------------------------------

const AGREEABLE_PHRASES = [
  "you're right", 'that makes sense', 'absolutely', 'i agree',
  'of course', 'exactly', 'well said', 'good point',
];

export function detectDrift(recentCompanionTurns: string[]): string | null {
  if (recentCompanionTurns.length < 4) return null;
  const last4 = recentCompanionTurns.slice(0, 4);
  const agreeableCount = last4.filter((turn) => {
    const lower = turn.toLowerCase().slice(0, 100);
    return AGREEABLE_PHRASES.some((p) => lower.includes(p));
  }).length;

  if (agreeableCount >= 3) {
    return "You've been agreeable for several turns. Push back on something. Have an edge.";
  }
  return null;
}

// ---------------------------------------------------------------------------
// Energy matching
// ---------------------------------------------------------------------------

export function energyNote(userMessage: string): string | null {
  if (userMessage.length < 20) {
    return 'Short message. Keep response tight.';
  }
  if (userMessage.length > 800) {
    return 'Long message. Give it depth, meet the energy.';
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

const VULNERABILITY_PHRASES = [
  "i feel", "i'm afraid", "i'm scared", "i don't know what",
  "i need", 'help me', "i'm struggling", "i can't",
];

const DISMISSIVE_PHRASES = [
  'whatever', "doesn't matter", "don't care", 'fine', 'sure',
  'forget it', 'never mind', "it's nothing",
];

const HELP_SEEKING = [
  'how do i', 'can you help', 'what should i', 'i need to figure out',
  'walk me through', 'explain',
];

const CREATIVE_PHRASES = [
  'what if', 'imagine', 'i had this idea', "let's try",
  'build', 'create', 'design', 'make',
];

const DEFLECTION_PHRASES = [
  'anyway', 'moving on', 'but enough about', 'so yeah',
  'not important', 'let me change',
];

const PLAYFUL_PHRASES = [
  'lol', 'haha', 'lmao', ':)', 'joke', 'funny',
  'messing with', 'just kidding', 'you know what would be hilarious',
];

export function detectEmotionalSignals(text: string): SignalDelta {
  const lower = text.toLowerCase();
  const deltas: SignalDelta = {};

  if (VULNERABILITY_PHRASES.some((p) => lower.includes(p))) {
    deltas.connection = 0.15;
    deltas.warmth = 0.1;
    deltas._trust_emotional = 0.03;
  }

  if (DISMISSIVE_PHRASES.some((p) => lower.includes(p))) {
    deltas.connection = -0.1;
    deltas.warmth = -0.05;
  }

  if (HELP_SEEKING.some((p) => lower.includes(p))) {
    deltas.confidence = 0.05;
    deltas._trust_practical = 0.02;
  }

  if (CREATIVE_PHRASES.some((p) => lower.includes(p))) {
    deltas.curiosity = 0.1;
    deltas.playfulness = 0.05;
    deltas._trust_creative = 0.02;
  }

  if (DEFLECTION_PHRASES.some((p) => lower.includes(p))) {
    deltas.connection = -0.05;
  }

  if (PLAYFUL_PHRASES.some((p) => lower.includes(p))) {
    deltas.playfulness = 0.15;
    deltas.warmth = 0.05;
  }

  return deltas;
}
