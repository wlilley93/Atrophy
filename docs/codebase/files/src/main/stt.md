# src/main/stt.ts - Speech-to-Text

**Dependencies:** Node.js built-ins (`child_process`, `fs`, `path`, `os`, `crypto`), `./config`  
**Purpose:** Speech transcription via whisper.cpp with Metal acceleration

## Overview

This module handles speech-to-text transcription by spawning the whisper.cpp binary as a subprocess with Metal acceleration on Apple Silicon. It provides two transcription modes with different latency and accuracy tradeoffs - a full-quality mode for conversation turns and a fast mode for wake word detection.

## Two Transcription Modes

| Property | `transcribe()` | `transcribeFast()` |
|----------|----------------|---------------------|
| Use case | Full conversation turns | Wake word clips (~2 seconds) |
| Model | `config.WHISPER_MODEL` | Prefers `ggml-tiny.en.bin` in same directory |
| Threads | 4 | 2 |
| Timeout | 30 seconds | 5 seconds |
| Error handling | Returns empty string | Returns empty string |
| Typical latency | < 1 second for short clips | < 200ms for 2-second clips |

## Temp File Management

```typescript
function secureTmp(ext: string): string {
  const name = crypto.randomBytes(12).toString('hex') + ext;
  return path.join(os.tmpdir(), 'atrophy-stt-' + name);
}
```

**Security:** Random filenames (24 hex chars) prevent TOCTOU race conditions and symlink attacks. The `atrophy-stt-` prefix aids debugging and cleanup.

## WAV File Writing

```typescript
function writeWav(audioData: Float32Array, sampleRate: number, channels: number): string {
  const tmpPath = secureTmp('.wav');

  // Convert float32 [-1, 1] to int16
  const int16 = new Int16Array(audioData.length);
  for (let i = 0; i < audioData.length; i++) {
    const s = Math.max(-1, Math.min(1, audioData[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }

  const dataBytes = int16.length * 2;
  const bitsPerSample = 16;
  const blockAlign = channels * (bitsPerSample / 8);
  const byteRate = sampleRate * blockAlign;

  // WAV header (44 bytes)
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + dataBytes, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);  // chunk size
  header.writeUInt16LE(1, 20);   // PCM format
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write('data', 36);
  header.writeUInt32LE(dataBytes, 40);

  const body = Buffer.from(int16.buffer, int16.byteOffset, int16.byteLength);
  fs.writeFileSync(tmpPath, Buffer.concat([header, body]));
  return tmpPath;
}
```

### Audio Format Conversion

**Float32 to Int16:**
- Input: Float32Array with values in range [-1.0, 1.0]
- Output: Int16Array with values in range [-32768, 32767]
- Asymmetric scaling: negative values map to [-32768, 0], positive to [0, 32767]

### WAV Header Structure

| Offset | Size | Field | Value |
|--------|------|-------|-------|
| 0 | 4 | ChunkID | `RIFF` |
| 4 | 4 | ChunkSize | `36 + dataBytes` |
| 8 | 4 | Format | `WAVE` |
| 12 | 4 | Subchunk1ID | `fmt ` |
| 16 | 4 | Subchunk1Size | `16` (PCM) |
| 20 | 2 | AudioFormat | `1` (PCM) |
| 22 | 2 | NumChannels | `1` (mono) |
| 24 | 4 | SampleRate | `16000` |
| 28 | 4 | ByteRate | `32000` |
| 32 | 2 | BlockAlign | `2` |
| 34 | 2 | BitsPerSample | `16` |
| 36 | 4 | Subchunk2ID | `data` |
| 40 | 4 | Subchunk2Size | `int16.length * 2` |

**Result:** Standard 16kHz mono 16-bit PCM WAV file compatible with whisper.cpp.

## Full Transcription (transcribe)

```typescript
export function transcribe(audioData: Float32Array): Promise<string> {
  return new Promise((resolve, reject) => {
    const config = getConfig();
    const wavPath = writeWav(audioData, config.SAMPLE_RATE, config.CHANNELS);

    const proc = spawn(config.WHISPER_BIN, [
      '-m', config.WHISPER_MODEL,
      '-f', wavPath,
      '--no-timestamps',
      '-t', '4',
      '--language', 'en',
    ], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    proc.stdout?.on('data', (chunk: Buffer) => {
      stdout += chunk.toString();
    });

    const timeout = setTimeout(() => {
      try { proc.kill(); } catch { /* noop */ }
      cleanup();
      reject(new Error('Whisper transcription timed out (30s)'));
    }, 30000);

    function cleanup() {
      try { fs.unlinkSync(wavPath); } catch { /* noop */ }
    }

    proc.on('close', (code) => {
      clearTimeout(timeout);
      cleanup();

      if (code !== 0) {
        resolve('');  // Graceful degradation
        return;
      }

      // Parse output - skip metadata lines starting with [
      const lines = stdout
        .split('\n')
        .map((l) => l.trim())
        .filter((l) => l && !l.startsWith('['));

      resolve(lines.join(' '));
    });

    proc.on('error', () => {
      clearTimeout(timeout);
      cleanup();
      resolve('');  // Graceful degradation
    });
  });
}
```

