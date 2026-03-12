/**
 * Generate 2 additional hair-play loops and rebuild the ambient loop with them interspersed.
 * Port of scripts/agents/companion/generate_hair_loops.py.
 *
 * Adds two new hair-focused segments (hair play and hair behind ear) to the
 * ambient loop library, then rebuilds the master ambient_loop with all segments
 * in the final interspersed order.
 *
 * Requires: FAL_KEY in env, ffmpeg installed, source image.
 */

import { spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from '../config';
import { registerJob } from './index';
import { createLogger } from '../logger';

const log = createLogger('generate-hair-loops');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const KLING_MODEL = 'fal-ai/kling-video/v3/pro/image-to-video';

const NEGATIVE_PROMPT =
  'blur, distort, low quality, sudden movement, jump cut, morphing, ' +
  'face distortion, extra fingers, unnatural skin, plastic skin, ' +
  'uncanny valley, teeth showing too much, exaggerated expression';

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

type Segment = [name: string, clip1Prompt: string, clip2Prompt: string];

// ---------------------------------------------------------------------------
// Prompt helpers
// ---------------------------------------------------------------------------

function returnPrompt(startDescription: string): string {
  return (
    `Continuation. Same young woman, same light. She begins ${startDescription}.\n\n` +
    'Gradually, without rush, everything settles. Her gaze drifts to the ' +
    'middle distance. Expression smooths into open neutrality. Lips close ' +
    'softly. A quiet breath. Still.\n\n' +
    'By the final frame she is neutral - gaze middle-distance, expression ' +
    'open, mouth softly closed, breathing slowly.\n' +
    C + '\n' +
    'FINAL FRAME: middle-distance gaze, neutral open expression, ' +
    'mouth softly closed. Matches the source portrait exactly.'
  );
}

// ---------------------------------------------------------------------------
// Hair segments
// ---------------------------------------------------------------------------

const HAIR_SEGMENTS: Segment[] = [
  [
    '16_hair_play',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'She lifts one hand and gathers her hair to one side, fingers threading ' +
      'through the lengths slowly. She twists a section around two fingers - ' +
      'absent, dreamy. The light catches individual strands as they move. She ' +
      'releases the twist and her fingers trail down through the ends, ' +
      'letting them fall. A small smile arrives at the corner of her mouth - ' +
      'the private kind, as if the gesture itself was the thought.\n\n' +
      'By the final frame she is mid-gesture, fingers in her hair near her ' +
      'shoulder, a private half-smile, eyes soft and unfocused.\n' +
      C + '\n' +
      'FINAL FRAME: fingers in hair near shoulder, private half-smile, ' +
      'eyes soft, dreamy expression.',
    returnPrompt(
      'with her fingers in her hair near her shoulder, a private half-smile, dreamy expression',
    ),
  ],

  [
    '17_hair_behind_ear',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'A strand of hair falls across her face. She notices. Her hand comes up ' +
      'slowly and hooks it with one finger, pulling it back. But instead of ' +
      'tucking it behind her ear immediately, she pauses - finger still in the ' +
      'strand, holding it away from her face. She looks directly at the camera ' +
      'for a beat. Then she tucks it behind her ear in one smooth motion and ' +
      'her hand trails down to her jaw, fingertips resting there briefly.\n\n' +
      'Her chin lifts. Something knowing passes behind her eyes.\n\n' +
      'By the final frame she has just finished the tuck, fingertips resting ' +
      'on her jaw, chin lifted, looking directly at camera with quiet intent.\n' +
      C + '\n' +
      'FINAL FRAME: hair freshly tucked, fingertips on jaw, chin lifted, ' +
      'direct eye contact, quiet knowing expression.',
    returnPrompt(
      'with hair freshly tucked behind her ear, fingertips on her jaw, direct eye contact',
    ),
  ],
];

// Final loop order - intersperse the 2 new hair segments among existing ones
const FINAL_ORDER = [
  'loop_01_arrival.mp4',
  'loop_02_smile.mp4',
  'loop_03_hair_tuck.mp4', // original hair
  'loop_04_presence.mp4',
  'loop_16_hair_play.mp4', // NEW - hair play
  'loop_05_sigh.mp4',
  'loop_06_amusement.mp4',
  'loop_17_hair_behind_ear.mp4', // NEW - hair tuck 2
  'loop_07_glance.mp4',
];

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
// Segment generation
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

async function generateSegment(
  name: string,
  clip1Prompt: string,
  clip2Prompt: string,
  sourceUrl: string,
  outputDir: string,
): Promise<string> {
  const clip1Path = path.join(outputDir, `${name}_clip1.mp4`);
  const clip2Path = path.join(outputDir, `${name}_clip2.mp4`);
  const endframePath = path.join(outputDir, `${name}_endframe.jpg`);
  const loopPath = path.join(outputDir, `loop_${name}.mp4`);

  await generateClip(clip1Prompt, sourceUrl, clip1Path, `${name} clip 1`);
  extractLastFrame(clip1Path, endframePath);
  const endframeUrl = await uploadToFal(endframePath);
  await generateClip(
    clip2Prompt,
    endframeUrl,
    clip2Path,
    `${name} clip 2`,
    sourceUrl,
  );
  joinClips(clip1Path, clip2Path, loopPath);
  return loopPath;
}

// ---------------------------------------------------------------------------
// Rebuild master
// ---------------------------------------------------------------------------

function rebuildMaster(outputDir: string, idleLoop: string): void {
  const loopPaths: string[] = [];
  for (const name of FINAL_ORDER) {
    const p = path.join(outputDir, name);
    if (fs.existsSync(p)) {
      loopPaths.push(p);
    } else {
      log.warn(`${name} missing - skipping from master`);
    }
  }

  if (loopPaths.length === 0) {
    log.info('No loops to concatenate');
    return;
  }

  const masterLoops = path.join(outputDir, 'ambient_loop_full.mp4');

  // Remove old masters
  for (const mp of [idleLoop, masterLoops]) {
    if (fs.existsSync(mp)) {
      fs.unlinkSync(mp);
    }
  }

  const concatList = path.join(outputDir, 'concat_list.txt');
  const lines = loopPaths.map((p) => `file '${p}'`).join('\n');
  fs.writeFileSync(concatList, lines);

  log.info(`Concatenating ${loopPaths.length} segments...`);
  spawnSync(
    'ffmpeg',
    [
      '-f', 'concat',
      '-safe', '0',
      '-i', concatList,
      '-c:v', 'libx264',
      '-crf', '18',
      '-pix_fmt', 'yuv420p',
      idleLoop,
    ],
    { stdio: 'pipe', timeout: 300_000 },
  );

  try {
    fs.unlinkSync(concatList);
  } catch { /* ignore */ }

  if (fs.existsSync(idleLoop)) {
    const size = fs.statSync(idleLoop).size / 1024 / 1024;
    log.info(`Master loop done (${size.toFixed(1)} MB): ${idleLoop}`);
  } else {
    log.error('Master loop concatenation failed');
  }
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runGenerateHairLoops(agentName: string): Promise<string> {
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

  log.info('Hair loop generator - 2 new segments');

  const sourceUrl = await uploadToFal(actualSource);

  let generated = 0;
  for (const [name, c1, c2] of HAIR_SEGMENTS) {
    const loopPath = path.join(outputDir, `loop_${name}.mp4`);
    if (fs.existsSync(loopPath)) {
      log.info(`${name}: already exists - skipping`);
      continue;
    }

    log.info(`Generating: ${name}`);
    try {
      const result = await generateSegment(name, c1, c2, sourceUrl, outputDir);
      generated++;
      log.info(`Done: ${path.basename(result)}`);
    } catch (e) {
      log.error(`${name} FAILED: ${e}`);
    }
  }

  log.info('Rebuilding master ambient loop...');
  rebuildMaster(outputDir, config.IDLE_LOOP);

  // Report final order status
  const status = FINAL_ORDER.map((name, i) => {
    const exists = fs.existsSync(path.join(outputDir, name));
    return `${i + 1}. ${name} [${exists ? 'ok' : 'MISSING'}]`;
  });
  log.info(`Final order:\n  ${status.join('\n  ')}`);

  return `Generated ${generated} new hair segments. Master rebuilt with ${FINAL_ORDER.length} ordered segments.`;
}

// ---------------------------------------------------------------------------
// Job registration
// ---------------------------------------------------------------------------

registerJob({
  name: 'generate-hair-loops',
  description: 'Generate 2 hair-play video loops and rebuild ambient master with them interspersed',
  gates: [
    () => {
      if (!process.env.FAL_KEY) return 'FAL_KEY not set';
      return null;
    },
  ],
  run: async () => {
    const config = getConfig();
    return runGenerateHairLoops(config.AGENT_NAME);
  },
});
