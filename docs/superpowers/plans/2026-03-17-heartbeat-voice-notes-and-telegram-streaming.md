# Heartbeat Voice Notes, ElevenLabs Fallback, and Interactive Telegram Tools

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable heartbeat reach-outs to be sent as voice notes (agent decides), handle ElevenLabs credit exhaustion gracefully, and update prompts so the agent knows it can use interactive Telegram tools (ask_user with buttons) during background jobs.

**Architecture:** Extract shared audio conversion from voice-note.ts into a reusable module. Add ElevenLabs credit tracking to tts.ts (detect 401/402/429, set cooldown). Extend heartbeat's response parser to handle a `[VOICE_NOTE]` prefix. Update heartbeat and voice-note prompts to document available Telegram interaction tools.

**Tech Stack:** TypeScript, Electron, ffmpeg (for MP3-to-OGG Opus), ElevenLabs API, Telegram Bot API, Vitest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/main/audio-convert.ts` | Create | Shared MP3-to-OGG Opus conversion via ffmpeg, temp file cleanup helper |
| `src/main/tts.ts` | Modify | Add ElevenLabs credit exhaustion tracking (cooldown after repeated 401/402/429) |
| `src/main/jobs/voice-note.ts` | Modify | Import `convertToOgg` from audio-convert.ts instead of local copy |
| `src/main/jobs/heartbeat.ts` | Modify | Add `[VOICE_NOTE]` response handling, update prompt with voice/interaction options |
| `src/main/__tests__/audio-convert.test.ts` | Create | Tests for conversion function (mocked ffmpeg) |
| `src/main/__tests__/tts-credits.test.ts` | Create | Tests for ElevenLabs credit exhaustion tracking |
| `src/main/__tests__/heartbeat-voice.test.ts` | Create | Tests for heartbeat voice note response parsing |

---

### Task 1: Shared audio conversion module

**Files:**
- Create: `src/main/audio-convert.ts`
- Create: `src/main/__tests__/audio-convert.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// src/main/__tests__/audio-convert.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as child_process from 'child_process';
import * as fs from 'fs';

vi.mock('child_process');
vi.mock('fs');

// Import after mocks are set up
const { convertToOgg, cleanupFiles } = await import('../audio-convert');

describe('convertToOgg', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('converts mp3 to ogg by shelling out to ffmpeg', () => {
    vi.mocked(child_process.execFileSync).mockReturnValue(Buffer.from(''));
    vi.mocked(fs.existsSync).mockReturnValue(true);
    vi.mocked(fs.statSync).mockReturnValue({ size: 1024 } as fs.Stats);

    const result = convertToOgg('/tmp/test.mp3');
    expect(result).toBe('/tmp/test.ogg');
    expect(child_process.execFileSync).toHaveBeenCalledWith(
      'ffmpeg',
      expect.arrayContaining(['-i', '/tmp/test.mp3']),
      expect.objectContaining({ timeout: 30_000 }),
    );
  });

  it('returns null when ffmpeg fails', () => {
    vi.mocked(child_process.execFileSync).mockImplementation(() => {
      throw new Error('ffmpeg not found');
    });

    const result = convertToOgg('/tmp/test.mp3');
    expect(result).toBeNull();
  });

  it('returns null when output file is empty', () => {
    vi.mocked(child_process.execFileSync).mockReturnValue(Buffer.from(''));
    vi.mocked(fs.existsSync).mockReturnValue(true);
    vi.mocked(fs.statSync).mockReturnValue({ size: 0 } as fs.Stats);

    const result = convertToOgg('/tmp/test.mp3');
    expect(result).toBeNull();
  });
});

