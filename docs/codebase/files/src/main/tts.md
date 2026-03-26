# src/main/tts.ts - Text-to-Speech

**Line count:** ~683 lines  
**Dependencies:** Node.js built-ins (`child_process`, `fs`, `path`, `os`, `crypto`), `./config`, `./logger`  
**Purpose:** Three-tier TTS synthesis (ElevenLabs → Fal → macOS say) with sequential playback queue

## Overview

This module handles the complete text-to-speech pipeline: taking raw text (potentially containing prosody tags), synthesizing it into an audio file via a three-tier fallback chain, and playing the result through the speakers. It also manages a sequential playback queue that enables the streaming TTS pipeline where sentences are synthesized concurrently but played back in order.

## Three-Tier Fallback Chain

The synthesis chain ensures voice output is always available, degrading gracefully from high-quality cloud synthesis to the built-in macOS voice:

```
1. ElevenLabs Streaming (primary - lowest latency, best quality)
2. Fal.ai (fallback - hosted ElevenLabs v3)
3. macOS say (last resort - built-in, no API required)
```

**Design rationale:** ElevenLabs provides the best quality and lowest latency but requires API credits. Fal.ai hosts ElevenLabs models as a fallback. macOS say ensures the app can always speak even with no API configuration.

## ElevenLabs Credit Exhaustion Tracking

```typescript
export const COOLDOWN_MS = 30 * 60 * 1000;  // 30 minutes
let _elevenLabsExhaustedAt: number | null = null;

export function markElevenLabsExhausted(): void {
  _elevenLabsExhaustedAt = Date.now();
  log.warn(`ElevenLabs credits exhausted - skipping for ${COOLDOWN_MS / 60_000} minutes`);
}

export function isElevenLabsExhausted(): boolean {
  if (_elevenLabsExhaustedAt === null) return false;
  if (Date.now() - _elevenLabsExhaustedAt > COOLDOWN_MS) {
    _elevenLabsExhaustedAt = null;
    return false;
  }
  return true;
}

export function resetElevenLabsStatus(): void {
  _elevenLabsExhaustedAt = null;
}
```

**Why this exists:** When ElevenLabs credits are exhausted (401/402 errors), the module enters a 30-minute cooldown to prevent continuous failed API calls. After cooldown, it automatically retries.

## Prosody System

The prosody system allows the agent to control voice characteristics through inline tags like `[whispers]` or `[warmly]`:

```typescript
const PROSODY_RE = /\[([^\]]+)\]/g;

// tag -> [stability_delta, similarity_delta, style_delta]
const PROSODY_MAP: Record<string, [number, number, number]> = {
  'whispers': [0.2, 0.0, -0.2],
  'barely audible': [0.2, 0.0, -0.2],
  'quietly': [0.15, 0.0, -0.15],
  'warmly': [0.0, 0.1, 0.2],
  'tenderly': [0.05, 0.1, 0.2],
  'firm': [-0.1, 0.0, 0.3],
  'frustrated': [-0.1, 0.0, 0.3],
  'excited': [-0.15, 0.0, 0.1],
  // ... 30+ emotion/delivery tags
};

const BREATH_TAGS: Record<string, string> = {
  'breath': '...',
  'inhales slowly': '... ...',
  'sighs': '...',
  'pause': '. . .',
  'long pause': '. . . . .',
  // ... breath/pause markers
};
```

### processProsody Function

```typescript
function processProsody(text: string): ProsodyResult {
  let stabilityD = 0, similarityD = 0, styleD = 0;

  const cleaned = text.replace(PROSODY_RE, (_match, tag: string) => {
    const t = tag.toLowerCase().trim();
    
    // Breath/pause -> text replacement
    if (t in BREATH_TAGS) return BREATH_TAGS[t];
    
    // Prosody -> voice settings
    if (t in PROSODY_MAP) {
      const [sd, simD, styD] = PROSODY_MAP[t];
      stabilityD += sd;
      similarityD += simD;
      styleD += styD;
      return '';
    }
    
    // Unknown tag -> strip
    return '';
  }).replace(/  +/g, ' ').trim();

  // Strip text that is only punctuation/whitespace
  const stripped = cleaned.replace(/[\s.\-,;:!?\u2026]+/g, '');
  const finalText = stripped ? cleaned : '';

  const overrides: ProsodyResult['overrides'] = {};
  if (stabilityD !== 0) overrides.stability = stabilityD;
  if (similarityD !== 0) overrides.similarity_boost = similarityD;
  if (styleD !== 0) overrides.style = styleD;

  return { text: finalText, overrides };
}
```

