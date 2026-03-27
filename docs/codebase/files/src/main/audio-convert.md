# src/main/audio-convert.ts - Audio Conversion Utilities

**Dependencies:** `child_process`, `fs`, `./logger`  
**Purpose:** MP3 to OGG Opus conversion for Telegram voice notes

## Overview

This module provides shared audio conversion utilities, primarily for converting TTS output (MP3) to OGG Opus format required by Telegram voice notes.

**Requires:** ffmpeg with libopus support

## convertToOgg

```typescript
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
```

**Purpose:** Convert audio file to OGG Opus format.

**Parameters:**
- `inputPath`: Path to input audio file (typically MP3)

**Returns:** Output path on success, null on failure

**ffmpeg command:**
```bash
ffmpeg -y -i input.mp3 -c:a libopus -b:a 64k -vn output.ogg
```

**Flags:**
- `-y`: Overwrite output file
- `-c:a libopus`: Use Opus codec
- `-b:a 64k`: 64kbps bitrate (Telegram voice note quality)
- `-vn`: No video

**Timeout:** 30 seconds

**Output naming:** Same base name with `.ogg` extension

## cleanupFiles

```typescript
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

**Purpose:** Remove temp audio files.

**Features:**
- Accepts null/undefined safely (skips them)
- Silent failure (file may already be deleted)

**Usage:**
```typescript
// After sending voice note
cleanupFiles([audioPath, oggPath]);
```

## Usage Pattern

```typescript
// In voice-note.ts or run-task.ts
import { convertToOgg, cleanupFiles } from './audio-convert';

// Synthesize speech
const audioPath = await synthesise(text);
if (!audioPath) {
  // TTS failed
  return;
}

// Convert to OGG for Telegram
const oggPath = await convertToOgg(audioPath);
if (!oggPath) {
  // Conversion failed - send as text
  await sendMessage(text);
  cleanupFiles(audioPath);
  return;
}

// Send voice note
await sendVoiceNote(oggPath, text);

// Cleanup temp files
cleanupFiles(audioPath, oggPath);
```

## File I/O

| File | Purpose |
|------|---------|
| `/tmp/atrophy-tts-*.mp3` | TTS output (input to conversion) |
| `/tmp/atrophy-voice-*.ogg` | OGG output (for Telegram) |

## Exported API

| Function | Purpose |
|----------|---------|
| `convertToOgg(inputPath)` | Convert to OGG Opus |
| `cleanupFiles(...paths)` | Remove temp files |

## See Also

- `src/main/tts.ts` - TTS synthesis (produces MP3)
- `src/main/jobs/voice-note.ts` - Voice note job (uses conversion)
- `src/main/jobs/run-task.ts` - Task runner (uses conversion for voice delivery)
- `src/main/channels/telegram/api.ts` - Telegram voice note sending