describe('cleanupFiles', () => {
  it('removes all provided paths silently', () => {
    vi.mocked(fs.unlinkSync).mockReturnValue(undefined);

    cleanupFiles('/tmp/a.mp3', '/tmp/b.ogg', null);
    expect(fs.unlinkSync).toHaveBeenCalledTimes(2);
  });

  it('ignores errors on missing files', () => {
    vi.mocked(fs.unlinkSync).mockImplementation(() => {
      throw new Error('ENOENT');
    });

    // Should not throw
    cleanupFiles('/tmp/a.mp3');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/main/__tests__/audio-convert.test.ts`
Expected: FAIL - module not found

- [ ] **Step 3: Write the implementation**

```typescript
// src/main/audio-convert.ts
/**
 * Shared audio conversion utilities.
 *
 * Provides MP3-to-OGG Opus conversion via ffmpeg for Telegram voice notes,
 * and temp file cleanup helpers.
 */

import { execFileSync } from 'child_process';
import * as fs from 'fs';
import { createLogger } from './logger';

const log = createLogger('audio-convert');

/**
 * Convert an audio file to OGG Opus format for Telegram voice notes.
 * Returns the output path on success, or null if conversion fails.
 *
 * Requires ffmpeg with libopus support installed on the system.
 */
export function convertToOgg(inputPath: string): string | null {
  const outputPath = inputPath.replace(/\.[^.]+$/, '') + '.ogg';

  try {
    execFileSync(
      'ffmpeg',
      ['-y', '-i', inputPath, '-c:a', 'libopus', '-b:a', '64k', '-vn', outputPath],
      { stdio: 'pipe', timeout: 30_000 },
    );

    if (fs.existsSync(outputPath) && fs.statSync(outputPath).size > 0) {
      return outputPath;
    }
  } catch (e) {
    log.warn(`OGG conversion failed: ${e}`);
  }

  return null;
}

/**
 * Remove temp audio files. Accepts nulls safely.
 */
export function cleanupFiles(...paths: (string | null | undefined)[]): void {
  for (const p of paths) {
    if (p) {
      try {
        fs.unlinkSync(p);
      } catch { /* noop - file may already be gone */ }
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/main/__tests__/audio-convert.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/audio-convert.ts src/main/__tests__/audio-convert.test.ts
git commit -m "feat: extract shared audio conversion module"
```

---

### Task 2: ElevenLabs credit exhaustion tracking

**Files:**
- Modify: `src/main/tts.ts` (lines 388-431, the `synthesise` function and surrounding area)
- Create: `src/main/__tests__/tts-credits.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// src/main/__tests__/tts-credits.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';

// We test the exported credit-tracking functions
const { markElevenLabsExhausted, isElevenLabsExhausted, resetElevenLabsStatus, COOLDOWN_MS } =
  await import('../tts');

describe('ElevenLabs credit exhaustion', () => {
  beforeEach(() => {
    resetElevenLabsStatus();
  });

  it('starts as not exhausted', () => {
    expect(isElevenLabsExhausted()).toBe(false);
  });

  it('marks exhausted after call', () => {
    markElevenLabsExhausted();
    expect(isElevenLabsExhausted()).toBe(true);
  });

  it('auto-resets after cooldown period', () => {
    markElevenLabsExhausted();
    expect(isElevenLabsExhausted()).toBe(true);

    // Simulate time passing beyond cooldown
    vi.useFakeTimers();
    vi.advanceTimersByTime(COOLDOWN_MS + 1000);
    expect(isElevenLabsExhausted()).toBe(false);
    vi.useRealTimers();
  });

  it('can be manually reset', () => {
    markElevenLabsExhausted();
    resetElevenLabsStatus();
    expect(isElevenLabsExhausted()).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/main/__tests__/tts-credits.test.ts`
Expected: FAIL - exports not found

- [ ] **Step 3: Add credit tracking to tts.ts**

Add near the top of `tts.ts` (after the logger, around line 17):

```typescript
// ---------------------------------------------------------------------------
// ElevenLabs credit exhaustion tracking
// ---------------------------------------------------------------------------

/** Cooldown period after detecting credit exhaustion (30 minutes). */
export const COOLDOWN_MS = 30 * 60 * 1000;

let _elevenLabsExhaustedAt: number | null = null;

/** Mark ElevenLabs as credit-exhausted. Starts a cooldown timer. */
export function markElevenLabsExhausted(): void {
  _elevenLabsExhaustedAt = Date.now();
  log.warn(`ElevenLabs credits exhausted - skipping for ${COOLDOWN_MS / 60_000} minutes`);
}

/** Check if ElevenLabs is in credit-exhaustion cooldown. Auto-resets after COOLDOWN_MS. */
export function isElevenLabsExhausted(): boolean {
  if (_elevenLabsExhaustedAt === null) return false;
  if (Date.now() - _elevenLabsExhaustedAt > COOLDOWN_MS) {
    _elevenLabsExhaustedAt = null;
    return false;
  }
  return true;
}

/** Reset credit exhaustion status (for testing or manual recovery). */
export function resetElevenLabsStatus(): void {
  _elevenLabsExhaustedAt = null;
}
```

- [ ] **Step 4: Wire credit detection into synthesise()**

Modify the ElevenLabs block in `synthesise()`. Change the condition and catch:

```typescript
  // Primary: ElevenLabs streaming (with concurrency limit)
  if (config.ELEVENLABS_API_KEY && config.ELEVENLABS_VOICE_ID && !isElevenLabsExhausted()) {
    await acquireTtsSlot();
    try {
      return await synthesiseElevenLabsStream(text);
    } catch (e) {
      // Detect credit exhaustion (401 Unauthorized, 402 Payment Required, 429 Too Many Requests)
      const errMsg = String(e);
      if (/\b(401|402|429)\b/.test(errMsg)) {
        markElevenLabsExhausted();
      }
      log.warn(`ElevenLabs failed (${e}), trying Fal...`);
    } finally {
      releaseTtsSlot();
    }
  }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run src/main/__tests__/tts-credits.test.ts`
Expected: PASS

- [ ] **Step 6: Run full type check**

Run: `npx tsc --noEmit`
Expected: Clean

- [ ] **Step 7: Commit**

```bash
git add src/main/tts.ts src/main/__tests__/tts-credits.test.ts
git commit -m "feat: track ElevenLabs credit exhaustion with 30-min cooldown"
```

---

### Task 3: Wire voice-note.ts to use shared audio-convert

**Files:**
- Modify: `src/main/jobs/voice-note.ts` (lines 15, 92-115, 314-322)

- [ ] **Step 1: Replace local convertToOgg with import from audio-convert**

In `voice-note.ts`:

1. Remove `import { execSync } from 'child_process';` (line 15) - no longer needed.
2. Add import: `import { convertToOgg, cleanupFiles } from '../audio-convert';`
3. Remove the entire local `convertToOgg` function (lines 92-115).
4. Replace the cleanup block (lines 314-322) with: `cleanupFiles(audioPath, oggPath);`

- [ ] **Step 2: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean

- [ ] **Step 3: Commit**

```bash
git add src/main/jobs/voice-note.ts
git commit -m "refactor: use shared audio-convert in voice-note job"
```

---

### Task 4: Add voice note support to heartbeat

**Files:**
- Modify: `src/main/jobs/heartbeat.ts`
- Create: `src/main/__tests__/heartbeat-voice.test.ts`

- [ ] **Step 1: Write the failing test for response parsing**

```typescript
// src/main/__tests__/heartbeat-voice.test.ts
import { describe, it, expect } from 'vitest';

const { parseHeartbeatResponse } = await import('../jobs/heartbeat');

describe('parseHeartbeatResponse', () => {
  it('parses REACH_OUT prefix', () => {
    const result = parseHeartbeatResponse('[REACH_OUT] Hey, thought of you');
    expect(result).toEqual({ type: 'REACH_OUT', message: 'Hey, thought of you' });
  });

  it('parses VOICE_NOTE prefix', () => {
    const result = parseHeartbeatResponse('[VOICE_NOTE] I was just thinking about our conversation');
    expect(result).toEqual({ type: 'VOICE_NOTE', message: 'I was just thinking about our conversation' });
  });

  it('parses HEARTBEAT_OK prefix', () => {
    const result = parseHeartbeatResponse('[HEARTBEAT_OK] Too soon to reach out');
    expect(result).toEqual({ type: 'HEARTBEAT_OK', message: 'Too soon to reach out' });
  });

  it('parses SUPPRESS prefix', () => {
    const result = parseHeartbeatResponse('[SUPPRESS] User is away');
    expect(result).toEqual({ type: 'SUPPRESS', message: 'User is away' });
  });

  it('parses ASK prefix with options', () => {
    const result = parseHeartbeatResponse('[ASK] Should I check in about the project? | Yes | No | Later');
    expect(result).toEqual({
      type: 'ASK',
      message: 'Should I check in about the project?',
      options: ['Yes', 'No', 'Later'],
    });
  });

  it('returns UNKNOWN for unrecognized format', () => {
    const result = parseHeartbeatResponse('Just some random text');
    expect(result).toEqual({ type: 'UNKNOWN', message: 'Just some random text' });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/main/__tests__/heartbeat-voice.test.ts`
Expected: FAIL - parseHeartbeatResponse not found

- [ ] **Step 3: Add parseHeartbeatResponse function**

Add to `heartbeat.ts` before `handleResponse`:

```typescript
// ---------------------------------------------------------------------------
// Response parsing
// ---------------------------------------------------------------------------

export interface HeartbeatParsed {
  type: 'REACH_OUT' | 'VOICE_NOTE' | 'HEARTBEAT_OK' | 'SUPPRESS' | 'ASK' | 'UNKNOWN';
  message: string;
  options?: string[];
}

export function parseHeartbeatResponse(response: string): HeartbeatParsed {
  const stripped = response.trim();

  if (stripped.startsWith('[VOICE_NOTE]')) {
    return { type: 'VOICE_NOTE', message: stripped.slice('[VOICE_NOTE]'.length).trim() };
  }

  if (stripped.startsWith('[REACH_OUT]')) {
    return { type: 'REACH_OUT', message: stripped.slice('[REACH_OUT]'.length).trim() };
  }

  if (stripped.startsWith('[HEARTBEAT_OK]')) {
    return { type: 'HEARTBEAT_OK', message: stripped.slice('[HEARTBEAT_OK]'.length).trim() };
  }

  if (stripped.startsWith('[SUPPRESS]')) {
    return { type: 'SUPPRESS', message: stripped.slice('[SUPPRESS]'.length).trim() };
  }

  if (stripped.startsWith('[ASK]')) {
    const content = stripped.slice('[ASK]'.length).trim();
    const parts = content.split('|').map((s) => s.trim());
    return {
      type: 'ASK',
      message: parts[0],
      options: parts.slice(1),
    };
  }

  return { type: 'UNKNOWN', message: stripped };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/main/__tests__/heartbeat-voice.test.ts`
Expected: PASS

- [ ] **Step 5: Add new imports to heartbeat.ts**

```typescript
import * as fs from 'fs';
import { synthesise, isElevenLabsExhausted } from '../tts';
import { sendVoiceNote, sendButtons } from '../telegram';
import { convertToOgg, cleanupFiles } from '../audio-convert';
```

- [ ] **Step 6: Rewrite handleResponse to use parseHeartbeatResponse**

Replace the existing `handleResponse` function:

```typescript
async function handleResponse(response: string): Promise<string> {
  const config = getConfig();
  const parsed = parseHeartbeatResponse(response);

  switch (parsed.type) {
    case 'REACH_OUT': {
      logHeartbeat('REACH_OUT', '', parsed.message);
      await deliverTextMessage(parsed.message, config);
      return `REACH_OUT: ${parsed.message.slice(0, 80)}`;
    }

    case 'VOICE_NOTE': {
      logHeartbeat('VOICE_NOTE', '', parsed.message);
      await deliverVoiceNote(parsed.message, config);
      return `VOICE_NOTE: ${parsed.message.slice(0, 80)}`;
    }

    case 'HEARTBEAT_OK': {
      logHeartbeat('HEARTBEAT_OK', parsed.message);
      return `OK: ${parsed.message.slice(0, 80)}`;
    }

    case 'SUPPRESS': {
      logHeartbeat('SUPPRESS', parsed.message);
      return `Suppressed: ${parsed.message.slice(0, 80)}`;
    }

    case 'ASK': {
      logHeartbeat('ASK', parsed.message);
      await deliverAskMessage(parsed.message, parsed.options || ['Yes', 'No'], config);
      return `ASK: ${parsed.message.slice(0, 80)}`;
    }

    default: {
      logHeartbeat('UNKNOWN', parsed.message.slice(0, 500));
      return `Unknown format: ${parsed.message.slice(0, 80)}`;
    }
  }
}
```

- [ ] **Step 7: Add delivery helper functions**

Add below `handleResponse`:

```typescript
// ---------------------------------------------------------------------------
// Delivery helpers
// ---------------------------------------------------------------------------

async function deliverTextMessage(message: string, config: ReturnType<typeof getConfig>): Promise<void> {
  if (isMacIdle()) {
    try {
      await sendTelegram(message);
      log.info('Sent text via Telegram (Mac idle)');
    } catch (e) {
      log.error(`Telegram send failed: ${e}`);
    }
  } else {
    log.info('Mac active - local only, skipping Telegram');
  }

  sendNotification(config.AGENT_DISPLAY_NAME, message.slice(0, 200));
  await queueMessage(message, 'heartbeat');
}

async function deliverVoiceNote(message: string, config: ReturnType<typeof getConfig>): Promise<void> {
  // Always queue text + notification regardless of voice success
  sendNotification(config.AGENT_DISPLAY_NAME, message.slice(0, 200));
  await queueMessage(message, 'heartbeat');

  // Only send voice via Telegram if Mac is idle
  if (!isMacIdle()) {
    log.info('Mac active - local only, skipping voice note');
    return;
  }

  // Check if ElevenLabs is available
  if (isElevenLabsExhausted()) {
    log.info('ElevenLabs exhausted - falling back to text');
    await sendTelegram(message);
    return;
  }

  // Synthesise speech
  let audioPath: string | null = null;
  try {
    audioPath = await synthesise(message);
    if (!audioPath || !fs.existsSync(audioPath) || fs.statSync(audioPath).size === 0) {
      log.warn('TTS produced no audio - sending as text');
      await sendTelegram(message);
      return;
    }
  } catch (e) {
    log.warn(`TTS failed: ${e} - sending as text`);
    await sendTelegram(message);
    return;
  }

  // Convert to OGG for Telegram voice notes
  const oggPath = convertToOgg(audioPath);
  const sendPath = oggPath ?? audioPath;

  const success = await sendVoiceNote(sendPath);
  if (!success) {
    log.warn('Voice note send failed - sending as text');
    await sendTelegram(message);
  } else {
    log.info('Sent voice note via Telegram');
  }

  // Clean up temp audio files (MP3 and OGG)
  cleanupFiles(audioPath, oggPath);
}

async function deliverAskMessage(
  question: string,
  options: string[],
  config: ReturnType<typeof getConfig>,
): Promise<void> {
  if (!isMacIdle()) {
    log.info('Mac active - skipping Telegram ASK');
    sendNotification(config.AGENT_DISPLAY_NAME, question.slice(0, 200));
    return;
  }

  try {
    const buttons = [options.map((opt) => ({ text: opt, callback_data: opt.toLowerCase() }))];
    await sendButtons(question, buttons);
    log.info(`Sent ASK via Telegram: ${question.slice(0, 60)}`);
  } catch (e) {
    log.error(`Telegram ASK failed: ${e}`);
  }
}
```

- [ ] **Step 8: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean

- [ ] **Step 9: Run all tests**

Run: `npx vitest run`
Expected: All pass

- [ ] **Step 10: Commit**

```bash
git add src/main/jobs/heartbeat.ts src/main/__tests__/heartbeat-voice.test.ts
git commit -m "feat: heartbeat voice notes with ElevenLabs fallback and ASK support"
```

---

### Task 5: Update heartbeat prompt

**Files:**
- Modify: `src/main/jobs/heartbeat.ts` (the `HEARTBEAT_PROMPT` constant, lines 48-61)

- [ ] **Step 1: Update the HEARTBEAT_PROMPT constant**

Replace the existing `HEARTBEAT_PROMPT`:

```typescript
const HEARTBEAT_PROMPT =
  '[HEARTBEAT CHECK - internal evaluation, not a conversation]\n\n' +
  'You are deciding whether to reach out to the user unprompted. ' +
  'You have access to your full conversation history and memory tools.\n\n' +
  'First, review your state - use recall, daily_digest, or your memory tools ' +
  'if you need to refresh context. You may also update your HEARTBEAT.md ' +
  'checklist via write_note if your monitoring criteria should evolve.\n\n' +
  '## Available tools during this evaluation\n\n' +
  '- **ask_user** (via the interact tool): Send a question to the user via ' +
  'Telegram with Yes/No/custom buttons. Use for confirmations or choices. ' +
  'The user will see inline buttons and can tap to respond. Use this when ' +
  'you need input before deciding what to do.\n' +
  '- **send_telegram**: Send a text message directly to the user via Telegram.\n\n' +
  'Then evaluate using the checklist below. Respond with exactly ONE prefix:\n\n' +
  '[REACH_OUT] followed by the message you\'d send. Be specific. ' +
  'Reference the actual thing. Don\'t say \'just checking in.\'\n\n' +
  '[VOICE_NOTE] followed by the message, spoken naturally as if recording ' +
  'a voice memo. Use this when the thought is personal, warm, or would ' +
  'land better as a voice than text. 2-4 sentences. No greeting, no sign-off. ' +
  'NOTE: If voice synthesis is unavailable, this falls back to text automatically.\n\n' +
  '[ASK] followed by a question and pipe-separated options. Example:\n' +
  '[ASK] Want me to check in about the project later? | Yes | No | Tomorrow\n' +
  'The user will see this as tappable buttons in Telegram.\n\n' +
  '[HEARTBEAT_OK] followed by a brief reason why now isn\'t the right time.\n\n' +
  '[SUPPRESS] followed by a brief reason if you actively shouldn\'t reach out ' +
  '(e.g. he\'s away, it\'s too soon, he needs space).\n\n' +
  'Keep it short. 1-3 sentences for the message, one line for OK/SUPPRESS.';
```

- [ ] **Step 2: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean

- [ ] **Step 3: Commit**

```bash
git add src/main/jobs/heartbeat.ts
git commit -m "feat: update heartbeat prompt with voice note, ASK, and tool awareness"
```

---

### Task 6: Clean up voice-note.ts imports

**Files:**
- Modify: `src/main/jobs/voice-note.ts`

- [ ] **Step 1: Remove unused execSync import**

Remove `import { execSync } from 'child_process';` (line 15). The `fs` import stays (used for `existsSync`/`statSync`).

- [ ] **Step 2: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean

- [ ] **Step 3: Commit**

```bash
git add src/main/jobs/voice-note.ts
git commit -m "chore: clean up unused imports in voice-note"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full test suite**

Run: `npx vitest run`
Expected: All tests pass

- [ ] **Step 2: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean

- [ ] **Step 3: Build the app**

Run: `npx electron-vite build`
Expected: Build succeeds