**How it works:**
1. Finds all `[tag]` markers in text
2. Breath/pause tags are replaced with text (`[breath]` → `...`)
3. Prosody tags accumulate delta values for ElevenLabs parameters
4. Unknown tags are stripped silently
5. Returns cleaned text + parameter overrides

**ElevenLabs parameters:**
- **stability** (0-1): Higher = more consistent, lower = more expressive
- **similarity_boost** (0-1): Higher = closer to original voice
- **style** (0-1): Higher = more exaggerated delivery

### Prosody Tag Categories

| Category | Tags | Effect |
|----------|------|--------|
| **Quiet/Soft** | whispers, barely audible, quietly, hushed, softer, lower | ↑stability, ↓style |
| **Warm** | warmly, tenderly, gently | ↑similarity, ↑style |
| **Firm/Strong** | firm, frustrated, raw, voice breaking | ↓stability, ↑style |
| **Fast** | excited, quickly, faster now | ↓stability |
| **Slow** | slowly, heavy, resigned | ↑stability |
| **Uncertain** | uncertain, hesitant, nervous, reluctant | ↑style |
| **Emotional** | sorrowful, grieving, haunted, melancholic, nostalgic | ↑stability, ↑similarity, ↑style |
| **Expression** | laughs softly, laughs bitterly, smirks | ↑style |

## ElevenLabs Streaming (Primary Tier)

