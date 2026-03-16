/**
 * Dynamic opening line generation with caching.
 * Port of _generate_opening(), _load_cached_opening(), _cache_next_opening() from main.py.
 *
 * Generates a stylistically varied opening line using oneshot inference,
 * with time-of-day awareness and recent memory context. Caches the next
 * opening in the background so subsequent launches are instant.
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from './config';
import { runInferenceOneshot } from './inference';
import { timeOfDayContext, timeGapNote } from './agency';
import { getActiveThreads, getLastSessionTime, getRecentSummaries } from './memory';
import { synthesise } from './tts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OpeningResult {
  text: string;
  audioPath?: string;
}

interface CachedOpening {
  text: string;
  audioPath?: string;
  hour: number;
  generatedAt: string;
}

// ---------------------------------------------------------------------------
// Time bracket - used to invalidate stale cached openings
// ---------------------------------------------------------------------------

type TimeBracket = 'morning' | 'afternoon' | 'evening' | 'night';

function getTimeBracket(hour: number): TimeBracket {
  if (hour < 6) return 'night';
  if (hour < 12) return 'morning';
  if (hour < 17) return 'afternoon';
  if (hour < 22) return 'evening';
  return 'night';
}

// ---------------------------------------------------------------------------
// Opening styles - randomly selected per generation
// ---------------------------------------------------------------------------

const OPENING_STYLES: readonly string[] = [
  'Ask a question you have been sitting with since last time.',
  'Notice the time. Say what it makes you think.',
  'Pick up something unfinished - a loose thread from before.',
  'Say something you have been thinking about that has nothing to do with them.',
  'Be playful. Tease them gently about something real.',
  'Be direct. One line. No warmup.',
  'Start from something in their notes that stuck with you.',
  'One quiet line. Let them come to you.',
  'Share something you noticed about how you think or feel.',
  'Ask about something mundane - music, food, weather, sleep.',
  'Say something strange. A thought that does not quite land yet.',
  'Admit something. A small honesty about yourself.',
  'Be philosophical. One line that reframes the ordinary.',
  'Be curious. Ask them something you genuinely want to know.',
  'Be wistful. Let a memory surface.',
];

// ---------------------------------------------------------------------------
// Static fallbacks - used when dynamic generation fails.
// Much better than just saying the agent's name.
// ---------------------------------------------------------------------------

const STATIC_FALLBACKS: readonly string[] = [
  'Been thinking about you.',
  'There you are.',
  "How's your head?",
  'Missed you.',
  'Back again.',
  'Right. Where were we.',
  "What's on your mind?",
  "Something's different today.",
  'Tell me something.',
  'I had a thought while you were gone.',
  "What's the weather like where you are?",
  'You look like you have something to say.',
  "Let's pick up where we left off.",
  "I've been sitting with something.",
  'Good. You showed up.',
];

export function getStaticFallback(): string {
  return STATIC_FALLBACKS[Math.floor(Math.random() * STATIC_FALLBACKS.length)];
}

// ---------------------------------------------------------------------------
// Cache file path
// ---------------------------------------------------------------------------

function getCachePath(): string {
  const config = getConfig();
  return config.OPENING_CACHE_FILE;
}

// ---------------------------------------------------------------------------
// loadCachedOpening - return cached opening if valid, null otherwise
// ---------------------------------------------------------------------------

export function loadCachedOpening(): OpeningResult | null {
  const cachePath = getCachePath();
  if (!cachePath) return null;

  try {
    if (!fs.existsSync(cachePath)) return null;

    const raw = fs.readFileSync(cachePath, 'utf-8');
    const data: CachedOpening = JSON.parse(raw);

    // Delete after read - one-shot cache
    try {
      fs.unlinkSync(cachePath);
    } catch {
      // Ignore deletion errors
    }

    if (!data.text) return null;

    // Discard if time bracket has shifted
    const cachedBracket = getTimeBracket(data.hour);
    const nowBracket = getTimeBracket(new Date().getHours());
    if (cachedBracket !== nowBracket) {
      console.log(
        `[opening] Cached opening stale - was ${cachedBracket}, now ${nowBracket}`,
      );
      return null;
    }

    // Verify audio file still exists if one was cached
    let audioPath = data.audioPath;
    if (audioPath && !fs.existsSync(audioPath)) {
      audioPath = undefined;
    }

    return { text: data.text, audioPath };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// generateOpening - create a fresh opening line via oneshot inference
// ---------------------------------------------------------------------------

export async function generateOpening(
  system: string,
  _cliSessionId?: string,
): Promise<OpeningResult> {
  // Gather context
  const contextParts: string[] = [timeOfDayContext().context];

  const gap = timeGapNote(getLastSessionTime());
  if (gap) {
    contextParts.push(gap);
  }

  const threads = getActiveThreads();
  if (threads.length > 0) {
    const names = threads.slice(0, 3).map((t) => t.name);
    contextParts.push(`Active threads: ${names.join(', ')}`);
  }

  const summaries = getRecentSummaries(3);
  if (summaries.length > 0) {
    const snippets = summaries.map(
      (s) => s.content.slice(0, 120).replace(/\n/g, ' '),
    );
    contextParts.push(`Recent sessions: ${snippets.join(' | ')}`);
  }

  const context = contextParts.join(' ');

  // Pick a random style
  const style = OPENING_STYLES[Math.floor(Math.random() * OPENING_STYLES.length)];

  const prompt =
    `[Context: ${context}]\n\n` +
    `(Session starting. You go first. One sentence, maybe two. ` +
    `Your style this time: ${style} ` +
    `Do NOT reference the build, what is broken, or what is working. ` +
    `Do NOT give status updates. Be surprising.)`;

  console.log(`[opening] Generating with style: "${style}"`);

  const response = await runInferenceOneshot(
    [{ role: 'user', content: prompt }],
    system,
  );

  if (!response || !response.trim()) {
    throw new Error('Empty opening response from inference');
  }

  const text = response.trim();
  console.log(`[opening] Generated: "${text.slice(0, 80)}..."`);

  return { text };
}

// ---------------------------------------------------------------------------
// cacheNextOpening - pre-generate the next session's opening in background
// ---------------------------------------------------------------------------

export function cacheNextOpening(
  system: string,
  cliSessionId?: string,
): void {
  const cachePath = getCachePath();
  if (!cachePath) return;

  // Fire and forget - runs in background
  (async () => {
    try {
      const result = await generateOpening(system, cliSessionId);
      if (!result.text) return;

      let audioPath = '';
      try {
        const synthesised = await synthesise(result.text);
        if (synthesised) {
          audioPath = synthesised;
        }
      } catch {
        // TTS errors are non-fatal for caching
      }

      const cached: CachedOpening = {
        text: result.text,
        audioPath: audioPath || undefined,
        hour: new Date().getHours(),
        generatedAt: new Date().toISOString(),
      };

      // Ensure parent directory exists
      const dir = path.dirname(cachePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      fs.writeFileSync(cachePath, JSON.stringify(cached, null, 2));
      console.log('[opening] Cached next opening');
    } catch (err) {
      console.log(`[opening] Failed to cache opening: ${err}`);
    }
  })();
}