### Whisper.cpp Command Line

```
whisper-cli -m <model_path> -f <wav_path> --no-timestamps -t 4 --language en
```

| Flag | Value | Purpose |
|------|-------|---------|
| `-m` | Model path | GGML model file (e.g., `ggml-tiny.en.bin`) |
| `-f` | WAV path | Input audio file |
| `--no-timestamps` | (flag) | Suppress `[00:00.000 --> 00:02.000]` prefixes |
| `-t` | `4` | Thread count for parallel processing |
| `--language` | `en` | Force English (skip language detection) |

### Output Parsing

Whisper.cpp output includes metadata lines that must be filtered:

```
[00:00:00.000 --> 00:00:02.000]   Hello, how are you today?
```

After parsing (split, trim, filter lines starting with `[`, join): `Hello, how are you today?`

### Error Handling

- **Non-zero exit code:** Returns empty string (graceful degradation)
- **Process error:** Returns empty string
- **Timeout:** Kills process, cleans up temp file, rejects with error
- **Cleanup:** Always runs in `close` and `error` handlers

## Fast Transcription (transcribeFast)

```typescript
export function transcribeFast(audioData: Float32Array): Promise<string> {
  return new Promise((resolve, reject) => {
    const config = getConfig();

    // Prefer tiny model if available
    const tinyModel = path.join(
      path.dirname(config.WHISPER_MODEL),
      'ggml-tiny.en.bin',
    );
    const model = fs.existsSync(tinyModel) ? tinyModel : config.WHISPER_MODEL;
    const wavPath = writeWav(audioData, config.SAMPLE_RATE, config.CHANNELS);

    const proc = spawn(config.WHISPER_BIN, [
      '-m', model,
      '-f', wavPath,
      '--no-timestamps',
      '-t', '2',  // Fewer threads for lighter footprint
      '--language', 'en',
    ], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    // ... same pattern as transcribe() but with 5-second timeout
  });
}
```

**Optimizations for speed:**
1. Uses `ggml-tiny.en.bin` (smallest, fastest model) if available
2. Only 2 threads (lower CPU usage for continuous wake word detection)
3. 5-second timeout (fail fast on hangs)

## Graceful Degradation Pattern

Both functions return empty string on error rather than throwing:

```typescript
if (code !== 0) {
  resolve('');  // Graceful degradation
  return;
}
```

**Why:** Voice input is a convenience feature. A transcription failure should never crash the app or block the UI. Callers check for empty string and handle gracefully (e.g., "I didn't catch that").

## Timeout Implementation

```typescript
const timeout = setTimeout(() => {
  try { proc.kill(); } catch { /* noop */ }
  cleanup();
  reject(new Error('Whisper transcription timed out (30s)'));
}, 30000);
```

**Purpose:** Prevents hung processes from blocking indefinitely. The timeout is cleared when the process exits normally.

## File I/O Summary

| Operation | Path | When |
|-----------|------|------|
| Write | `/tmp/atrophy-stt-<random>.wav` | Before transcription |
| Delete | Same path | After transcription completes |

## Dependencies

| Binary | Path | Purpose |
|--------|------|---------|
| whisper-cli | `<bundle>/vendor/whisper.cpp/build/bin/whisper-cli` | Transcription |
| Model | `<bundle>/vendor/whisper.cpp/models/ggml-tiny.en.bin` | Speech recognition |

## Exported API

| Function | Purpose |
|----------|---------|
| `transcribe(audioData)` | Full-quality transcription for conversation turns |
| `transcribeFast(audioData)` | Fast transcription for wake word detection |

## See Also

- `src/main/audio.ts` - Calls `transcribe()` for push-to-talk
- `src/main/wake-word.ts` - Calls `transcribeFast()` for wake word detection
- `src/main/config.ts` - Provides WHISPER_BIN and WHISPER_MODEL paths