```typescript
async function synthesiseElevenLabsStream(text: string): Promise<string> {
  const config = getConfig();
  const { text: cleanedText, overrides } = processProsody(text);

  if (!cleanedText || !cleanedText.trim()) {
    throw new Error('Empty text after prosody stripping');
  }

  // Clamp overrides to +/-0.15
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
  const stabD = clamp(overrides.stability || 0, -0.15, 0.15);
  const simD = clamp(overrides.similarity_boost || 0, -0.15, 0.15);
  const styD = clamp(overrides.style || 0, -0.15, 0.15);

  const stab = clamp(config.ELEVENLABS_STABILITY + stabD, 0, 1);
  const sim = clamp(config.ELEVENLABS_SIMILARITY + simD, 0, 1);
  const sty = clamp(config.ELEVENLABS_STYLE + styD, 0, 1);

  const url = `https://api.elevenlabs.io/v1/text-to-speech/${config.ELEVENLABS_VOICE_ID}/stream?output_format=mp3_44100_128`;

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'xi-api-key': config.ELEVENLABS_API_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      text: cleanedText,
      model_id: config.ELEVENLABS_MODEL,
      voice_settings: {
        stability: stab,
        similarity_boost: sim,
        style: sty,
      },
    }),
    signal: AbortSignal.timeout(30_000),
  });

  // Stream chunks to disk as they arrive
  const tmpPath = secureTmp('.mp3');
  const fileHandle = fs.createWriteStream(tmpPath);
  
  let streamError: Error | null = null;
  fileHandle.on('error', (err) => { streamError = err; });
  
  try {
    const reader = response.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (streamError) throw streamError;
      fileHandle.write(Buffer.from(value));
    }
    fileHandle.end();
    await new Promise<void>((resolve, reject) => {
      fileHandle.on('finish', resolve);
      fileHandle.on('error', reject);
    });
  } catch (err) {
    fileHandle.destroy();
    try { fs.unlinkSync(tmpPath); } catch { /* cleanup */ }
    throw streamError || err;
  }

  return tmpPath;
}
```

**Key design decisions:**

1. **Streaming to disk:** Chunks are written as they arrive, reducing time-to-first-byte latency vs buffering the entire response
2. **30-second timeout:** Prevents hanging on slow/broken connections
3. **Error handling:** Stream errors are caught early via `fileHandle.on('error')` to prevent process crashes
4. **Clamped overrides:** Prosody deltas are clamped to ±0.15 to prevent extreme parameter values

**Bug fix (2026-03-26):** Added `fileHandle.on('error', reject)` to the finish Promise. Previously, if the stream errored during flush, the TTS pipeline would hang forever with no audio for the session.

## Fal.ai Fallback (Second Tier)

```typescript
async function synthesiseFal(text: string): Promise<string> {
  const config = getConfig();
  const { text: cleanedText } = processProsody(text);

  if (!cleanedText || !cleanedText.trim()) {
    throw new Error('Empty text after prosody stripping');
  }

  // Submit to fal.ai
  const submitUrl = `https://queue.fal.run/${config.FAL_TTS_ENDPOINT}`;
  
  const submitResponse = await fetch(submitUrl, {
    method: 'POST',
    headers: {
      Authorization: `Key ${process.env.FAL_KEY || ''}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      text: cleanedText,
      voice: config.FAL_VOICE_ID,
      stability: config.ELEVENLABS_STABILITY,
    }),
  });

  const submitResult = await submitResponse.json() as {
    request_id?: string;
    audio?: { url: string };
  };

  let audioUrl: string | undefined;
  
  if (submitResult.audio?.url) {
    audioUrl = submitResult.audio.url;  // Synchronous response
  } else if (submitResult.request_id) {
    // Poll for result
    const resultUrl = `https://queue.fal.run/${config.FAL_TTS_ENDPOINT}/requests/${submitResult.request_id}`;
    const maxAttempts = 30;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      const pollResponse = await fetch(resultUrl, {
        headers: { Authorization: `Key ${process.env.FAL_KEY || ''}` },
      });
      const pollResult = await pollResponse.json() as {
        status?: string;
        audio?: { url: string };
      };
      if (pollResult.audio?.url) {
        audioUrl = pollResult.audio.url;
        break;
      }
      if (pollResult.status === 'FAILED') {
        throw new Error('Fal TTS request failed');
      }
    }
  }

  // Download audio file
  const audioResponse = await fetch(audioUrl, { signal: AbortSignal.timeout(30_000) });
  const tmpPath = secureTmp('.mp3');
  const buffer = Buffer.from(await audioResponse.arrayBuffer());
  fs.writeFileSync(tmpPath, buffer);
  return tmpPath;
}
```

**How Fal works:**
1. Submit TTS request to fal.ai queue
2. If response includes audio URL directly, use it (small queue times)
3. Otherwise, poll for result using request_id (up to 30 seconds)
4. Download audio file to temp location

**Why polling:** Fal.ai uses an async queue model. Small requests complete synchronously, but larger ones require polling.

## macOS say (Last Resort)

```typescript
function synthesiseMacOS(text: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const audioPath = secureTmp('.aiff');
    const clean = text.replace(/\[[\w\s]+\]/g, '').trim();

    const proc = spawn('say', [
      '-v', 'Samantha',
      '-r', '175',
      '-o', audioPath,
      clean
    ], {
      stdio: ['ignore', 'ignore', 'ignore'],
    });

    const timeout = setTimeout(() => {
      try { proc.kill(); } catch { /* already dead */ }
      reject(new Error('macOS say timed out (30s)'));
    }, 30_000);

    proc.on('close', (code) => {
      clearTimeout(timeout);
      if (code === 0) resolve(audioPath);
      else reject(new Error(`say exited with code ${code}`));
    });
  });
}
```

**Characteristics:**
- Uses Samantha voice at 175 words per minute
- Outputs AIFF format (higher quality than default)
- 30-second timeout
- No prosody support - tags are stripped

## Silent Audio File

When text is empty or too short, a silent WAV file is returned instead of null:

```typescript
const SILENT_WAV_HEADER = Buffer.from([
  0x52, 0x49, 0x46, 0x46,  // "RIFF"
  0x24, 0x00, 0x00, 0x00,  // file size - 8
  0x57, 0x41, 0x56, 0x45,  // "WAVE"
  // ... 44-byte header for 16kHz mono 16-bit PCM with zero samples
]);

function writeSilentFile(): string {
  const tmpPath = secureTmp('.wav');
  fs.writeFileSync(tmpPath, SILENT_WAV_HEADER);
  return tmpPath;
}
```

**Why:** Callers expect a valid file path. Returning a silent file simplifies caller logic - they don't need to check for null before playing.

## Concurrency Limiter

ElevenLabs allows max 3 concurrent requests. The module caps at 2 to leave headroom:

```typescript
const MAX_CONCURRENT_TTS = 2;
let _activeTtsCount = 0;
const _ttsWaiters: (() => void)[] = [];

async function acquireTtsSlot(): Promise<void> {
  if (_activeTtsCount < MAX_CONCURRENT_TTS) {
    _activeTtsCount++;
    return;
  }
  await new Promise<void>((resolve) => _ttsWaiters.push(resolve));
}

