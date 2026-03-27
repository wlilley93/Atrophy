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

  // 70% threshold for time clustering (matches Python behavior)
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

// ---------------------------------------------------------------------------
// Need satisfaction phrase lists
// ---------------------------------------------------------------------------

const STIMULATION_PHRASES: readonly string[] = [
  'interesting', 'curious about', 'what if', 'how does', 'tell me about',
  'never thought about', 'that reminds me', 'new idea',
];

const EXPRESSION_PHRASES: readonly string[] = [
  'create', 'build', 'write', 'make', 'design', 'compose',
  'draw', 'draft', 'generate', 'produce',
];

const PURPOSE_PHRASES: readonly string[] = [
  'help me', 'can you', 'i need you to', 'could you', 'please do',
  'work on', 'finish', 'complete', 'handle', 'take care of',
];

const AUTONOMY_PHRASES: readonly string[] = [
  'do what you think', 'your call', 'i trust your judgment',
  'up to you', 'whatever you think', 'you decide',
  'i trust you', 'your choice', 'go with your gut',
];

const RECOGNITION_PHRASES: readonly string[] = [
  'great work', 'exactly right', 'well done', 'perfect',
  'good job', 'nailed it', 'brilliant', 'impressive',
  'nice work', 'love it', 'excellent', 'spot on', 'amazing',
];

const NOVELTY_PHRASES: readonly string[] = [
  'completely different', 'new topic', 'change of subject',
  'something else', 'random question', 'off topic',
  'unrelated', 'by the way', 'switching gears',
];

// ---------------------------------------------------------------------------
// Relationship phrase lists
// ---------------------------------------------------------------------------

const FAMILIARITY_PHRASES: readonly string[] = [
  'remember when', 'like last time', 'as we discussed',
  'you mentioned', 'we talked about', 'from before',
  'like you said', 'our conversation',
];

const RAPPORT_PHRASES: readonly string[] = [
  'haha', 'lol', 'lmao', 'that\'s funny', 'hilarious',
  'cracking up', 'dying', '\u{1F602}', '\u{1F604}', '\u{1F923}',
  '\u{1F606}', '\u{1F60D}',
];

const BOUNDARY_PHRASES: readonly string[] = [
  'don\'t', 'stop', 'not now', 'leave it', 'drop it',
  'enough', 'back off', 'not interested', 'no thanks',
  'i said no', 'quit it',
];

const CHALLENGE_COMFORT_PHRASES: readonly string[] = [
  'good point', 'you\'re right to push back', 'fair enough',
  'i hadn\'t thought of that', 'you make a good case',
  'okay you convinced me', 'that\'s a valid criticism',
];

const VULNERABILITY_PERSONAL_PHRASES: readonly string[] = [
  'i feel', 'i\'ve been', 'my family', 'my relationship',
  'growing up', 'when i was', 'personally', 'between us',
  'i\'ve never told', 'this is personal',
];

// ---------------------------------------------------------------------------
// New trust domain phrase lists
// ---------------------------------------------------------------------------

const OPERATIONAL_TRUST_PHRASES: readonly string[] = [
  'go ahead', 'do it', 'execute', 'deploy', 'run it',
  'ship it', 'make it happen', 'pull the trigger',
  'proceed', 'launch', 'push it',
];

const PERSONAL_TRUST_PHRASES: readonly string[] = [
  'my life', 'my partner', 'my family', 'my health',
  'my feelings', 'at home', 'my friend', 'my kids',
  'my parents', 'my relationship', 'dating', 'my ex',
];

// ---------------------------------------------------------------------------
// New emotion phrase lists
// ---------------------------------------------------------------------------

const ANTICIPATION_PHRASES: readonly string[] = [
  'can\'t wait', 'looking forward', 'tomorrow', 'planning',
  'excited about', 'next week', 'soon', 'going to be',
  'upcoming', 'about to',
];

const SATISFACTION_PHRASES: readonly string[] = [
  'done', 'finished', 'works perfectly', 'nailed it',
  'complete', 'sorted', 'finally', 'all good',
  'that works', 'solved',
];

const MELANCHOLY_PHRASES: readonly string[] = [
  'miss', 'wish', 'used to', 'gone', 'lost',
  'remember when', 'those days', 'if only',
  'not anymore', 'once upon',
];

const DEFIANCE_PHRASES: readonly string[] = [
  'no', 'wrong', 'i disagree', 'that\'s not right',
  'absolutely not', 'you\'re wrong', 'i don\'t think so',
  'that\'s incorrect', 'i reject', 'not true',
];

