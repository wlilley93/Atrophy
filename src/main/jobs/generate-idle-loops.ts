/**
 * Generate the three idle loop videos for the companion avatar via LivePortrait.
 * Port of scripts/agents/companion/generate_idle_loops.py.
 *
 * Renders three idle state videos from the source portrait using LivePortrait
 * (audio-driven face animation):
 *   - idle_loop.mp4      - neutral, at rest
 *   - idle_thinking.mp4  - slight downward gaze
 *   - idle_listening.mp4 - forward attention
 *
 * Uses a synthetic breathing/idle driver audio to produce subtle motion.
 *
 * Requires: LivePortrait installed, source image at avatar/source/face.png.
 */

import { spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from '../config';
import { registerJob } from './index';
import { createLogger } from '../logger';

const log = createLogger('generate-idle-loops');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const IDLE_DURATION_SEC = 12;
const SAMPLE_RATE = 16000;

// LivePortrait path - check common install locations
const LIVEPORTRAIT_CANDIDATES = [
  path.join(process.env.HOME || '', 'LivePortrait'),
  path.join(process.env.HOME || '', 'Projects', 'LivePortrait'),
  '/opt/LivePortrait',
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function findLivePortrait(): string | null {
  // Check env var first
  const envPath = process.env.LIVEPORTRAIT_PATH;
  if (envPath && fs.existsSync(envPath)) return envPath;

  for (const candidate of LIVEPORTRAIT_CANDIDATES) {
    if (fs.existsSync(candidate) && fs.existsSync(path.join(candidate, 'inference.py'))) {
      return candidate;
    }
  }
  return null;
}

function idleDriverPath(avatarDir: string): string {
  return path.join(avatarDir, 'source', 'idle_driver.wav');
}

/**
 * Generate a synthetic breathing/idle driver WAV file.
 *
 * Produces a very quiet sine wave (0.2Hz) with tiny noise - just enough
 * for LivePortrait to animate subtle breathing movement without any
 * speech-like artefacts.
 */
function generateIdleDriver(outputPath: string): void {
  if (fs.existsSync(outputPath)) {
    log.info(`Idle driver already exists: ${outputPath}`);
    return;
  }

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const nSamples = SAMPLE_RATE * IDLE_DURATION_SEC;

  // WAV header for mono 16-bit PCM
  const dataSize = nSamples * 2;
  const fileSize = 44 + dataSize;
  const buffer = Buffer.alloc(fileSize);

  // RIFF header
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(fileSize - 8, 4);
  buffer.write('WAVE', 8);

  // fmt chunk
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16); // chunk size
  buffer.writeUInt16LE(1, 20); // PCM format
  buffer.writeUInt16LE(1, 22); // mono
  buffer.writeUInt32LE(SAMPLE_RATE, 24); // sample rate
  buffer.writeUInt32LE(SAMPLE_RATE * 2, 28); // byte rate
  buffer.writeUInt16LE(2, 32); // block align
  buffer.writeUInt16LE(16, 34); // bits per sample

  // data chunk
  buffer.write('data', 36);
  buffer.writeUInt32LE(dataSize, 40);

  // Generate samples - subtle breathing sine + tiny noise
  // Python version uses hash(i) % 20 - 10 for noise. We replicate with
  // a simple integer hash (Knuth multiplicative) to stay deterministic.
  for (let i = 0; i < nSamples; i++) {
    const t = i / SAMPLE_RATE;
    const breath = Math.sin(2 * Math.PI * 0.2 * t) * 50;
    const noise = (((i * 2654435761) >>> 0) % 20) - 10;
    let sample = Math.round(breath + noise);
    sample = Math.max(-32768, Math.min(32767, sample));
    buffer.writeInt16LE(sample, 44 + i * 2);
  }

  fs.writeFileSync(outputPath, buffer);
  log.info(`Generated idle driver audio: ${outputPath}`);
}

/**
 * Render a single idle video using LivePortrait.
 */
function renderIdle(
  livePortraitPath: string,
  sourceImage: string,
  driverAudio: string,
  outputPath: string,
  label: string,
  resolution: number,
): boolean {
  if (fs.existsSync(outputPath)) {
    log.info(`Already exists: ${outputPath} - skipping`);
    return true;
  }

  log.info(`Rendering ${label}...`);

  const env = {
    ...process.env,
    PYTORCH_ENABLE_MPS_FALLBACK: '1',
  };

  const result = spawnSync(
    'python',
    [
      'inference.py',
      '--source_image', sourceImage,
      '--driving_audio', driverAudio,
      '--output', outputPath,
      '--size', String(resolution),
    ],
    {
      cwd: livePortraitPath,
      encoding: 'utf-8',
      timeout: 600_000, // 10 minute timeout
      env,
      stdio: 'pipe',
    },
  );

  if (result.status !== 0) {
    log.error(`${label} FAILED: ${(result.stderr || '').slice(0, 300)}`);
    return false;
  }

  if (fs.existsSync(outputPath)) {
    log.info(`Done: ${outputPath}`);
    return true;
  }

  log.warn(`${label}: render completed but file not found at ${outputPath}`);
  return false;
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runGenerateIdleLoops(agentName: string): Promise<string> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  // Validate source image
  if (!fs.existsSync(config.SOURCE_IMAGE)) {
    return 'Skipped: source image not found. Run generate-face first and select a face.';
  }

  // Find LivePortrait installation
  const livePortraitPath = findLivePortrait();
  if (!livePortraitPath) {
    return 'Skipped: LivePortrait not found. Set LIVEPORTRAIT_PATH env var or install to ~/LivePortrait.';
  }

  log.info(`LivePortrait: ${livePortraitPath}`);
  log.info(`Source image: ${config.SOURCE_IMAGE}`);

  // Generate idle driver audio
  const driverPath = idleDriverPath(config.AVATAR_DIR);
  generateIdleDriver(driverPath);

  // Render all three idle states
  const targets = [
    { path: config.IDLE_LOOP, label: 'idle_loop (rest)' },
    { path: config.IDLE_THINKING, label: 'idle_thinking' },
    { path: config.IDLE_LISTENING, label: 'idle_listening' },
  ];

  const results: string[] = [];
  let succeeded = 0;

  for (const target of targets) {
    const ok = renderIdle(
      livePortraitPath,
      config.SOURCE_IMAGE,
      driverPath,
      target.path,
      target.label,
      config.AVATAR_RESOLUTION,
    );
    if (ok) {
      succeeded++;
      results.push(`${target.label}: ok`);
    } else {
      results.push(`${target.label}: FAILED`);
    }
  }

  const missing = targets.filter((t) => !fs.existsSync(t.path));
  if (missing.length > 0) {
    log.warn(`${missing.length} loops failed to render`);
  } else {
    log.info('All three idle states ready');
  }

  return `Idle loops: ${succeeded}/${targets.length} rendered. ${results.join('; ')}`;
}

// ---------------------------------------------------------------------------
// Job registration
// ---------------------------------------------------------------------------

registerJob({
  name: 'generate-idle-loops',
  description: 'Generate idle loop videos (rest, thinking, listening) via LivePortrait',
  gates: [
    () => {
      const config = getConfig();
      if (!fs.existsSync(config.SOURCE_IMAGE)) {
        return 'No source image - run generate-face first';
      }
      return null;
    },
    () => {
      const lp = findLivePortrait();
      if (!lp) return 'LivePortrait not found';
      return null;
    },
  ],
  run: async () => {
    const config = getConfig();
    return runGenerateIdleLoops(config.AGENT_NAME);
  },
});