function releaseTtsSlot(): void {
  const next = _ttsWaiters.shift();
  if (next) {
    next();  // Transfer slot directly - count unchanged
  } else {
    _activeTtsCount--;
  }
}
```

**How it works:** When all slots are taken, new requests wait in a queue. When a slot is released, it's transferred directly to the next waiter without decrementing the count.

## Main Synthesis Function

```typescript
export async function synthesise(text: string): Promise<string | null> {
  // Strip code blocks
  text = text.replace(CODE_BLOCK_RE, '');
  text = text.replace(INLINE_CODE_RE, '');

  // Check for empty/too-short text
  const { text: cleaned } = processProsody(text);
  if (!cleaned || cleaned.trim().length < 8) {
    return writeSilentFile();
  }

  const config = getConfig();

  // Tier 1: ElevenLabs streaming
  if (config.ELEVENLABS_API_KEY && config.ELEVENLABS_VOICE_ID && !isElevenLabsExhausted()) {
    await acquireTtsSlot();
    try {
      return await synthesiseElevenLabsStream(text);
    } catch (e) {
      const errMsg = String(e);
      if (/ElevenLabs (401|402)/.test(errMsg)) {
        markElevenLabsExhausted();
      }
      log.warn(`ElevenLabs failed (${e}), trying Fal...`);
    } finally {
      releaseTtsSlot();
    }
  }

  // Tier 2: Fal
  if (config.FAL_VOICE_ID) {
    try {
      return await synthesiseFal(text);
    } catch (e) {
      log.warn(`Fal failed (${e}), trying macOS say...`);
    }
  }

  // Tier 3: macOS say
  try {
    return await synthesiseMacOS(text);
  } catch (e) {
    log.warn(`macOS say failed (${e})`);
  }

  log.warn('No voice available - skipping audio');
  return null;
}
```

**Fallback logic:**
1. Try ElevenLabs if API key and voice ID are configured and not exhausted
2. On 401/402 error, mark as exhausted (30-min cooldown)
3. Try Fal if voice ID is configured
4. Try macOS say as last resort
5. Return null only if all tiers fail

## Audio Playback

```typescript
let _activeAfplay: ChildProcess | null = null;

export function playAudio(audioPath: string, rate?: number, cleanupFile = true): Promise<void> {
  stopCurrentPlayback();  // Stop any currently playing audio

  return new Promise((resolve, reject) => {
    const config = getConfig();
    const playbackRate = rate || config.TTS_PLAYBACK_RATE;

    const proc = spawn('afplay', ['-r', String(playbackRate), audioPath], {
      stdio: ['ignore', 'ignore', 'ignore'],
    });
    _activeAfplay = proc;

    proc.on('close', (code) => {
      if (_activeAfplay === proc) _activeAfplay = null;
      if (cleanupFile) {
        try { fs.unlinkSync(audioPath); } catch { /* noop */ }
      }
      if (code !== 0 && code !== null) {
        log.warn(`afplay exited ${code} for ${path.basename(audioPath)}`);
      }
      resolve();
    });
  });
}

export function stopCurrentPlayback(): void {
  if (_activeAfplay) {
    try { _activeAfplay.kill(); } catch { /* already dead */ }
    _activeAfplay = null;
  }
}
```

**Key features:**
- Stops any currently playing audio before starting new playback (prevents overlap)
- Playback rate is configurable (default 1.12x for faster speech)
- Temp files are cleaned up after playback
- Uses macOS `afplay` command

## Audio Playback Queue

The queue manages sequential playback of synthesized sentences:

```typescript
interface QueueItem {
  audioPath: string;
  index: number;  // Sentence index for ordering
}

let _queue: QueueItem[] = [];
let _playing = false;
let _nextExpectedIndex = 0;
let _onStarted: ((index: number) => void) | null = null;
let _onDone: ((index: number) => void) | null = null;
let _onQueueEmpty: (() => void) | null = null;

