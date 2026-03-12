/**
 * Generate an intimate/sensual loop segment and add it to the ambient cycle.
 * Port of scripts/agents/companion/generate_intimate_loop.py.
 *
 * Produces a single ~10s loop (two 5s clips crossfaded) featuring a slow,
 * private stretch with a held look that dissolves back to neutral.
 *
 * Requires: FAL_KEY in env, ffmpeg installed, source image.
 */

import { spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from '../config';
import { registerJob } from './index';
import { createLogger } from '../logger';

const log = createLogger('generate-intimate-loop');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const KLING_MODEL = 'fal-ai/kling-video/v3/pro/image-to-video';

const NEGATIVE_PROMPT =
  'blur, distort, low quality, sudden movement, jump cut, morphing, ' +
  'face distortion, extra fingers, unnatural skin, plastic skin, ' +
  'uncanny valley, teeth showing too much, exaggerated expression, ' +
  'nudity, explicit, vulgar';

const C =
  '\nCinematic. 4K. Shallow depth of field. Warm ambient interior light, ' +
  'cool from the window. Static camera. No sudden movement.';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FalVideoResult {
  video?: { url: string };
  request_id?: string;
  status?: string;
}

// ---------------------------------------------------------------------------
// The segment: a slow, private stretch with a held look
// ---------------------------------------------------------------------------

const SEGMENT_NAME = '18_slow_stretch';

const CLIP1_PROMPT =
  'A young woman with blonde hair sits in soft natural light near a window. ' +
  'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
  'She shifts her weight. Her back arches slowly as she stretches - shoulders ' +
  'rolling back, neck lengthening. The movement is unhurried, feline. One hand ' +
  'rises and her fingertips drag slowly up the side of her neck, tracing her ' +
  'jawline. Her lips part. Her eyes close. The warm light catches the curve of ' +
  'her throat, the hollow of her collarbone.\n\n' +
  'Her head tilts into her own hand. A slow exhale through parted lips. Her ' +
  'fingers slide back down her neck to her collarbone, pressing lightly into ' +
  'the skin. Then her eyes open - heavy-lidded, directly at camera. She doesn\'t ' +
  'blink. The corner of her mouth lifts. Not a smile. An invitation. She bites ' +
  'her lower lip, barely, just the edge of her teeth catching it.\n\n' +
  'By the final frame: heavy-lidded direct eye contact, lips barely parted, ' +
  'fingertips pressing into collarbone, head tilted, the beginning of a smile ' +
  'that hasn\'t fully arrived.\n' +
  C + '\n' +
  'FINAL FRAME: heavy-lidded eye contact, lips parted, fingers on collarbone, ' +
  'head tilted, charged expression, warm light on throat and jaw.';

const CLIP2_PROMPT =
  'Continuation. Same young woman, same light. She begins with heavy-lidded ' +
  'direct eye contact, lips barely parted, fingertips pressing into her ' +
  'collarbone, head tilted.\n\n' +
  'She holds the look for a beat. Then something shifts - the tension in her ' +
  'shoulders releases. Her fingers trail down from her collarbone, slow, ' +
  'dragging lightly across her upper chest. Her hand comes to rest at the ' +
  'neckline of her top, pausing there. She exhales - her whole body softens ' +
  'with it. Her teeth release her lip.\n\n' +
  'Her eyes stay on camera but the intensity fades. The heat becomes warmth. ' +
  'Her hand drops to her lap. Her gaze drifts to the middle distance. Her ' +
  'lips close. A quiet breath. Still.\n\n' +
  'By the final frame she is neutral - gaze middle-distance, expression ' +
  'open, mouth softly closed, breathing slowly.\n' +
  C + '\n' +
  'FINAL FRAME: middle-distance gaze, neutral open expression, ' +
  'mouth softly closed. Matches the source portrait exactly.';

// ---------------------------------------------------------------------------
// Helpers - Fal AI
// ---------------------------------------------------------------------------

function getFalKey(): string {
  const key = process.env.FAL_KEY || '';
  if (!key) throw new Error('FAL_KEY environment variable is not set');
  return key;
}

async function uploadToFal(imagePath: string): Promise<string> {
  const falKey = getFalKey();
  const data = fs.readFileSync(imagePath);
  const ext = path.extname(imagePath).toLowerCase();
  const mimeMap: Record<string, string> = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
  };
  const contentType = mimeMap[ext] || 'image/png';

  const initResp = await fetch('https://rest.alpha.fal.ai/storage/upload/initiate', {
    method: 'POST',
    headers: {
      Authorization: `Key ${falKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      file_name: path.basename(imagePath),
      content_type: contentType,
    }),
  });

  if (!initResp.ok) throw new Error(`Fal upload initiate failed: ${initResp.status}`);
  const initResult = (await initResp.json()) as { upload_url: string; file_url: string };

  const uploadResp = await fetch(initResult.upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: data,
  });

  if (!uploadResp.ok) throw new Error(`Fal upload PUT failed: ${uploadResp.status}`);
  return initResult.file_url;
}

async function downloadFile(url: string, destPath: string): Promise<void> {
  const resp = await fetch(url, { signal: AbortSignal.timeout(120_000) });
  if (!resp.ok) throw new Error(`Download failed: ${resp.status}`);
  const buffer = Buffer.from(await resp.arrayBuffer());
  fs.writeFileSync(destPath, buffer);
}

async function klingGenerate(
  falKey: string,
  args: Record<string, unknown>,
): Promise<FalVideoResult> {
  const submitResp = await fetch(`https://queue.fal.run/${KLING_MODEL}`, {
    method: 'POST',
    headers: {
      Authorization: `Key ${falKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(args),
  });

  if (!submitResp.ok) {
    const body = await submitResp.text();
    throw new Error(`Fal submit ${submitResp.status}: ${body.slice(0, 300)}`);
  }

  const submitResult = (await submitResp.json()) as FalVideoResult;
  if (submitResult.video?.url) return submitResult;

  if (!submitResult.request_id) {
    throw new Error('Fal returned no video and no request_id');
  }

  const resultUrl = `https://queue.fal.run/${KLING_MODEL}/requests/${submitResult.request_id}`;
  const maxAttempts = 300;
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const pollResp = await fetch(resultUrl, {
      headers: { Authorization: `Key ${falKey}` },
    });
    if (!pollResp.ok) continue;
    const pollResult = (await pollResp.json()) as FalVideoResult;
    if (pollResult.video?.url) return pollResult;
    if (pollResult.status === 'FAILED') throw new Error('Kling video generation failed');
  }

  throw new Error('Kling video generation timed out');
}

// ---------------------------------------------------------------------------
// Helpers - ffmpeg
// ---------------------------------------------------------------------------

function extractLastFrame(videoPath: string, outputPath: string): void {
  if (fs.existsSync(outputPath)) return;

  spawnSync(
    'ffmpeg',
    ['-sseof', '-0.1', '-i', videoPath, '-vframes', '1', '-q:v', '2', outputPath],
    { stdio: 'pipe', timeout: 30_000 },
  );

  if (!fs.existsSync(outputPath)) {
    throw new Error(`Failed to extract last frame from ${path.basename(videoPath)}`);
  }
}

function getVideoDuration(videoPath: string): number {
  const result = spawnSync(
    'ffprobe',
    [
      '-v', 'error',
      '-show_entries', 'format=duration',
      '-of', 'default=noprint_wrappers=1:nokey=1',
      videoPath,
    ],
    { encoding: 'utf-8', timeout: 15_000 },
  );
  return parseFloat(result.stdout.trim());
}

function joinClips(clip1: string, clip2: string, output: string): void {
  if (fs.existsSync(output)) return;

  const duration = getVideoDuration(clip1);
  const offset = duration - 0.15;

  spawnSync(
    'ffmpeg',
    [
      '-i', clip1,
      '-i', clip2,
      '-filter_complex',
      `[0:v][1:v]xfade=transition=fade:duration=0.15:offset=${offset.toFixed(3)}[v]`,
      '-map', '[v]',
      '-c:v', 'libx264',
      '-crf', '18',
      '-pix_fmt', 'yuv420p',
      output,
    ],
    { stdio: 'pipe', timeout: 120_000 },
  );

  if (!fs.existsSync(output)) {
    throw new Error(`Failed to join ${path.basename(clip1)} + ${path.basename(clip2)}`);
  }
}

// ---------------------------------------------------------------------------
// Clip generation
// ---------------------------------------------------------------------------

async function generateClip(
  prompt: string,
  startImageUrl: string,
  outputPath: string,
  label: string,
  endImageUrl?: string,
): Promise<void> {
  if (fs.existsSync(outputPath)) {
    log.info(`${label}: exists - skipping`);
    return;
  }

  log.info(`${label}: generating...`);
  const falKey = getFalKey();

  const args: Record<string, unknown> = {
    prompt,
    start_image_url: startImageUrl,
    duration: 5,
    aspect_ratio: '9:16',
    negative_prompt: NEGATIVE_PROMPT,
    cfg_scale: 0.5,
    generate_audio: false,
  };
  if (endImageUrl) {
    args.end_image_url = endImageUrl;
  }

  const result = await klingGenerate(falKey, args);
  if (!result.video?.url) throw new Error(`${label}: no video URL in response`);

  log.info(`${label}: downloading...`);
  await downloadFile(result.video.url, outputPath);
  const size = fs.statSync(outputPath).size / 1024 / 1024;
  log.info(`${label}: saved (${size.toFixed(1)} MB)`);
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runGenerateIntimateLoop(agentName: string): Promise<string> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  const sourceImage = path.join(config.AVATAR_DIR, 'candidates', 'natural_02.png');
  if (!fs.existsSync(sourceImage)) {
    if (!fs.existsSync(config.SOURCE_IMAGE)) {
      return 'Skipped: no source image found';
    }
  }
  const actualSource = fs.existsSync(sourceImage) ? sourceImage : config.SOURCE_IMAGE;

  const outputDir = config.IDLE_LOOPS_DIR;
  fs.mkdirSync(outputDir, { recursive: true });

  const loopPath = path.join(outputDir, `loop_${SEGMENT_NAME}.mp4`);

  if (fs.existsSync(loopPath)) {
    const size = fs.statSync(loopPath).size / 1024 / 1024;
    log.info(`${SEGMENT_NAME}: already exists (${size.toFixed(1)} MB)`);
    return `Already exists: ${loopPath}`;
  }

  log.info('Intimate loop generator');

  const sourceUrl = await uploadToFal(actualSource);

  const clip1Path = path.join(outputDir, `${SEGMENT_NAME}_clip1.mp4`);
  const clip2Path = path.join(outputDir, `${SEGMENT_NAME}_clip2.mp4`);
  const endframePath = path.join(outputDir, `${SEGMENT_NAME}_endframe.jpg`);

  log.info(`Generating: ${SEGMENT_NAME}`);

  // Clip 1: neutral -> the stretch, the touch, the look
  await generateClip(CLIP1_PROMPT, sourceUrl, clip1Path, `${SEGMENT_NAME} clip 1`);

  // Extract last frame of clip 1 for clip 2's start
  extractLastFrame(clip1Path, endframePath);
  const endframeUrl = await uploadToFal(endframePath);

  // Clip 2: the held look dissolves back to neutral
  await generateClip(
    CLIP2_PROMPT,
    endframeUrl,
    clip2Path,
    `${SEGMENT_NAME} clip 2`,
    sourceUrl,
  );

  // Crossfade join
  joinClips(clip1Path, clip2Path, loopPath);

  if (fs.existsSync(loopPath)) {
    const size = fs.statSync(loopPath).size / 1024 / 1024;
    log.info(`Done: ${path.basename(loopPath)} (${size.toFixed(1)} MB)`);
    log.info(`Add to FINAL_ORDER in generate-hair-loops.ts: "loop_${SEGMENT_NAME}.mp4"`);
    return `Generated intimate loop: ${path.basename(loopPath)} (${size.toFixed(1)} MB)`;
  }

  return 'Intimate loop generation failed';
}

// ---------------------------------------------------------------------------
// Job registration
// ---------------------------------------------------------------------------

registerJob({
  name: 'generate-intimate-loop',
  description: 'Generate an intimate/sensual ambient loop segment via Kling 3.0 on Fal',
  gates: [
    () => {
      if (!process.env.FAL_KEY) return 'FAL_KEY not set';
      return null;
    },
  ],
  run: async () => {
    const config = getConfig();
    return runGenerateIntimateLoop(config.AGENT_NAME);
  },
});
