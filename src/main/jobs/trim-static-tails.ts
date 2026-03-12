/**
 * Trim static tails from generated video loop clips.
 * Port of scripts/agents/companion/trim_static_tails.py.
 *
 * Analyzes frame-to-frame scene change scores to find where motion ends,
 * then trims each clip to remove the frozen tail. Keeps a 0.3s buffer
 * so the cut doesn't feel abrupt.
 *
 * Overwrites originals after backing up to .pretrim.mp4.
 *
 * Requires: ffmpeg and ffprobe installed.
 */

import { spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from '../config';
import { registerJob } from './index';
import { createLogger } from '../logger';

const log = createLogger('trim-static-tails');

// ---------------------------------------------------------------------------
// Constants - matching the Python source exactly
// ---------------------------------------------------------------------------

const MOTION_THRESHOLD = 0.004; // rolling avg scene score below this = static
const WINDOW_FRAMES = 24; // 1 second rolling window at 24fps
const TAIL_BUFFER = 0.3; // keep 0.3s after last motion for smooth end
const MIN_TRIM = 0.5; // only trim if saving more than 0.5s

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getVideoDuration(videoPath: string): number {
  const result = spawnSync(
    'ffprobe',
    [
      '-v', 'error',
      '-show_entries', 'format=duration',
      '-of', 'csv=p=0',
      videoPath,
    ],
    { encoding: 'utf-8', timeout: 15_000 },
  );
  return parseFloat(result.stdout.trim());
}

/**
 * Analyze frame-to-frame scene change scores and find the optimal trim point.
 * Returns the time in seconds to trim to, or null if no trim is needed.
 */
function findTrimPoint(videoPath: string): number | null {
  const duration = getVideoDuration(videoPath);

  // Extract scene change scores for every frame
  const result = spawnSync(
    'ffmpeg',
    [
      '-i', videoPath,
      '-vf', "select='gte(scene,0)',metadata=print:file=/dev/stdout",
      '-an',
      '-f', 'null',
      '-',
    ],
    { encoding: 'utf-8', timeout: 60_000 },
  );

  // Parse scene_score values from ffmpeg output
  const scores: number[] = [];
  for (const line of (result.stdout || '').split('\n')) {
    if (line.includes('scene_score')) {
      const val = line.split('=').pop();
      if (val) {
        const num = parseFloat(val);
        if (!isNaN(num)) {
          scores.push(num);
        }
      }
    }
  }

  // Need enough frames for meaningful analysis
  if (scores.length < WINDOW_FRAMES * 2) {
    return null;
  }

  const fps = scores.length / duration;

  // Compute rolling mean of scene scores
  const means: number[] = [];
  for (let i = 0; i <= scores.length - WINDOW_FRAMES; i++) {
    let sum = 0;
    for (let j = i; j < i + WINDOW_FRAMES; j++) {
      sum += scores[j];
    }
    means.push(sum / WINDOW_FRAMES);
  }

  // Find the last frame with significant motion
  let lastActive = 0;
  for (let i = 0; i < means.length; i++) {
    if (means[i] > MOTION_THRESHOLD) {
      lastActive = i + WINDOW_FRAMES;
    }
  }

  const trimTime = Math.min(lastActive / fps + TAIL_BUFFER, duration);
  const saved = duration - trimTime;

  if (saved < MIN_TRIM) {
    return null;
  }

  return trimTime;
}

/**
 * Trim a video clip to the given time, overwriting the original after backup.
 */
function trimClip(videoPath: string, trimTime: number): boolean {
  const tmpPath = videoPath.replace(/\.mp4$/, '.trimmed.mp4');

  spawnSync(
    'ffmpeg',
    [
      '-y',
      '-i', videoPath,
      '-t', trimTime.toFixed(3),
      '-c:v', 'libx264',
      '-crf', '18',
      '-pix_fmt', 'yuv420p',
      '-an',
      tmpPath,
    ],
    { stdio: 'pipe', timeout: 60_000 },
  );

  if (!fs.existsSync(tmpPath) || fs.statSync(tmpPath).size === 0) {
    // Clean up failed attempt
    try { fs.unlinkSync(tmpPath); } catch { /* ignore */ }
    return false;
  }

  // Backup original
  const bakPath = videoPath.replace(/\.mp4$/, '.pretrim.mp4');
  if (!fs.existsSync(bakPath)) {
    fs.renameSync(videoPath, bakPath);
  } else {
    fs.unlinkSync(videoPath);
  }

  // Replace with trimmed version
  fs.renameSync(tmpPath, videoPath);
  return true;
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runTrimStaticTails(agentName: string): Promise<string> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  const loopsDir = config.IDLE_LOOPS_DIR;

  if (!fs.existsSync(loopsDir)) {
    return 'Skipped: loops directory does not exist';
  }

  // Find all loop_*.mp4 files
  const clips = fs
    .readdirSync(loopsDir)
    .filter((f) => f.startsWith('loop_') && f.endsWith('.mp4'))
    .sort()
    .map((f) => path.join(loopsDir, f));

  if (clips.length === 0) {
    return 'No loop clips found';
  }

  log.info(`Analyzing ${clips.length} clips...`);

  let trimmed = 0;
  const results: string[] = [];

  for (const clip of clips) {
    const basename = path.basename(clip);
    const duration = getVideoDuration(clip);
    const trimTime = findTrimPoint(clip);

    if (trimTime === null) {
      log.info(`${basename}: ${duration.toFixed(1)}s - no trim needed`);
      results.push(`${basename}: no trim`);
      continue;
    }

    const saved = duration - trimTime;
    log.info(
      `${basename}: ${duration.toFixed(1)}s -> ${trimTime.toFixed(1)}s ` +
        `(trimming ${saved.toFixed(1)}s)`,
    );

    if (trimClip(clip, trimTime)) {
      const newDur = getVideoDuration(clip);
      log.info(`  done (${newDur.toFixed(1)}s)`);
      results.push(`${basename}: ${duration.toFixed(1)}s -> ${newDur.toFixed(1)}s`);
      trimmed++;
    } else {
      log.error(`  ${basename}: trim FAILED`);
      results.push(`${basename}: FAILED`);
    }
  }

  const summary = `Trimmed ${trimmed}/${clips.length} clips`;
  if (trimmed > 0) {
    log.info(`${summary}. Originals backed up as .pretrim.mp4`);
  } else {
    log.info(summary);
  }

  return `${summary}. ${results.join('; ')}`;
}

// ---------------------------------------------------------------------------
// Job registration
// ---------------------------------------------------------------------------

registerJob({
  name: 'trim-static-tails',
  description: 'Trim static/frozen tails from generated video loop clips using scene analysis',
  gates: [
    () => {
      // Check if ffprobe is available
      const result = spawnSync('which', ['ffprobe'], { encoding: 'utf-8', timeout: 5000 });
      if (result.status !== 0) return 'ffprobe not found';
      return null;
    },
  ],
  run: async () => {
    const config = getConfig();
    return runTrimStaticTails(config.AGENT_NAME);
  },
});