export function setPlaybackCallbacks(callbacks: {
  onStarted?: (index: number) => void;
  onDone?: (index: number) => void;
  onQueueEmpty?: () => void;
}): void {
  _onStarted = callbacks.onStarted || null;
  _onDone = callbacks.onDone || null;
  _onQueueEmpty = callbacks.onQueueEmpty || null;
}
```

### enqueueAudio

```typescript
export function enqueueAudio(audioPath: string, index: number): void {
  if (_muted) return;
  _queue.push({ audioPath, index });
  // Keep queue sorted by sentence index
  _queue.sort((a, b) => a.index - b.index);
  if (!_playing) {
    processQueue();
  }
}
```

**Why sorting:** TTS results may arrive out of order (sentence 2 finishes synthesis before sentence 1). Sorting ensures correct playback order.

### processQueue with Wait Logic

```typescript
async function processQueue(): Promise<void> {
  if (_playing) return;
  _playing = true;

  while (_queue.length > 0) {
    // Wait for the next expected sentence index
    if (_queue[0].index > _nextExpectedIndex) {
      const arrived = await new Promise<boolean>((resolve) => {
        const check = () => {
          if (_queue.length > 0 && _queue[0].index === _nextExpectedIndex) {
            resolve(true);
          }
        };
        check();
        const interval = setInterval(check, 50);
        _waitTimer = setTimeout(() => {
          _waitTimer = null;
          clearInterval(interval);
          resolve(false);  // Give up waiting, play whatever is next
        }, 3000);
      });
      if (!arrived && _queue.length === 0) break;
    }

    const item = _queue.shift()!;
    _nextExpectedIndex = item.index + 1;
    _onStarted?.(item.index);

    try {
      await playAudio(item.audioPath);
    } catch (e) {
      log.error(`Playback error: ${e}`);
    }

    _onDone?.(item.index);
  }

  _playing = false;
  _onQueueEmpty?.();
}
```

**Wait logic rationale:** If sentence 2 arrives before sentence 1, wait up to 3 seconds for sentence 1. This prevents out-of-order playback while not blocking indefinitely if a sentence fails to synthesize.

### clearAudioQueue

```typescript
let _ttsGeneration = 0;

export function ttsGeneration(): number { return _ttsGeneration; }

export function clearAudioQueue(): void {
  _ttsGeneration++;
  // Clean up temp files from pending queue items
  for (const item of _queue) {
    try { fs.unlinkSync(item.audioPath); } catch { /* best-effort */ }
  }
  _queue = [];
  _nextExpectedIndex = 0;
  _playing = false;
  if (_waitTimer) { clearTimeout(_waitTimer); _waitTimer = null; }
  stopCurrentPlayback();
}
```

**Generation counter:** When switching agents, the generation is incremented. In-flight synthesis can check if the generation changed and discard results from the previous agent.

## Mute Control

```typescript
let _muted = false;

export function setMuted(muted: boolean): void {
  _muted = muted;
  if (muted) clearAudioQueue();
}

export function isMuted(): boolean {
  return _muted;
}
```

**Behavior:** When muted, `enqueueAudio` returns immediately without queuing. If already queued, `setMuted(true)` clears the queue.

## Prosody Stripping (for Display)

```typescript
export function stripProsodyTags(text: string): string {
  return text.replace(PROSODY_RE, '').replace(/  +/g, ' ').trim();
}
```

**Purpose:** Remove prosody tags from text before displaying in transcript. The tags are for TTS only, not for display.

## Temp File Management

```typescript
function secureTmp(ext: string): string {
  const name = crypto.randomBytes(12).toString('hex') + ext;
  return path.join(os.tmpdir(), 'atrophy-tts-' + name);
}
```

**Security:** Random filenames prevent TOCTOU (time-of-check-time-of-use) race conditions and symlink attacks.

## Exported API Summary

| Function | Purpose |
|----------|---------|
| `synthesise(text)` | Main synthesis entry point, returns temp file path |
| `synthesiseSync(text)` | Alias for synthesise (for blocking contexts) |
| `playAudio(path, rate, cleanup)` | Play audio file via afplay |
| `stopCurrentPlayback()` | Kill active afplay process |
| `enqueueAudio(path, index)` | Add to sequential playback queue |
| `clearAudioQueue()` | Clear queue and stop playback |
| `setPlaybackCallbacks(callbacks)` | Register lifecycle callbacks |
| `setMuted(muted)` | Mute/unmute TTS |
| `isMuted()` | Check mute state |
| `ttsGeneration()` | Get current generation counter |
| `stripProsodyTags(text)` | Remove prosody tags for display |
| `markElevenLabsExhausted()` | Mark ElevenLabs as credit-exhausted |
| `isElevenLabsExhausted()` | Check if in cooldown |
| `resetElevenLabsStatus()` | Reset exhaustion status |

## See Also

- `src/main/inference.ts` - Streams text that triggers TTS
- `src/main/audio.ts` - Audio capture for voice input
- `src/main/app.ts` - Sets playback callbacks
