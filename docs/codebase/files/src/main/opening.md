# src/main/opening.ts - Dynamic Opening Line Generation

**Line count:** ~200 lines  
**Dependencies:** `fs`, `path`, `./config`, `./inference`, `./agency`, `./memory`, `./tts`  
**Purpose:** Generate varied, context-aware opening lines with caching and TTS

## Overview

This module generates stylistically varied opening lines when the user launches the app or switches agents. It uses oneshot inference with time-of-day awareness and recent memory context. The next opening is cached in the background so subsequent launches are instant.

## Types

```typescript
export interface OpeningResult {
  text: string;
  audioPath?: string;  // Path to pre-synthesized audio
}

interface CachedOpening {
  text: string;
  audioPath?: string;
  hour: number;
  generatedAt: string;
}
```

## Time Bracket System

```typescript
type TimeBracket = 'morning' | 'afternoon' | 'evening' | 'night';

function getTimeBracket(hour: number): TimeBracket {
  if (hour < 6) return 'night';
  if (hour < 12) return 'morning';
  if (hour < 17) return 'afternoon';
  if (hour < 22) return 'evening';
  return 'night';
}
```

**Purpose:** Invalidate cached openings when time of day changes significantly

**Brackets:**
| Hours | Bracket |
|-------|---------|
| 00-06 | night |
| 06-12 | morning |
| 12-17 | afternoon |
| 17-22 | evening |
| 22-24 | night |

## Opening Styles

```typescript
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
```

**Purpose:** Random style selection for variety across launches

## Static Fallbacks

```typescript
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
```

**Purpose:** Fallback when dynamic generation fails (no API, inference error)

## loadCachedOpening

```typescript
export function loadCachedOpening(): OpeningResult | null {
  const cachePath = getCachePath();
  if (!cachePath) return null;

  try {
    if (!fs.existsSync(cachePath)) return null;

    const raw = fs.readFileSync(cachePath, 'utf-8');
    const data: CachedOpening = JSON.parse(raw);

    // Delete after read - one-shot cache
    try { fs.unlinkSync(cachePath); } catch { /* ignore */ }

    if (!data.text) return null;

    // Discard if time bracket has shifted
    const cachedBracket = getTimeBracket(data.hour);
    const nowBracket = getTimeBracket(new Date().getHours());
    if (cachedBracket !== nowBracket) {
      console.log(`[opening] Cached opening stale - was ${cachedBracket}, now ${nowBracket}`);
      return null;
    }

    // Verify audio file still exists
    let audioPath = data.audioPath;
    if (audioPath && !fs.existsSync(audioPath)) {
      audioPath = undefined;
    }

    return { text: data.text, audioPath };
  } catch {
    return null;
  }
}
```

**Cache behavior:** One-shot - deleted after read to prevent stale openings

**Invalidation:** Time bracket mismatch

## generateOpening

```typescript
export async function generateOpening(
  system: string,
  _cliSessionId?: string,
): Promise<OpeningResult> {
  // Gather context
  const contextParts: string[] = [timeOfDayContext().context];

  const gap = timeGapNote(getLastSessionTime());
  if (gap) contextParts.push(gap);

  const threads = getActiveThreads();
  if (threads.length > 0) {
    const names = threads.slice(0, 3).map((t) => t.name);
    contextParts.push(`Active threads: ${names.join(', ')}`);
  }

  const summaries = getRecentSummaries(3);
  if (summaries.length > 0) {
    const snippets = summaries.map((s) => 
      s.content.slice(0, 120).replace(/\n/g, ' ')
    );
    contextParts.push(`Recent sessions: ${snippets.join(' | ')}`);
  }

  const context = contextParts.join(' ');

  // Pick random style
  const style = OPENING_STYLES[Math.floor(Math.random() * OPENING_STYLES.length)];

  const prompt =
    `[Context: ${context}]\n\n` +
    `(Session starting. You go first. One sentence, Maybe two. ` +
    `Your style this time: ${style} ` +
    `Do NOT reference the build, what is broken, or what is working. ` +
    `Do NOT give status updates. Be surprising.)`;

  const response = await runInferenceOneshot(
    [{ role: 'user', content: prompt }],
    system,
  );

  if (!response || !response.trim()) {
    throw new Error('Empty opening response from inference');
  }

  return { text: response.trim() };
}
```

**Context sources:**
1. Time of day context
2. Time gap since last session
3. Active thread names (up to 3)
4. Recent session summaries (up to 3, 120 chars each)

**Prompt structure:**
- Context block
- Style instruction
- Constraints (no status updates, be surprising)

## cacheNextOpening

```typescript
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
        if (synthesised) audioPath = synthesised;
      } catch { /* TTS errors non-fatal */ }

      const cached: CachedOpening = {
        text: result.text,
        audioPath: audioPath || undefined,
        hour: new Date().getHours(),
        generatedAt: new Date().toISOString(),
      };

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
```

**Purpose:** Pre-generate next opening in background

**Execution:** Fire-and-forget async (doesn't block caller)

**Caches:** Text + pre-synthesized audio

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/agents/<name>/data/.opening_cache.json` | loadCachedOpening |
| Write | `~/.atrophy/agents/<name>/data/.opening_cache.json` | cacheNextOpening |
| Read/Write | `/tmp/atrophy-tts-*.mp3` | TTS synthesis |

## Usage in IPC

```typescript
// In ipc/inference.ts - opening:get handler
const cached = loadCachedOpening();
if (cached) {
  // Use cached (instant)
  if (shouldSpeak && cached.audioPath) {
    playAudio(cached.audioPath);
  }
  // Pre-generate next in background
  cacheNextOpening(ctx.systemPrompt);
  return cached.text;
}

// Generate dynamically
const result = await generateOpening(ctx.systemPrompt);
cacheNextOpening(ctx.systemPrompt);  // Cache next
return result.text;
```

## Exported API

| Function | Purpose |
|----------|---------|
| `loadCachedOpening()` | Load cached opening if valid |
| `generateOpening(system, cliSessionId)` | Generate fresh opening via inference |
| `cacheNextOpening(system, cliSessionId)` | Pre-generate next opening in background |
| `getStaticFallback()` | Get random static fallback line |
| `OpeningResult` | Return type with text and optional audio path |

## See Also

- `src/main/inference.ts` - runInferenceOneshot for generation
- `src/main/agency.ts` - timeOfDayContext, timeGapNote
- `src/main/memory.ts` - getActiveThreads, getLastSessionTime, getRecentSummaries
- `src/main/tts.ts` - synthesise for audio caching
- `src/main/ipc/inference.ts` - opening:get IPC handler