export function detectEmotionalSignals(text: string): SignalDelta {
  const lower = text.toLowerCase().trim();
  const length = text.trim().length;
  const deltas: SignalDelta = {};

  function add(key: string, value: number): void {
    deltas[key] = (deltas[key] || 0) + value;
  }

  // -----------------------------------------------------------------------
  // Existing emotion signals
  // -----------------------------------------------------------------------

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

  // Vulnerability / openness - emotional trust signal
  if (VULNERABILITY_PHRASES.some((p) => lower.includes(p))) {
    add('connection', 0.15);
    add('warmth', 0.1);
    deltas._trust_emotional = 0.03;
  }

  // Asking for help (practical trust signal)
  if (HELP_SEEKING.some((p) => lower.includes(p))) {
    add('confidence', 0.05);
    deltas._trust_practical = 0.02;
  }

  // Sharing creative work (creative trust signal)
  if (CREATIVE_PHRASES.some((p) => lower.includes(p))) {
    add('curiosity', 0.1);
    deltas._trust_creative = 0.02;
  }

  // Long thoughtful messages signal intellectual trust
  if (length > 400) {
    deltas._trust_intellectual = 0.02;
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

  // -----------------------------------------------------------------------
  // New emotion signals
  // -----------------------------------------------------------------------

  // Amusement - humor markers (overlaps with playfulness but distinct emotion)
  if (RAPPORT_PHRASES.some((p) => lower.includes(p))) {
    add('amusement', 0.15);
  }

  // Anticipation - future-oriented language
  if (ANTICIPATION_PHRASES.some((p) => lower.includes(p))) {
    add('anticipation', 0.1);
  }

  // Satisfaction - completion markers
  if (SATISFACTION_PHRASES.some((p) => lower.includes(p))) {
    add('satisfaction', 0.15);
  }

  // Tenderness - vulnerability + warmth context (only when vulnerability detected)
  if (VULNERABILITY_PHRASES.some((p) => lower.includes(p)) && length > 100) {
    add('tenderness', 0.1);
  }

  // Melancholy - sadness/nostalgia markers
  if (MELANCHOLY_PHRASES.some((p) => lower.includes(p))) {
    add('melancholy', 0.1);
  }

  // Focus - long detailed message on a single topic (>500 chars, heuristic for technical)
  if (length > 500) {
    add('focus', 0.1);
  }

  // Defiance - disagreement markers
  if (DEFIANCE_PHRASES.some((p) => lower.includes(p))) {
    add('defiance', 0.1);
  }

  // -----------------------------------------------------------------------
  // New trust domains
  // -----------------------------------------------------------------------

  // Operational trust - granting real-world access
  if (OPERATIONAL_TRUST_PHRASES.some((p) => lower.includes(p))) {
    deltas._trust_operational = 0.02;
  }

  // Personal trust - sharing personal details, non-work topics
  if (PERSONAL_TRUST_PHRASES.some((p) => lower.includes(p))) {
    deltas._trust_personal = 0.02;
  }

  // -----------------------------------------------------------------------
  // Need satisfaction signals
  // -----------------------------------------------------------------------

  // Stimulation - new topic, interesting question, novel problem
  if (STIMULATION_PHRASES.some((p) => lower.includes(p))) {
    add('_need_stimulation', 3);
  }

  // Expression - asking agent to create/build/write something
  if (EXPRESSION_PHRASES.some((p) => lower.includes(p))) {
    add('_need_expression', 3);
  }

  // Purpose - asking for help, giving a task, requesting work
  if (PURPOSE_PHRASES.some((p) => lower.includes(p))) {
    add('_need_purpose', 4);
  }

  // Autonomy - delegating decision-making
  if (AUTONOMY_PHRASES.some((p) => lower.includes(p))) {
    add('_need_autonomy', 3);
  }

  // Recognition - positive feedback, praise
  if (RECOGNITION_PHRASES.some((p) => lower.includes(p))) {
    add('_need_recognition', 4);
  }

  // Novelty - introducing a new subject, unexpected turn
  if (NOVELTY_PHRASES.some((p) => lower.includes(p))) {
    add('_need_novelty', 3);
  }

  // Social - back-and-forth engagement (>100 chars suggests real conversation)
  if (length > 100) {
    add('_need_social', 2);
  }

  // -----------------------------------------------------------------------
  // Relationship signals
  // -----------------------------------------------------------------------

  // Baseline familiarity growth - every real conversation (>50 chars) builds familiarity.
  // This is the "just showing up" signal - independent of keywords.
  if (length > 50) {
    add('_rel_familiarity', 0.01);
    add('_rel_reliability', 0.005);
  }

  // Familiarity - referencing shared history (stronger signal)
  if (FAMILIARITY_PHRASES.some((p) => lower.includes(p))) {
    add('_rel_familiarity', 0.03);
  }

  // Rapport - humor landing
  if (RAPPORT_PHRASES.some((p) => lower.includes(p))) {
    add('_rel_rapport', 0.03);
  }

  // Boundaries - setting a limit
  if (BOUNDARY_PHRASES.some((p) => lower.includes(p))) {
    add('_rel_boundaries', 0.015);
  }

  // Challenge comfort - accepting pushback
  if (CHALLENGE_COMFORT_PHRASES.some((p) => lower.includes(p))) {
    add('_rel_challenge_comfort', 0.025);
  }

  // Vulnerability - sharing personal info beyond work
  if (VULNERABILITY_PERSONAL_PHRASES.some((p) => lower.includes(p))) {
    add('_rel_vulnerability', 0.03);
  }

  return deltas;
}
